# Backend API Contract

This document defines the Frappe/CRM payload contract expected by the Windows tracker client for optional advanced features.

These APIs are optional. If they are missing or disabled in CRM policy, the client continues normal tracking behavior.

## Policy Response

The existing policy method:

- `cclms.api.desktop_tracker.get_tracking_policy`

may optionally include these additional fields:

```json
{
  "message": {
    "heartbeat_seconds": 60,
    "snapshot_min_minutes": 45,
    "snapshot_max_minutes": 75,
    "binding": {...},

    "productivity_rules": [],

    "device_actions_enabled": false,
    "device_actions_poll_seconds": 60,

    "device_health_enabled": false,
    "device_health_poll_seconds": 300,

    "notifications_enabled": false,
    "notifications_poll_seconds": 60,

    "biometric_sync_enabled": false,
    "biometric_sync_interval_minutes": 15,
    "biometric_device": {},

    "call_metadata_enabled": true,
    "call_detail_patterns": [
      {
        "name": "phone_number",
        "pattern": "(\\+?\\d[\\d\\s\\-()]{6,}\\d)"
      }
    ],

    "map_intelligence_enabled": false,
    "map_sync_scope_seconds": 180,
    "map_context_debounce_seconds": 20,
    "competitor_keywords": [],
    "map_popup_enabled": true
  }
}
```

## 1. Scoped ZIP Cache Sync

Method:

- `cclms.api.desktop_tracker.sync_zip_cache_scope`

Request:

```json
{
  "device_id": "DEVICE-ID",
  "zip_code": "12345",
  "state": "TX",
  "latitude": 29.7604,
  "longitude": -95.3698,
  "source_type": "google_maps",
  "url": "https://www.google.com/maps/..."
}
```

Response:

```json
{
  "message": {
    "zips": [
      {
        "zip_code": "12345",
        "city": "Houston",
        "state": "TX",
        "zone_color": "Green",
        "zip_score": 84,
        "competitor_count": 6,
        "our_lead_count": 2,
        "validation_status": "Proceed"
      }
    ]
  }
}
```

Notes:

- keep the result scoped to current ZIP or small nearby set
- do not return national datasets

## 2. Scoped Lead Cache Sync

Method:

- `cclms.api.desktop_tracker.sync_lead_cache_scope`

Request:

```json
{
  "device_id": "DEVICE-ID",
  "zip_code": "12345",
  "state": "TX",
  "latitude": 29.7604,
  "longitude": -95.3698,
  "source_type": "atm_radar",
  "url": "https://..."
}
```

Response:

```json
{
  "message": {
    "leads": [
      {
        "atm_lead_name": "ATM-LEAD-0001",
        "business_name": "ABC Mart",
        "address": "123 Main St, Houston, TX 12345",
        "zip_code": "12345",
        "state": "TX",
        "latitude": 29.7604,
        "longitude": -95.3698,
        "workflow_state": "Approved",
        "modified": "2026-03-19 08:00:00"
      }
    ]
  }
}
```

Notes:

- include only current relevant ZIP/area data
- enough fields must be present for duplicate detection

## 3. Scoped Competitor Cache Sync

Method:

- `cclms.api.desktop_tracker.sync_competitor_cache_scope`

Request:

```json
{
  "device_id": "DEVICE-ID",
  "zip_code": "12345",
  "state": "TX",
  "latitude": 29.7604,
  "longitude": -95.3698,
  "source_type": "google_maps",
  "url": "https://..."
}
```

Response:

```json
{
  "message": {
    "competitors": [
      {
        "external_id": "place-or-external-id",
        "name": "Competitor Kiosk A",
        "address": "999 Market St, Houston, TX 12345",
        "zip_code": "12345",
        "state": "TX",
        "latitude": 29.761,
        "longitude": -95.368,
        "source_url": "https://...",
        "source_type": "google_maps",
        "synced_to_crm": true,
        "crm_competitor_kiosk_name": "COMP-KIOSK-0001"
      }
    ]
  }
}
```

## 4. Competitor Kiosk Upsert

Method:

- `cclms.api.desktop_tracker.upsert_competitor_kiosk`

Request:

```json
{
  "device_id": "DEVICE-ID",
  "name": "Target Location Name",
  "address": "123 Main St, Houston, TX 12345",
  "zip_code": "12345",
  "state": "TX",
  "latitude": 29.7604,
  "longitude": -95.3698,
  "source_url": "https://www.google.com/maps/...",
  "source_type": "google_maps",
  "fingerprint": "stable-fingerprint"
}
```

Response:

```json
{
  "message": {
    "name": "COMP-KIOSK-0002",
    "created": true,
    "duplicate": false
  }
}
```

Notes:

- server must be idempotent by fingerprint or equivalent normalized rule
- duplicate writes must not create repeated records

## 5. Location Validation Endpoint

Method:

- `cclms.api.desktop_tracker.validate_location_scope`

This is optional. The current client can work without it, but it is recommended if you want backend-enforced validation for special business rules.

Request:

```json
{
  "device_id": "DEVICE-ID",
  "place_name": "ABC Mart",
  "address": "123 Main St, Houston, TX 12345",
  "zip_code": "12345",
  "state": "TX",
  "latitude": 29.7604,
  "longitude": -95.3698,
  "source_type": "google_maps",
  "url": "https://..."
}
```

Response:

```json
{
  "message": {
    "allowed": true,
    "status": "Proceed",
    "zone_color": "Green",
    "zip_score": 84,
    "duplicate_found": false,
    "workflow_state": "",
    "reason": ""
  }
}
```

