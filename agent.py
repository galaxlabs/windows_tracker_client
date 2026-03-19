import json
import logging
import os
import random
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
from version import __version__


EPOCH_OFFSET = 11644473600
UPDATE_CHECK_FILE = ".update-check.json"
QUEUE_DB_FILE = "tracker_queue.sqlite3"


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


def chrome_time_to_datetime(value):
    if not value:
        return None
    return datetime.fromtimestamp((int(value) / 1000000) - EPOCH_OFFSET, tz=timezone.utc)


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
                "window_title": window_title,
                "active_app": process_name,
                "status": "Started",
            }
            return

        if self.active_call and not is_call_app:
            payload = dict(self.active_call)
            payload["end_time"] = _server_datetime(now)
            payload["status"] = "Completed"
            payload["source_system"] = "windows-inferred-call"
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

                    for url, title, last_visit_time in self._recent_browser_rows():
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
