import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


def _server_datetime(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _normalize_domain(value):
    host = (value or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _normalize_text(value):
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _extract_zip(*values):
    for value in values:
        if not value:
            continue
        match = re.search(r"\b(\d{5})(?:-\d{4})?\b", str(value))
        if match:
            return match.group(1)
    return ""


class MapIntelligenceAssistant:
    def __init__(self, base_dir, config, device_id, call_method, post_method, notify_callback, logger=None):
        self.base_dir = Path(base_dir)
        self.config = config
        self.device_id = device_id
        self.call_method = call_method
        self.post_method = post_method
        self.notify_callback = notify_callback
        self.logger = logger or logging.getLogger(__name__)
        self.enabled = bool(config.get("map_intelligence_enabled", False))
        self.productivity_rules = []
        self._init_db()

    def _db_path(self):
        return self.base_dir / (self.config.get("map_cache_db") or "scouting_cache.sqlite3")

    def _connect(self):
        return sqlite3.connect(self._db_path())

    def _init_db(self):
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS zip_cache (
                    zip_code TEXT PRIMARY KEY,
                    city TEXT,
                    state TEXT,
                    zone_color TEXT,
                    zip_score REAL,
                    competitor_count INTEGER,
                    our_lead_count INTEGER,
                    validation_status TEXT,
                    last_synced_at TEXT,
                    raw_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS competitor_cache (
                    external_id TEXT,
                    name TEXT,
                    address TEXT,
                    zip_code TEXT,
                    state TEXT,
                    latitude REAL,
                    longitude REAL,
                    source_url TEXT,
                    source_type TEXT,
                    last_seen_at TEXT,
                    synced_to_crm INTEGER,
                    crm_competitor_kiosk_name TEXT,
                    fingerprint TEXT UNIQUE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lead_cache (
                    atm_lead_name TEXT,
                    business_name TEXT,
                    address TEXT,
                    zip_code TEXT,
                    state TEXT,
                    latitude REAL,
                    longitude REAL,
                    workflow_state TEXT,
                    modified TEXT,
                    fingerprint TEXT UNIQUE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS location_fingerprint_cache (
                    fingerprint TEXT PRIMARY KEY,
                    source_type TEXT,
                    source_name TEXT,
                    zip_code TEXT,
                    latitude REAL,
                    longitude REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_cooldown (
                    fingerprint TEXT PRIMARY KEY,
                    alert_type TEXT,
                    last_alerted_at TEXT
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def update_policy(self, policy):
        self.enabled = bool(policy.get("map_intelligence_enabled", self.config.get("map_intelligence_enabled", False)))
        if policy.get("productivity_rules") is not None:
            self.productivity_rules = list(policy.get("productivity_rules") or [])
        self.config.update(
            {
                key: value
                for key, value in policy.items()
                if key
                in {
                    "map_intelligence_enabled",
                    "map_cache_db",
                    "map_sync_scope_seconds",
                    "map_context_debounce_seconds",
                    "atm_radar_domains",
                    "crm_scouting_domains",
                    "maps_domains",
                    "scoped_zip_sync_method",
                    "scoped_lead_sync_method",
                    "scoped_competitor_sync_method",
                    "location_validate_method",
                    "competitor_upsert_method",
                    "competitor_keywords",
                    "duplicate_alert_cooldown_seconds",
                    "map_popup_enabled",
                }
            }
        )

    def _state_get(self, key, default=""):
        conn = self._connect()
        try:
            row = conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
            return row[0] if row else default
        finally:
            conn.close()

    def _state_set(self, key, value):
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO sync_state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, str(value)),
            )
            conn.commit()
        finally:
            conn.close()

    def _cooldown_active(self, fingerprint, alert_type, now):
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT last_alerted_at FROM alert_cooldown WHERE fingerprint = ? AND alert_type = ?",
                (fingerprint, alert_type),
            ).fetchone()
            if not row:
                return False
            last_alerted_at = datetime.fromisoformat(row[0])
            seconds = int(self.config.get("duplicate_alert_cooldown_seconds", 600))
            return now - last_alerted_at < timedelta(seconds=seconds)
        finally:
            conn.close()

    def _mark_cooldown(self, fingerprint, alert_type, now):
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO alert_cooldown (fingerprint, alert_type, last_alerted_at) VALUES (?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET alert_type = excluded.alert_type, last_alerted_at = excluded.last_alerted_at
                """,
                (fingerprint, alert_type, now.isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def _is_relevant_url(self, url):
        domain = _normalize_domain(urlparse(url or "").netloc)
        domain_groups = (
            self.config.get("atm_radar_domains") or [],
            self.config.get("crm_scouting_domains") or [],
            self.config.get("maps_domains") or [],
        )
        for group in domain_groups:
            for item in group:
                item = _normalize_domain(item)
                if domain == item or domain.endswith("." + item):
                    return True
        return False

    def _source_type(self, url):
        domain = _normalize_domain(urlparse(url or "").netloc)
        for item in self.config.get("atm_radar_domains") or []:
            item = _normalize_domain(item)
            if domain == item or domain.endswith("." + item):
                return "atm_radar"
        for item in self.config.get("crm_scouting_domains") or []:
            item = _normalize_domain(item)
            if domain == item or domain.endswith("." + item):
                return "crm_scouting"
        for item in self.config.get("maps_domains") or []:
            item = _normalize_domain(item)
            if domain == item or domain.endswith("." + item):
                return "google_maps"
        return ""

    def _extract_coordinates(self, url):
        text = url or ""
        match = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", text)
        if match:
            return float(match.group(1)), float(match.group(2))
        match = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", text)
        if match:
            return float(match.group(1)), float(match.group(2))
        parsed = urlparse(text)
        query = parse_qs(parsed.query)
        if query.get("q"):
            geo = query["q"][0]
            match = re.match(r"(-?\d+\.\d+),(-?\d+\.\d+)", geo)
            if match:
                return float(match.group(1)), float(match.group(2))
        return None, None

    def _extract_place_name(self, window_title, url):
        title = (window_title or "").strip()
        if title:
            for suffix in [" - Google Maps", " - ATM Radar", " - Google Chrome", " - Microsoft​ Edge"]:
                if title.endswith(suffix):
                    title = title[: -len(suffix)]
            if title:
                return title.strip()

        match = re.search(r"/place/([^/]+)", url or "")
        if match:
            return unquote(match.group(1)).replace("+", " ")
        return ""

    def _context_from_browser(self, active_app, window_title, browser_rows):
        relevant_rows = [(url, title, when) for url, title, when in browser_rows if self._is_relevant_url(url)]
        if not relevant_rows and not any(
            token in (window_title or "").lower() for token in ["google maps", "atm radar", "scouting", "map"]
        ):
            return None

        url = ""
        page_title = window_title or ""
        if relevant_rows:
            url, title, _ = relevant_rows[-1]
            page_title = title or page_title

        latitude, longitude = self._extract_coordinates(url)
        zip_code = _extract_zip(page_title, url, window_title)
        state = ""
        place_name = self._extract_place_name(page_title, url)

        return {
            "source_type": self._source_type(url),
            "url": url,
            "window_title": window_title or "",
            "page_title": page_title,
            "active_app": active_app or "",
            "place_name": place_name,
            "address": page_title,
            "zip_code": zip_code,
            "state": state,
            "latitude": latitude,
            "longitude": longitude,
        }

    def _fingerprint(self, source_name="", address="", zip_code="", latitude=None, longitude=None):
        base = "|".join(
            [
                _normalize_text(source_name),
                _normalize_text(address),
                _normalize_text(zip_code),
                "" if latitude is None else f"{latitude:.5f}",
                "" if longitude is None else f"{longitude:.5f}",
            ]
        )
        return hashlib.sha1(base.encode("utf-8")).hexdigest()

    def _sync_dataset(self, method, payload):
        if not method:
            return None
        try:
            return self.call_method(method, payload)
        except Exception:
            self.logger.exception("Scoped sync failed for %s", method)
            return None

    def _upsert_zip_cache(self, rows):
        conn = self._connect()
        try:
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO zip_cache (zip_code, city, state, zone_color, zip_score, competitor_count, our_lead_count, validation_status, last_synced_at, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(zip_code) DO UPDATE SET
                        city = excluded.city,
                        state = excluded.state,
                        zone_color = excluded.zone_color,
                        zip_score = excluded.zip_score,
                        competitor_count = excluded.competitor_count,
                        our_lead_count = excluded.our_lead_count,
                        validation_status = excluded.validation_status,
                        last_synced_at = excluded.last_synced_at,
                        raw_json = excluded.raw_json
                    """,
                    (
                        row.get("zip_code"),
                        row.get("city"),
                        row.get("state"),
                        row.get("zone_color"),
                        row.get("zip_score"),
                        row.get("competitor_count"),
                        row.get("our_lead_count"),
                        row.get("validation_status"),
                        _server_datetime(datetime.now(timezone.utc)),
                        json.dumps(row),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def _upsert_lead_cache(self, rows):
        conn = self._connect()
        try:
            for row in rows:
                fingerprint = self._fingerprint(
                    row.get("business_name") or row.get("atm_lead_name"),
                    row.get("address"),
                    row.get("zip_code"),
                    row.get("latitude"),
                    row.get("longitude"),
                )
                conn.execute(
                    """
                    INSERT INTO lead_cache (atm_lead_name, business_name, address, zip_code, state, latitude, longitude, workflow_state, modified, fingerprint)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(fingerprint) DO UPDATE SET
                        atm_lead_name = excluded.atm_lead_name,
                        business_name = excluded.business_name,
                        address = excluded.address,
                        zip_code = excluded.zip_code,
                        state = excluded.state,
                        latitude = excluded.latitude,
                        longitude = excluded.longitude,
                        workflow_state = excluded.workflow_state,
                        modified = excluded.modified
                    """,
                    (
                        row.get("atm_lead_name"),
                        row.get("business_name"),
                        row.get("address"),
                        row.get("zip_code"),
                        row.get("state"),
                        row.get("latitude"),
                        row.get("longitude"),
                        row.get("workflow_state"),
                        row.get("modified"),
                        fingerprint,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def _upsert_competitor_cache(self, rows):
        conn = self._connect()
        try:
            for row in rows:
                fingerprint = self._fingerprint(
                    row.get("name"),
                    row.get("address"),
                    row.get("zip_code"),
                    row.get("latitude"),
                    row.get("longitude"),
                )
                conn.execute(
                    """
                    INSERT INTO competitor_cache (external_id, name, address, zip_code, state, latitude, longitude, source_url, source_type, last_seen_at, synced_to_crm, crm_competitor_kiosk_name, fingerprint)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(fingerprint) DO UPDATE SET
                        external_id = excluded.external_id,
                        name = excluded.name,
                        address = excluded.address,
                        zip_code = excluded.zip_code,
                        state = excluded.state,
                        latitude = excluded.latitude,
                        longitude = excluded.longitude,
                        source_url = excluded.source_url,
                        source_type = excluded.source_type,
                        last_seen_at = excluded.last_seen_at,
                        synced_to_crm = excluded.synced_to_crm,
                        crm_competitor_kiosk_name = excluded.crm_competitor_kiosk_name
                    """,
                    (
                        row.get("external_id") or row.get("place_id"),
                        row.get("name"),
                        row.get("address"),
                        row.get("zip_code"),
                        row.get("state"),
                        row.get("latitude"),
                        row.get("longitude"),
                        row.get("source_url"),
                        row.get("source_type"),
                        _server_datetime(datetime.now(timezone.utc)),
                        1 if row.get("synced_to_crm") else 0,
                        row.get("crm_competitor_kiosk_name"),
                        fingerprint,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def _sync_scoped_data(self, context, now):
        if not self.enabled or not context:
            return
        scope_key = "|".join(
            [
                context.get("source_type") or "",
                context.get("zip_code") or "",
                "" if context.get("latitude") is None else f"{context['latitude']:.3f}",
                "" if context.get("longitude") is None else f"{context['longitude']:.3f}",
            ]
        )
        if not scope_key.strip("|"):
            return

        last_sync_raw = self._state_get(f"scope:{scope_key}")
        if last_sync_raw:
            last_sync = datetime.fromisoformat(last_sync_raw)
            if now - last_sync < timedelta(seconds=int(self.config.get("map_sync_scope_seconds", 180))):
                return

        payload = {
            "device_id": self.device_id,
            "zip_code": context.get("zip_code"),
            "state": context.get("state"),
            "latitude": context.get("latitude"),
            "longitude": context.get("longitude"),
            "source_type": context.get("source_type"),
            "url": context.get("url"),
        }

        zip_response = self._sync_dataset(self.config.get("scoped_zip_sync_method"), payload)
        if zip_response:
            message = zip_response.get("message") or {}
            rows = message.get("zips") if isinstance(message, dict) else message
            if isinstance(rows, list):
                self._upsert_zip_cache(rows)

        lead_response = self._sync_dataset(self.config.get("scoped_lead_sync_method"), payload)
        if lead_response:
            message = lead_response.get("message") or {}
            rows = message.get("leads") if isinstance(message, dict) else message
            if isinstance(rows, list):
                self._upsert_lead_cache(rows)

        competitor_response = self._sync_dataset(self.config.get("scoped_competitor_sync_method"), payload)
        if competitor_response:
            message = competitor_response.get("message") or {}
            rows = message.get("competitors") if isinstance(message, dict) else message
            if isinstance(rows, list):
                self._upsert_competitor_cache(rows)

        self._state_set(f"scope:{scope_key}", now.isoformat())

    def _zip_guidance(self, zip_code):
        if not zip_code:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT zone_color, zip_score, competitor_count, our_lead_count, validation_status FROM zip_cache WHERE zip_code = ?",
                (zip_code,),
            ).fetchone()
            if not row:
                return None
            return {
                "zone_color": row[0],
                "zip_score": row[1],
                "competitor_count": row[2],
                "our_lead_count": row[3],
                "validation_status": row[4],
            }
        finally:
            conn.close()

    def _find_duplicate_lead(self, context):
        fingerprint = self._fingerprint(
            context.get("place_name"),
            context.get("address"),
            context.get("zip_code"),
            context.get("latitude"),
            context.get("longitude"),
        )
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT atm_lead_name, business_name, workflow_state FROM lead_cache WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if row:
                return {"atm_lead_name": row[0], "business_name": row[1], "workflow_state": row[2], "fingerprint": fingerprint}

            row = conn.execute(
                """
                SELECT atm_lead_name, business_name, workflow_state, fingerprint
                FROM lead_cache
                WHERE zip_code = ? AND lower(business_name) = ?
                """,
                (context.get("zip_code"), _normalize_text(context.get("place_name"))),
            ).fetchone()
            if row:
                return {"atm_lead_name": row[0], "business_name": row[1], "workflow_state": row[2], "fingerprint": row[3]}
            return None
        finally:
            conn.close()

    def _candidate_is_competitor(self, context):
        keywords = [item.lower() for item in (self.config.get("competitor_keywords") or []) if item]
        if not keywords:
            return False
        text = " ".join(
            [
                context.get("place_name") or "",
                context.get("window_title") or "",
                context.get("url") or "",
            ]
        ).lower()
        return any(keyword in text for keyword in keywords)

    def _upsert_competitor_candidate(self, context, now):
        if not self._candidate_is_competitor(context):
            return
        fingerprint = self._fingerprint(
            context.get("place_name"),
            context.get("address"),
            context.get("zip_code"),
            context.get("latitude"),
            context.get("longitude"),
        )
        conn = self._connect()
        try:
            exists = conn.execute("SELECT 1 FROM competitor_cache WHERE fingerprint = ?", (fingerprint,)).fetchone()
            if exists:
                return
        finally:
            conn.close()

        payload = {
            "device_id": self.device_id,
            "name": context.get("place_name"),
            "address": context.get("address"),
            "zip_code": context.get("zip_code"),
            "state": context.get("state"),
            "latitude": context.get("latitude"),
            "longitude": context.get("longitude"),
            "source_url": context.get("url"),
            "source_type": context.get("source_type"),
            "fingerprint": fingerprint,
        }
        method = self.config.get("competitor_upsert_method")
        if method:
            try:
                response = self.post_method(method, payload)
                message = response.get("message") or {}
                payload["synced_to_crm"] = True
                payload["crm_competitor_kiosk_name"] = message.get("name") if isinstance(message, dict) else None
            except Exception:
                self.logger.exception("Competitor upsert failed")
                payload["synced_to_crm"] = False
                payload["crm_competitor_kiosk_name"] = None
        else:
            payload["synced_to_crm"] = False
            payload["crm_competitor_kiosk_name"] = None

        self._upsert_competitor_cache([payload])
        self._state_set(f"competitor:{fingerprint}", now.isoformat())

    def _maybe_notify(self, context, now):
        if not self.config.get("map_popup_enabled", True):
            return
        fingerprint = self._fingerprint(
            context.get("place_name"),
            context.get("address"),
            context.get("zip_code"),
            context.get("latitude"),
            context.get("longitude"),
        )
        if not fingerprint:
            return

        duplicate = self._find_duplicate_lead(context)
        if duplicate and not self._cooldown_active(fingerprint, "duplicate", now):
            self.notify_callback(
                {
                    "notification_id": f"duplicate-{fingerprint}",
                    "title": "Duplicate ATM Lead",
                    "message": f"This location already exists at workflow state: {duplicate.get('workflow_state') or 'Unknown'}",
                    "repeat_seconds": int(self.config.get("duplicate_alert_cooldown_seconds", 600)),
                }
            )
            self._mark_cooldown(fingerprint, "duplicate", now)

        zip_info = self._zip_guidance(context.get("zip_code"))
        if zip_info and not self._cooldown_active(fingerprint, "zip_guidance", now):
            parts = []
            if zip_info.get("zone_color"):
                parts.append(f"Zone: {zip_info['zone_color']}")
            if zip_info.get("zip_score") is not None:
                parts.append(f"Score: {zip_info['zip_score']}")
            if zip_info.get("validation_status"):
                parts.append(f"Status: {zip_info['validation_status']}")
            if zip_info.get("competitor_count") is not None:
                parts.append(f"Competitors: {zip_info['competitor_count']}")
            if zip_info.get("our_lead_count") is not None:
                parts.append(f"Our Leads: {zip_info['our_lead_count']}")
            if parts:
                self.notify_callback(
                    {
                        "notification_id": f"zip-{fingerprint}",
                        "title": "ZIP Guidance",
                        "message": " | ".join(parts),
                        "repeat_seconds": int(self.config.get("duplicate_alert_cooldown_seconds", 600)),
                    }
                )
                self._mark_cooldown(fingerprint, "zip_guidance", now)

    def process_cycle(self, now, active_app, window_title, browser_rows):
        if not self.enabled:
            return None

        if active_app.lower() not in [item.lower() for item in (self.config.get("browser_relevant_processes") or ["chrome.exe", "msedge.exe"])]:
            return None

        context = self._context_from_browser(active_app, window_title, browser_rows)
        if not context:
            return None

        last_context_raw = self._state_get("current_context_seen")
        if last_context_raw:
            last_context = datetime.fromisoformat(last_context_raw)
            if now - last_context < timedelta(seconds=int(self.config.get("map_context_debounce_seconds", 20))):
                self._sync_scoped_data(context, now)
                return context

        self._sync_scoped_data(context, now)
        self._maybe_notify(context, now)
        self._upsert_competitor_candidate(context, now)
        self._state_set("current_context_seen", now.isoformat())
        self._state_set("current_context", json.dumps(context))
        return context
