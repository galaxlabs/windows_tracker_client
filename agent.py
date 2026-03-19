import ctypes
import json
import logging
import os
import random
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import getpass
import platform
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import psutil
import requests
import win32gui
import win32process
from PIL import ImageGrab
from embedded_defaults import DEFAULT_CONFIG
from map_intelligence import MapIntelligenceAssistant
from version import __version__


EPOCH_OFFSET = 11644473600
UPDATE_CHECK_FILE = ".update-check.json"
QUEUE_DB_FILE = "tracker_queue.sqlite3"
BIOMETRIC_SYNC_FILE = ".biometric-sync.json"
NOTIFICATION_RUNTIME_FILE = ".notification-runtime.json"


def _base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _load_config(config_path=None):
    config = dict(DEFAULT_CONFIG)
    base_dir = _base_dir()

    override_candidates = []
    if config_path:
        override_candidates.append(Path(config_path))
    else:
        override_candidates.extend([base_dir / "config.json", Path.cwd() / "config.json"])

    for candidate in override_candidates:
        if candidate.exists():
            try:
                config.update(json.loads(candidate.read_text(encoding="utf-8-sig")))
            except json.JSONDecodeError:
                logging.exception("Failed to parse config file: %s", candidate)
            break

    if not config.get("device_id"):
        config["device_id"] = socket.gethostname()
    return config