## 6. Device Notifications

Method:

- `cclms.api.desktop_tracker.get_device_notifications`

Request:

```json
{
  "device_id": "DEVICE-ID",
  "system_info": {
    "device_id": "DEVICE-ID",
    "machine_name": "DESKTOP-01",
    "windows_username": "user"
  }
}
```

Response:

```json
{
  "message": [
    {
      "notification_id": "policy-warning-001",
      "enabled": true,
      "title": "Policy Warning",
      "message": "Restricted location. Do not proceed.",
      "repeat_seconds": 300,
      "severity": "warning"
    }
  ]
}
```

## 7. Device Actions

Method:

- `cclms.api.desktop_tracker.get_device_actions`

Request:

```json
{
  "device_id": "DEVICE-ID",
  "system_info": {
    "device_id": "DEVICE-ID",
    "machine_name": "DESKTOP-01",
    "windows_username": "user"
  }
}
```

Response:

```json
{
  "message": [
    {
      "action_id": "ACT-0001",
      "device_id": "DEVICE-ID",
      "action_type": "change_local_password",
      "payload": {
        "target_username": "user",
        "new_password": "StrongPassword123!",
        "force_logoff_after_change": true
      },
      "expires_at": "2026-03-19 09:00:00"
    }
  ]
}
```

Action ack method:

- `cclms.api.desktop_tracker.ack_device_action`

Request:

```json
{
  "action_id": "ACT-0001",
  "device_id": "DEVICE-ID",
  "status": "success",
  "message": "Local password changed for user"
}
```

Additional supported action types on the Windows client:

- `collect_diagnostics`
- `close_duplicate_tracker_processes`
- `flush_dns`
- `clear_offline_queue`
- `clear_app_temp_files`
- `reset_notification_cache`
- `repair_tracker_runtime`

## 8. Biometric Attendance Ingest

Method:

- `cclms.api.desktop_tracker.ingest_biometric_attendance`

Request:

```json
{
  "device_id": "DEVICE-ID",
  "biometric_device": {
    "enabled": true,
    "ip": "192.168.1.201",
    "port": 4370,
    "password": "12345",
    "device_serial": "ZK-01"
  },
  "records": [
    {
      "uid": 1,
      "user_id": "EMP-001",
      "timestamp": "2026-03-19 08:10:00",
      "status": 0,
      "punch": 0,
      "device_ip": "192.168.1.201"
    }
  ]
}
```

Response:

```json
{
  "message": {
    "accepted": 1,
    "duplicates": 0
  }
}
```

## 9. Productivity Rules

The client will apply rules only if CRM returns them.

Policy fragment:

```json
{
  "productivity_rules": [
    {
      "name": "Excel Productive",
      "process_name": "excel.exe",
      "rating": "productive",
      "score": 1
    },
    {
      "name": "Facebook Unproductive",
      "process_name": "chrome.exe",
      "domain": "facebook.com",
      "rating": "unproductive",
      "score": -1
    }
  ]
}
```

## 10. Map Intelligence Policy

Optional policy fragment:

```json
{
  "map_intelligence_enabled": true,
  "map_sync_scope_seconds": 180,
  "map_context_debounce_seconds": 20,
  "competitor_keywords": ["atm", "bitcoin atm", "crypto kiosk", "coinhub", "coinflip"],
  "map_popup_enabled": true
}
```

## 11. Device Health Report

Method:

- `cclms.api.desktop_tracker.report_device_health`

Request:

```json
{
  "device_id": "DEVICE-ID",
  "machine_name": "DESKTOP-01",
  "windows_username": "user",
  "version": "0.1.0",
  "queue_count": 0,
  "process_count": 1,
  "dns_status": {
    "host": "crm.galaxylabs.online",
    "ok": true,
    "ip": "31.97.197.65"
  },
  "last_log_lines": [
    "2026-03-19 08:10:00 INFO Bootstrapping tracker..."
  ],
  "time_utc": "2026-03-19 08:15:00",
  "system_info": {
    "device_id": "DEVICE-ID",
    "machine_name": "DESKTOP-01",
    "windows_username": "user"
  }
}
```

Purpose:

- identify broken devices centrally
- see DNS or queue problems remotely
- support admin troubleshooting actions from CRM

## 12. Call Details Ingest

Method:

- `cclms.api.desktop_tracker.ingest_call_details`

Request:

```json
{
  "device_id": "DEVICE-ID",
  "call_id": "DEVICE-ID-1710830000",
  "source_system": "windows-inferred-call",
  "active_app": "ringcentral.exe",
  "window_title": "John Smith - Incoming call +1 555 111 2222",
  "direction": "incoming",
  "caller_id": "John Smith",
  "caller_phone": "+15551112222",
  "callee_phone": "+15551112222",
  "phone_number": "+15551112222",
  "start_time": "2026-03-19 08:20:00",
  "end_time": "2026-03-19 08:25:15",
  "duration_seconds": 315,
  "status": "Completed",
  "system_info": {
    "device_id": "DEVICE-ID",
    "machine_name": "DESKTOP-01",
    "windows_username": "user"
  }
}
```

Notes:

- this is metadata-only
- use RingCentral or backend archival for actual recording evidence
- do not require audio capture from the Windows agent to use this endpoint

## Implementation Notes For Backend

- keep all scoped sync payloads small and local to the user’s current viewed area
- avoid returning national datasets
- make upserts idempotent
- duplicate prevention should rely on server-side normalized fingerprint logic too
- if a feature is not enabled, return nothing or omit the field entirely
- do not require the client to use these APIs unless policy explicitly enables the related feature