def _server_datetime(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_version(value):
    cleaned = (value or "").strip().lstrip("vV")
    parts = []
    for piece in cleaned.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _normalize_domain(value):
    host = (value or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def chrome_time_to_datetime(value):
    if not value:
        return None
    return datetime.fromtimestamp((int(value) / 1000000) - EPOCH_OFFSET, tz=timezone.utc)


class TrackerRestartRequested(Exception):
    pass


class TrackerAgent:
    def __init__(self, config_path):
        self.config_path = Path(config_path) if config_path else None
        self.config = _load_config(config_path)
        self.base_dir = _base_dir()
        self._setup_logging()
        self._init_queue()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"token {self.config['api_key']}:{self.config['api_secret']}",
                "Accept": "application/json",
            }
        )
        self.base = self.config["site_url"].rstrip("/")
        self.device_id = self.config.get("device_id") or socket.gethostname()
        self.machine_name = socket.gethostname()
        self.windows_username = getpass.getuser()
        self.binding = {}
        self.last_history_scan = datetime.now(timezone.utc) - timedelta(seconds=int(self.config.get("history_seconds", 120)))
        self.next_snapshot_at = self._next_snapshot_time()
        self.active_call = None
        self.policy = {}
        self.current_version = __version__
        self.productivity_rules = list(self.config.get("productivity_rules") or [])
        self.device_actions_enabled = bool(self.config.get("device_actions_enabled", False))
        self.last_device_action_poll = datetime.now(timezone.utc) - timedelta(seconds=int(self.config.get("device_actions_poll_seconds", 60)))
        self.device_health_enabled = bool(self.config.get("device_health_enabled", False))
        self.last_device_health_poll = datetime.now(timezone.utc) - timedelta(seconds=int(self.config.get("device_health_poll_seconds", 300)))
        self.notifications_enabled = bool(self.config.get("notifications_enabled", False))
        self.last_notification_poll = datetime.now(timezone.utc) - timedelta(seconds=int(self.config.get("notifications_poll_seconds", 60)))
        self.notification_rules = []
        self.biometric_sync_enabled = bool(self.config.get("biometric_sync_enabled", False))
        self.biometric_device = dict(self.config.get("biometric_device") or {})
        self.last_biometric_sync = datetime.now(timezone.utc) - timedelta(minutes=int(self.config.get("biometric_sync_interval_minutes", 15)))
        self.call_metadata_enabled = bool(self.config.get("call_metadata_enabled", True))
        self.map_assistant = MapIntelligenceAssistant(
            base_dir=self.base_dir,
            config=self.config,
            device_id=self.device_id,
            call_method=self._call,
            post_method=self._post,
            notify_callback=self._show_notification,
            logger=logging.getLogger(__name__),
        )

    def _setup_logging(self):
        log_path = self.base_dir / (self.config.get("log_file") or "tracker.log")
        logging.basicConfig(
            filename=str(log_path),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )

    def _next_snapshot_time(self):
        now = datetime.now(timezone.utc)
        minimum = int(self.config.get("snapshot_min_minutes", 45))
        maximum = int(self.config.get("snapshot_max_minutes", 75))
        return now + timedelta(minutes=random.randint(minimum, maximum))

    def _post(self, method, payload):
        url = f"{self.base}/api/method/{method}"
        response = self.session.post(
            url,
            data={"payload": json.dumps(payload)},
            timeout=30,
            verify=bool(self.config.get("verify_ssl", True)),
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            body = response.text.strip()
            raise RuntimeError(f"HTTP {response.status_code} from {method}: {body}") from exc
        return response.json()

    def _call(self, method, payload=None):
        return self._post(method, payload or {})

    def _queue_db_path(self):
        return self.base_dir / (self.config.get("offline_queue_db") or QUEUE_DB_FILE)

    def _init_queue(self):
        conn = sqlite3.connect(self._queue_db_path())
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS outbound_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    method TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS device_action_history (
                    action_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    message TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _queue_event(self, method, payload):
        conn = sqlite3.connect(self._queue_db_path())
        try:
            conn.execute(
                "INSERT INTO outbound_queue (method, payload_json, created_at) VALUES (?, ?, ?)",
                (method, json.dumps(payload), _server_datetime(datetime.now(timezone.utc))),
            )
            conn.commit()
        finally:
            conn.close()

    def _flush_queue(self):
        conn = sqlite3.connect(self._queue_db_path())
        try:
            rows = conn.execute(
                "SELECT id, method, payload_json FROM outbound_queue ORDER BY id ASC LIMIT 100"
            ).fetchall()
            for row_id, method, payload_json in rows:
                payload = json.loads(payload_json)
                try:
                    self._post(method, payload)
                except requests.RequestException:
                    return
                except Exception:
                    logging.exception("Dropping invalid queued event id=%s method=%s", row_id, method)
                    conn.execute("DELETE FROM outbound_queue WHERE id = ?", (row_id,))
                    conn.commit()
                    continue

                conn.execute("DELETE FROM outbound_queue WHERE id = ?", (row_id,))
                conn.commit()
        finally:
            conn.close()

    def _send_or_queue(self, method, payload):
        try:
            return self._post(method, payload)
        except requests.RequestException:
            self._queue_event(method, payload)
            logging.warning("Queued %s event because CRM is unreachable", method)
            return None

    def _action_history_get(self, action_id):
        conn = sqlite3.connect(self._queue_db_path())
        try:
            row = conn.execute(
                "SELECT status, message, updated_at FROM device_action_history WHERE action_id = ?",
                (str(action_id),),
            ).fetchone()
            return row
        finally:
            conn.close()

    def _action_history_set(self, action_id, status, message=""):
        conn = sqlite3.connect(self._queue_db_path())
        try:
            conn.execute(
                """
                INSERT INTO device_action_history (action_id, status, message, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(action_id) DO UPDATE SET
                    status = excluded.status,
                    message = excluded.message,
                    updated_at = excluded.updated_at
                """,
                (str(action_id), status, message, _server_datetime(datetime.now(timezone.utc))),
            )
            conn.commit()
        finally:
            conn.close()

    def _biometric_sync_path(self):
        return self.base_dir / BIOMETRIC_SYNC_FILE

    def _notification_rules_path(self):
        return self.base_dir / (self.config.get("notifications_state_file") or "notification_rules.json")

    def _notification_runtime_path(self):
        return self.base_dir / NOTIFICATION_RUNTIME_FILE

    def _load_biometric_sync_state(self):
        path = self._biometric_sync_path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_biometric_sync_state(self, payload):
        self._biometric_sync_path().write_text(json.dumps(payload), encoding="utf-8")

    def _load_notification_runtime(self):
        path = self._notification_runtime_path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_notification_runtime(self, payload):
        self._notification_runtime_path().write_text(json.dumps(payload), encoding="utf-8")

    def _log_path(self):
        return self.base_dir / (self.config.get("log_file") or "tracker.log")

    def _tail_log_lines(self, limit=None):
        limit = int(limit or self.config.get("device_health_log_lines", 20))
        log_path = self._log_path()
        if not log_path.exists():
            return []
        try:
            return log_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]
        except Exception:
            return []

    def _queue_count(self):
        conn = sqlite3.connect(self._queue_db_path())
        try:
            row = conn.execute("SELECT COUNT(*) FROM outbound_queue").fetchone()
            return int(row[0] if row else 0)
        finally:
            conn.close()

    def _process_count(self):
        return len([proc for proc in psutil.process_iter(["name"]) if (proc.info.get("name") or "").lower() == "cclms-tracker.exe"])

    def _tracker_processes(self):
        processes = []
        for proc in psutil.process_iter(["pid", "name", "create_time"]):
            if (proc.info.get("name") or "").lower() == "cclms-tracker.exe":
                processes.append(proc.info)
        return sorted(processes, key=lambda item: item.get("create_time") or 0)

    def _dns_status(self):
        host = urlparse(self.base).hostname or self.base
        try:
            ip = socket.gethostbyname(host)
            return {"host": host, "ok": True, "ip": ip}
        except Exception as exc:
            return {"host": host, "ok": False, "error": str(exc)}

    def _collect_diagnostics(self):
        return {
            "device_id": self.device_id,
            "machine_name": self.machine_name,
            "windows_username": self.windows_username,
            "version": self.current_version,
            "queue_count": self._queue_count(),
            "process_count": self._process_count(),
            "processes": self._tracker_processes(),
            "dns_status": self._dns_status(),
            "last_log_lines": self._tail_log_lines(),
            "time_utc": _server_datetime(datetime.now(timezone.utc)),
        }

    def _report_device_health(self, now):
        if not self.device_health_enabled:
            return
        interval_seconds = int(self.config.get("device_health_poll_seconds", 300))
        if now - self.last_device_health_poll < timedelta(seconds=interval_seconds):
            return
        self.last_device_health_poll = now

        method = self.config.get("device_health_method")
        if not method:
            return

        payload = self._collect_diagnostics()
        payload["system_info"] = self._system_info()
        try:
            self._send_or_queue(method, payload)
        except Exception:
            logging.exception("Device health report failed")

    def _flush_dns(self):
        subprocess.run(
            ["ipconfig", "/flushdns"],
            check=True,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "DNS cache flushed"

    def _clear_offline_queue(self):
        conn = sqlite3.connect(self._queue_db_path())
        try:
            conn.execute("DELETE FROM outbound_queue")
            conn.commit()
        finally:
            conn.close()
        return "Offline queue cleared"

    def _reset_notification_cache(self):
        for path in [self._notification_rules_path(), self._notification_runtime_path()]:
            if path.exists():
                path.unlink()
        self.notification_rules = []
        return "Notification cache reset"

    def _repair_tracker_runtime(self):
        for path in [
            self._update_check_path(),
            self._notification_runtime_path(),
            self._biometric_sync_path(),
        ]:
            if path.exists():
                path.unlink()
        self._init_queue()
        self.binding = {}
        self.policy = {}
        self.active_call = None
        self.next_snapshot_at = self._next_snapshot_time()
        return "Tracker runtime reset completed"

    def _close_duplicate_tracker_processes(self):
        processes = self._tracker_processes()
        if len(processes) <= 1:
            return "No duplicate tracker process found"
        keep_pid = os.getpid()
        closed = []
        for proc in processes:
            pid = proc.get("pid")
            if pid and pid != keep_pid:
                try:
                    psutil.Process(pid).kill()
                    closed.append(pid)
                except Exception:
                    logging.exception("Failed to stop duplicate tracker pid=%s", pid)
        return f"Stopped duplicate tracker processes: {closed}" if closed else "No duplicate tracker process stopped"

    def _clear_app_temp_files(self):
        removed = []
        temp_root = Path(tempfile.gettempdir())
        patterns = ["cclms-tracker-update-*", "snapshot_*.jpg"]
        for pattern in patterns:
            for item in temp_root.glob(pattern):
                try:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
                    removed.append(str(item))
                except Exception:
                    logging.exception("Failed to remove temp item %s", item)
        return f"Removed {len(removed)} app temp items"

    def _extract_call_metadata(self, window_title, process_name):
        metadata = {
            "active_app": process_name,
            "window_title": window_title,
            "source_system": "windows-inferred-call",
        }
        if not self.call_metadata_enabled:
            return metadata

        text = window_title or ""
        metadata["direction"] = "unknown"
        lower = text.lower()
        if any(token in lower for token in ["incoming", "inbound", "caller"]):
            metadata["direction"] = "incoming"
        elif any(token in lower for token in ["outgoing", "outbound", "dialing", "calling"]):
            metadata["direction"] = "outgoing"

        for rule in self.config.get("call_detail_patterns", []) or []:
            name = rule.get("name")
            pattern = rule.get("pattern")
            if not name or not pattern:
                continue
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                metadata[name] = value
                if name == "phone_number":
                    metadata.setdefault("caller_phone", value)
                    metadata.setdefault("callee_phone", value)

        if " - " in text:
            metadata.setdefault("caller_id", text.split(" - ", 1)[0].strip())
        return metadata

    def _extract_action(self, action):
        payload = dict(action or {})
        payload_body = payload.get("payload")
        if isinstance(payload_body, str):
            try:
                payload_body = json.loads(payload_body)
            except Exception:
                payload_body = {"raw": payload_body}
        if not isinstance(payload_body, dict):
            payload_body = {}
        payload["payload"] = payload_body
        return payload

    def _rule_matches(self, rule, active_app="", window_title="", website_url=""):
        process_rule = (rule.get("process_name") or rule.get("active_app") or "").strip().lower()
        if process_rule and process_rule != (active_app or "").strip().lower():
            return False

        title_rule = (rule.get("window_title_contains") or "").strip().lower()
        if title_rule and title_rule not in (window_title or "").strip().lower():
            return False

        domain_rule = _normalize_domain(rule.get("domain") or "")
        if domain_rule:
            current_domain = _normalize_domain(urlparse(website_url or "").netloc)
            if not current_domain:
                return False
            if current_domain != domain_rule and not current_domain.endswith("." + domain_rule):
                return False

        return True

    def _productivity_for_event(self, payload):
        if not self.productivity_rules:
            return None

        active_app = (payload.get("active_app") or "").strip().lower()
        window_title = payload.get("window_title") or ""
        website_url = payload.get("website_url") or ""

        for rule in self.productivity_rules:
            if self._rule_matches(rule, active_app=active_app, window_title=window_title, website_url=website_url):
                return {
                    "productivity_rating": rule.get("rating") or rule.get("productivity_rating") or "",
                    "productivity_score": rule.get("score", 0),
                    "productivity_rule_name": rule.get("name") or rule.get("rule_name") or "",
                }

        return None

    def _apply_productivity(self, payload):
        productivity = self._productivity_for_event(payload)
        if productivity:
            payload.update({key: value for key, value in productivity.items() if value not in ("", None)})
        return payload

    def _ack_device_action(self, action_id, status, message=""):
        method = self.config.get("device_action_ack_method")
        if not method:
            return
        self._post(
            method,
            {
                "action_id": action_id,
                "device_id": self.device_id,
                "status": status,
                "message": message,
            },
        )

    def _change_local_password(self, payload):
        username = payload.get("target_username") or payload.get("username") or self.windows_username
        new_password = payload.get("new_password") or payload.get("password")
        if not new_password:
            raise RuntimeError("Device action change_local_password requires new_password")

        subprocess.run(
            ["net", "user", username, new_password],
            check=True,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        if payload.get("force_logoff_after_change"):
            subprocess.Popen(
                ["shutdown", "/l"],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

        return f"Local password changed for {username}"

    def _sync_biometric_attendance(self):
        if not self.biometric_sync_enabled or not self.biometric_device.get("enabled"):
            return "Biometric sync disabled"

        try:
            from zk import ZK
        except ImportError as exc:
            raise RuntimeError("Biometric sync requires the pyzk package") from exc

        host = self.biometric_device.get("ip")
        port = int(self.biometric_device.get("port") or 4370)
        password = int(self.biometric_device.get("password") or self.biometric_device.get("comm_key") or 0)
        method = self.config.get("biometric_sync_method")

        if not host or not method:
            raise RuntimeError("Biometric sync requires CRM-provided ip and ingest method")

        state = self._load_biometric_sync_state()
        last_sync_value = state.get("last_sync_at")
        last_sync_at = datetime.fromisoformat(last_sync_value) if last_sync_value else None

        zk_client = ZK(host, port=port, timeout=10, password=password, ommit_ping=False)
        conn = zk_client.connect()
        try:
            records = []
            max_seen = last_sync_at
            for attendance in conn.get_attendance():
                punch_time = attendance.timestamp
                if last_sync_at and punch_time <= last_sync_at:
                    continue
                records.append(
                    {
                        "uid": getattr(attendance, "uid", None),
                        "user_id": getattr(attendance, "user_id", None),
                        "timestamp": _server_datetime(punch_time.replace(tzinfo=timezone.utc) if punch_time.tzinfo is None else punch_time),
                        "status": getattr(attendance, "status", None),
                        "punch": getattr(attendance, "punch", None),
                        "device_ip": host,
                    }
                )
                if max_seen is None or punch_time > max_seen:
                    max_seen = punch_time
        finally:
            conn.disconnect()

        if records:
            self._post(
                method,
                {
                    "device_id": self.device_id,
                    "biometric_device": self.biometric_device,
                    "records": records,
                },
            )

        if max_seen:
            state["last_sync_at"] = max_seen.isoformat()
            self._save_biometric_sync_state(state)

        return f"Synced {len(records)} biometric attendance rows"

    def _execute_device_action(self, action):
        action = self._extract_action(action)
        action_id = action.get("action_id") or action.get("name") or action.get("id")
        action_type = action.get("action_type") or action.get("type")
        payload = action.get("payload") or {}

        if not action_id or not action_type:
            raise RuntimeError("Invalid device action payload")

        action_type = action_type.strip().lower()

        if action_type == "refresh_policy":
            self.bootstrap()
            return "Policy refreshed"
        if action_type == "restart_tracker":
            return "Tracker restart requested"
        if action_type == "lock_workstation":
            ctypes.windll.user32.LockWorkStation()
            return "Workstation locked"
        if action_type == "logoff_user":
            subprocess.Popen(["shutdown", "/l"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return "User logoff requested"
        if action_type == "restart_computer":
            subprocess.Popen(["shutdown", "/r", "/t", "5", "/f"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return "Computer restart requested"
        if action_type == "shutdown_computer":
            subprocess.Popen(["shutdown", "/s", "/t", "5", "/f"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return "Computer shutdown requested"
        if action_type == "change_local_password":
            return self._change_local_password(payload)
        if action_type == "collect_diagnostics":
            diagnostics = self._collect_diagnostics()
            return json.dumps(diagnostics)
        if action_type == "close_duplicate_tracker_processes":
            return self._close_duplicate_tracker_processes()
        if action_type == "flush_dns":
            return self._flush_dns()
        if action_type == "clear_offline_queue":
            return self._clear_offline_queue()
        if action_type == "clear_app_temp_files":
            return self._clear_app_temp_files()
        if action_type == "reset_notification_cache":
            return self._reset_notification_cache()
        if action_type == "repair_tracker_runtime":
            return self._repair_tracker_runtime()
        if action_type == "sync_biometric_attendance":
            return self._sync_biometric_attendance()

        raise RuntimeError(f"Unsupported device action type: {action_type}")

    def _poll_device_actions(self, now):
        if not self.device_actions_enabled:
            return
        interval_seconds = int(self.config.get("device_actions_poll_seconds", 60))
        if now - self.last_device_action_poll < timedelta(seconds=interval_seconds):
            return
        self.last_device_action_poll = now

        method = self.config.get("device_actions_method")
        if not method:
            return

        response = self._call(method, {"device_id": self.device_id, "system_info": self._system_info()})
        actions = response.get("message") or []
        if not isinstance(actions, list):
            return

        for raw_action in actions:
            action = self._extract_action(raw_action)
            action_id = action.get("action_id") or action.get("name") or action.get("id")
            if not action_id:
                continue

            existing = self._action_history_get(action_id)
            if existing and existing[0] == "success":
                continue

            try:
                self._action_history_set(action_id, "running", "")
                result = self._execute_device_action(action)
                self._action_history_set(action_id, "success", result)
                self._ack_device_action(action_id, "success", result)
                if (action.get("action_type") or "").strip().lower() == "restart_tracker":
                    raise TrackerRestartRequested(result)
            except TrackerRestartRequested:
                raise
            except Exception as exc:
                message = str(exc)
                self._action_history_set(action_id, "failed", message)
                try:
                    self._ack_device_action(action_id, "failed", message)
                except Exception:
                    logging.exception("Failed to acknowledge device action %s", action_id)
                logging.exception("Device action failed: %s", action_id)

    def _sync_biometric_if_due(self, now):
        if not self.biometric_sync_enabled or not self.biometric_device.get("enabled"):
            return
        interval_minutes = int(self.config.get("biometric_sync_interval_minutes", 15))
        if now - self.last_biometric_sync < timedelta(minutes=interval_minutes):
            return
        self.last_biometric_sync = now
        try:
            result = self._sync_biometric_attendance()
            logging.info(result)
        except Exception:
            logging.exception("Biometric attendance sync failed")

    def _show_notification(self, notification):
        title = str(notification.get("title") or "Tracker Notification")
        message = str(notification.get("message") or notification.get("body") or "")
        if not message:
            return

        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            f"[System.Windows.Forms.MessageBox]::Show(@'\n{message}\n'@, @'\n{title}\n'@) | Out-Null"
        )
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def _poll_notifications(self, now):
        if not self.notifications_enabled:
            return

        interval_seconds = int(self.config.get("notifications_poll_seconds", 60))
        if now - self.last_notification_poll < timedelta(seconds=interval_seconds):
            return
        self.last_notification_poll = now

        method = self.config.get("notifications_method")
        if not method:
            return

        response = self._call(method, {"device_id": self.device_id, "system_info": self._system_info()})
        notifications = response.get("message") or []
        if not isinstance(notifications, list):
            notifications = []

        self.notification_rules = notifications
        self._notification_rules_path().write_text(json.dumps(notifications, indent=2), encoding="utf-8")

        runtime_state = self._load_notification_runtime()
        active_ids = set()

        for item in notifications:
            if not isinstance(item, dict):
                continue
            if item.get("enabled") is False:
                continue

            notification_id = str(item.get("notification_id") or item.get("name") or item.get("id") or "")
            if not notification_id:
                continue
            active_ids.add(notification_id)

            repeat_seconds = int(item.get("repeat_seconds") or item.get("repeat_interval_seconds") or 300)
            last_shown_raw = runtime_state.get(notification_id, {}).get("last_shown")
            last_shown = datetime.fromisoformat(last_shown_raw) if last_shown_raw else None
            if last_shown and now - last_shown < timedelta(seconds=repeat_seconds):
                continue

            self._show_notification(item)
            runtime_state[notification_id] = {
                "last_shown": now.isoformat(),
                "title": item.get("title") or "",
            }
            logging.info("Displayed notification %s", notification_id)

        for notification_id in list(runtime_state.keys()):
            if notification_id not in active_ids:
                del runtime_state[notification_id]

        self._save_notification_runtime(runtime_state)

    def _update_check_path(self):
        return self.base_dir / UPDATE_CHECK_FILE

    def _should_check_for_updates(self):
        if not getattr(sys, "frozen", False):
            return False
        if not self.config.get("auto_update_enabled", True):
            return False
        if not self.config.get("github_repo"):
            return False

        interval_minutes = int(self.config.get("auto_update_check_minutes", 360))
        check_path = self._update_check_path()
        if not check_path.exists():
            return True

        try:
            payload = json.loads(check_path.read_text(encoding="utf-8"))
            last_checked = datetime.fromisoformat(payload["last_checked"])
        except Exception:
            return True

        return datetime.now(timezone.utc) - last_checked >= timedelta(minutes=interval_minutes)

    def _mark_update_check(self):
        payload = {"last_checked": datetime.now(timezone.utc).isoformat()}
        self._update_check_path().write_text(json.dumps(payload), encoding="utf-8")

    def _latest_release(self):
        repo = self.config.get("github_repo", "").strip().strip("/")
        asset_name = self.config.get("github_release_asset", "cclms-tracker-windows-x64.zip")
        if not repo:
            return None

        url = f"https://api.github.com/repos/{repo}/releases/latest"
        headers = {"Accept": "application/vnd.github+json"}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        payload = response.json()
        tag_name = payload.get("tag_name", "")

        for asset in payload.get("assets", []):
            if asset.get("name") == asset_name:
                return {
                    "version": tag_name,
                    "asset_url": asset.get("browser_download_url"),
                    "asset_name": asset_name,
                }

        raise RuntimeError(f"Latest GitHub release does not contain asset '{asset_name}'")

    def _updater_script_contents(self):
        return r"""
param(
    [Parameter(Mandatory = $true)][string]$DownloadUrl,
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [Parameter(Mandatory = $true)][string]$TaskName,
    [Parameter(Mandatory = $true)][int]$ParentPid
)

$ErrorActionPreference = "Stop"

$tempRoot = Join-Path $env:TEMP ("cclms-tracker-update-" + [guid]::NewGuid().ToString("N"))
$zipPath = Join-Path $tempRoot "release.zip"
$extractPath = Join-Path $tempRoot "release"

New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

try {
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force

    try {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    } catch {
    }

    try {
        Wait-Process -Id $ParentPid -Timeout 60 -ErrorAction SilentlyContinue
    } catch {
    }

    $sourceRoot = Get-ChildItem -Path $extractPath | Select-Object -First 1
    if ($sourceRoot -and $sourceRoot.PSIsContainer) {
        $sourcePath = $sourceRoot.FullName
    } else {
        $sourcePath = $extractPath
    }

    Copy-Item -Path (Join-Path $sourcePath "*") -Destination $InstallRoot -Recurse -Force

    Start-ScheduledTask -TaskName $TaskName
} finally {
    Start-Sleep -Seconds 2
    Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
"""

    def _trigger_update(self, release_info):
        script_path = Path(tempfile.gettempdir()) / "cclms-tracker-updater.ps1"
        script_path.write_text(self._updater_script_contents(), encoding="utf-8")

        install_root = self.base_dir.parent if self.base_dir.name.lower() == "dist" else self.base_dir
        task_name = self.config.get("service_name") or "CCLMS-Tracker"

        subprocess.Popen(
            [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-DownloadUrl",
                release_info["asset_url"],
                "-InstallRoot",
                str(install_root),
                "-TaskName",
                task_name,
                "-ParentPid",
                str(os.getpid()),
            ],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def _check_for_updates(self):
        if not self._should_check_for_updates():
            return

        try:
            release_info = self._latest_release()
            self._mark_update_check()
            if not release_info:
                return

            latest_version = _parse_version(release_info["version"])
            current_version = _parse_version(self.current_version)
            if latest_version <= current_version:
                return

            logging.info(
                "Starting update from version %s to %s using %s",
                self.current_version,
                release_info["version"],
                release_info["asset_name"],
            )
            self._trigger_update(release_info)
            raise SystemExit(0)
        except Exception:
            logging.exception("Auto-update check failed")

    def _system_info(self):
        return {
            "device_id": self.device_id,
            "machine_name": self.machine_name,
            "windows_username": self.windows_username,
            "ip_address": self._ip_address(),
            "platform": sys.platform,
            "platform_release": platform.release(),
            "platform_version": platform.version(),
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": psutil.virtual_memory().percent,
        }

    def _restart_delay(self):
        return int(self.config.get("runtime_restart_delay_seconds", 30))

    def _is_fatal_error(self, exc):
        if isinstance(exc, requests.RequestException):
            return False
        if isinstance(exc, RuntimeError):
            message = str(exc)
            fatal_markers = [
                "did not return a binding from CRM",
                "HTTP 401",
                "HTTP 403",
            ]
            return any(marker in message for marker in fatal_markers)
        return False

    def _safe_logout(self):
        try:
            self.send_logout()
        except Exception:
            logging.exception("Failed to send logout event")

    def _bootstrap_until_ready(self):
        while True:
            try:
                self.bootstrap()
                self._flush_queue()
                self.send_login()
                return
            except Exception as exc:
                if self._is_fatal_error(exc):
                    raise
                logging.exception("Bootstrap failed; retrying in %s seconds", self._restart_delay())
                time.sleep(self._restart_delay())

    def _ip_address(self):
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return ""

    def _foreground_window(self):
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process_name = ""
        try:
            process_name = psutil.Process(pid).name()
        except Exception:
            pass
        return process_name, title

    def _browser_history_paths(self):
        base = Path(os.environ.get("LOCALAPPDATA", ""))
        return [
            base / "Google" / "Chrome" / "User Data" / "Default" / "History",
            base / "Microsoft" / "Edge" / "User Data" / "Default" / "History",
        ]

    def _recent_browser_rows(self):
        rows = []
        for history_path in self._browser_history_paths():
            if not history_path.exists():
                continue
            tmp_path = history_path.with_suffix(".tmp")
            try:
                shutil.copy2(history_path, tmp_path)
                conn = sqlite3.connect(tmp_path)
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT url, title, last_visit_time
                    FROM urls
                    WHERE last_visit_time > ?
                    ORDER BY last_visit_time ASC
                    """,
                    [int((self.last_history_scan.timestamp() + EPOCH_OFFSET) * 1000000)],
                )
                rows.extend(cur.fetchall())
                conn.close()
            except Exception:
                pass
            finally:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
        return rows

    def _take_snapshot(self):
        shot = ImageGrab.grab()
        path = Path.cwd() / f"snapshot_{int(time.time())}.jpg"
        shot.save(path, "JPEG", quality=60)
        encoded = path.read_bytes()
        try:
            path.unlink()
        except Exception:
            pass
        import base64

        return "data:image/jpeg;base64," + base64.b64encode(encoded).decode("utf-8")

    def _send_activity(self, payload):
        payload.setdefault("system_info", self._system_info())
        self._apply_productivity(payload)
        return self._send_or_queue("cclms.api.desktop_tracker.ingest_activity", payload)

    def _send_call(self, payload):
        payload.setdefault("system_info", self._system_info())
        return self._send_or_queue("cclms.api.desktop_tracker.ingest_call", payload)

    def bootstrap(self):
        logging.info("Bootstrapping tracker for device_id=%s machine=%s", self.device_id, self.machine_name)
        response = self._call(
            "cclms.api.desktop_tracker.get_tracking_policy",
            {"system_info": self._system_info(), "device_id": self.device_id},
        )
        message = response.get("message") or {}
        self.policy = message
        self.binding = message.get("binding") or {}
        if not self.binding:
            raise RuntimeError(
                f"Tracker device '{self.device_id}' did not return a binding from CRM. "
                "Check Tracker Device enrollment, allowed_service_user, and API credentials."
            )

        if message.get("productivity_rules") is not None:
            self.productivity_rules = list(message.get("productivity_rules") or [])
        self.device_actions_enabled = bool(message.get("device_actions_enabled", self.config.get("device_actions_enabled", False)))
        if message.get("device_actions_poll_seconds"):
            self.config["device_actions_poll_seconds"] = int(message["device_actions_poll_seconds"])
        if message.get("device_health_enabled") is not None:
            self.device_health_enabled = bool(message.get("device_health_enabled"))
        if message.get("device_health_poll_seconds"):
            self.config["device_health_poll_seconds"] = int(message["device_health_poll_seconds"])
        if message.get("notifications_enabled") is not None:
            self.notifications_enabled = bool(message.get("notifications_enabled"))
        if message.get("notifications_poll_seconds"):
            self.config["notifications_poll_seconds"] = int(message["notifications_poll_seconds"])
        if message.get("biometric_sync_enabled") is not None:
            self.biometric_sync_enabled = bool(message.get("biometric_sync_enabled"))
        if message.get("biometric_sync_interval_minutes"):
            self.config["biometric_sync_interval_minutes"] = int(message["biometric_sync_interval_minutes"])
        if message.get("biometric_device") is not None:
            self.biometric_device = dict(message.get("biometric_device") or {})
        self.map_assistant.update_policy(message)

        self.config["heartbeat_seconds"] = int(message.get("heartbeat_seconds") or self.config.get("heartbeat_seconds", 60))
        self.config["snapshot_min_minutes"] = int(message.get("snapshot_min_minutes") or self.config.get("snapshot_min_minutes", 45))
        self.config["snapshot_max_minutes"] = int(message.get("snapshot_max_minutes") or self.config.get("snapshot_max_minutes", 75))
        if message.get("call_process_hints"):
            self.config["call_process_hints"] = message["call_process_hints"]

        return message

    def send_login(self):
        self._send_activity(
            {
                "event_type": "Login",
                "event_time": _server_datetime(datetime.now(timezone.utc)),
                "activity_type": "CRM Entry",
                "summary": "Windows tracker started",
            }
        )

    def send_logout(self):
        self._send_or_queue(
            "cclms.api.desktop_tracker.ingest_logout",
            {
                "event_time": _server_datetime(datetime.now(timezone.utc)),
                "system_info": self._system_info(),
            },
        )

    def _handle_inferred_call(self, process_name, window_title):
        now = datetime.now(timezone.utc)
        hints = [value.lower() for value in self.config.get("call_process_hints", [])]
        is_call_app = process_name.lower() in hints

        if is_call_app and not self.active_call:
            self.active_call = {
                "call_id": f"{self.device_id}-{int(time.time())}",
                "start_time": _server_datetime(now),
                "status": "Started",
            }
            self.active_call.update(self._extract_call_metadata(window_title, process_name))
            return

        if self.active_call and not is_call_app:
            payload = dict(self.active_call)
            payload["end_time"] = _server_datetime(now)
            payload["status"] = "Completed"
            payload["source_system"] = "windows-inferred-call"
            try:
                start_dt = datetime.strptime(payload["start_time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                payload["duration_seconds"] = int((now - start_dt).total_seconds())
            except Exception:
                pass
            self._send_call(payload)
            self.active_call = None

    def loop(self):
        self._check_for_updates()
        while True:
            try:
                self._bootstrap_until_ready()
                heartbeat_seconds = int(self.config.get("heartbeat_seconds", 60))
                while True:
                    now = datetime.now(timezone.utc)
                    process_name, window_title = self._foreground_window()

                    self._flush_queue()
                    self._poll_device_actions(now)
                    self._report_device_health(now)
                    self._poll_notifications(now)
                    self._sync_biometric_if_due(now)

                    recent_browser_rows = self._recent_browser_rows()
                    self.map_assistant.process_cycle(now, process_name, window_title, recent_browser_rows)

                    self._send_activity(
                        {
                            "event_type": "Heartbeat",
                            "event_time": _server_datetime(now),
                            "event_source": "windows-agent",
                            "active_app": process_name,
                            "window_title": window_title,
                            "activity_type": "CRM Entry",
                            "summary": f"Foreground app: {process_name}",
                            "event_minutes": round(heartbeat_seconds / 60.0, 2),
                        }
                    )

                    self._handle_inferred_call(process_name, window_title)

                    for url, title, last_visit_time in recent_browser_rows:
                        visited_at = chrome_time_to_datetime(last_visit_time) or now
                        self._send_activity(
                            {
                                "event_type": "Website Visit",
                                "event_time": _server_datetime(visited_at),
                                "event_source": "browser-history",
                                "active_app": "browser",
                                "window_title": title,
                                "website_url": url,
                                "summary": f"Visited {urlparse(url).netloc}",
                                "event_minutes": 0,
                            }
                        )
                    self.last_history_scan = now

                    if now >= self.next_snapshot_at:
                        self._send_activity(
                            {
                                "event_type": "Screen Snap",
                                "event_time": _server_datetime(now),
                                "event_source": "windows-agent",
                                "active_app": process_name,
                                "window_title": window_title,
                                "summary": "Random hourly snapshot",
                                "screenshot_base64": self._take_snapshot(),
                            }
                        )
                        self.next_snapshot_at = self._next_snapshot_time()

                    time.sleep(heartbeat_seconds)
            except KeyboardInterrupt:
                self._safe_logout()
                raise
            except TrackerRestartRequested:
                logging.info("Tracker restart requested by CRM action")
                self._safe_logout()
                self.binding = {}
                self.policy = {}
                self.active_call = None
                self.next_snapshot_at = self._next_snapshot_time()
                time.sleep(2)
            except Exception as exc:
                if self._is_fatal_error(exc):
                    logging.exception("Fatal tracker error; stopping process")
                    self._safe_logout()
                    raise
                logging.exception("Transient tracker error; restarting loop in %s seconds", self._restart_delay())
                self._safe_logout()
                self.binding = {}
                self.policy = {}
                self.active_call = None
                self.next_snapshot_at = self._next_snapshot_time()
                time.sleep(self._restart_delay())


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    TrackerAgent(config_path).loop()


if __name__ == "__main__":
    main()
