# Backend Logic Spec

This document defines what the Frappe backend should implement for the current Windows tracker client in this repository.

## 1. Compatibility Check

### Implemented in this Windows client

- core tracking:
  - login
  - logout
  - heartbeat
  - browser history visits
  - random screen snapshots
- offline queue to local SQLite
- retry/restart for transient DNS/network failures
- GitHub-release auto-update support
- inferred softphone call metadata:
  - `call_id`
  - `start_time`
  - `end_time`
  - `duration_seconds`
  - `active_app`
  - `window_title`
  - `phone_number` when it can be inferred from window title
  - `caller_phone`
  - `caller_id`
- optional device health reporting
- optional device action polling and acknowledgements
- local troubleshooting actions

### Not implemented in this Windows client repo

Do not assume these exist yet on the Windows side:

- CRM notification polling / local repeated notification display
- biometric attendance device sync
- map intelligence / scouting mode
- ZIP cache sync
- competitor kiosk discovery
- lead duplicate overlay logic
- browser extension / DOM overlays
- local raw voice recording

These can be added later, but backend should not block current rollout waiting for them.

## 2. Source Of Truth

- CRM/Frappe remains the source of truth.
- The Windows client is a field/runtime agent only.
- Device enrollment and identity mapping come from CRM.
- Every sensitive remote action must be authorized, auditable, and scoped to a specific `device_id`.

## 3. Required Backend APIs

### 3.1 `cclms.api.desktop_tracker.get_tracking_policy`

This already exists and remains the bootstrap entry point.

Current response should continue to support:

- `binding`
- `heartbeat_seconds`
- `snapshot_min_minutes`
- `snapshot_max_minutes`
- `call_process_hints`

Extend it to optionally return:

```json
{
  "message": {
    "binding": {
      "name": "TD-0001",
      "tracked_user": "agent@example.com",
      "employee": "EMP-0001",
      "sales_agent": "AG-0001"
    },
    "heartbeat_seconds": 60,
    "snapshot_min_minutes": 45,
    "snapshot_max_minutes": 75,
    "call_process_hints": ["ringcentral.exe", "zoiper.exe", "teams.exe"],
    "device_actions_enabled": true,
    "device_actions_poll_seconds": 120,
    "device_actions_method": "cclms.api.desktop_tracker.get_device_actions",
    "device_action_ack_method": "cclms.api.desktop_tracker.ack_device_action",
    "device_health_enabled": true,
    "device_health_poll_seconds": 300,
    "device_health_method": "cclms.api.desktop_tracker.report_device_health"
  }
}
```

Rules:

- if optional keys are missing, the client keeps working normally
- `binding` remains mandatory

### 3.2 `cclms.api.desktop_tracker.report_device_health`

Purpose:

- lightweight periodic health reporting from each laptop

Expected payload:

```json
{
  "device_id": "WIN-LAPTOP-01",
  "machine_name": "WIN-LAPTOP-01",
  "windows_username": "aqn",
  "version": "0.1.3",
  "time_utc": "2026-03-19 12:00:00",
  "queue_count": 0,
  "tracker_process_count": 1,
  "dns_status": {
    "host": "crm.example.com",
    "resolved": true,
    "ip_address": "1.2.3.4"
  },
  "system_info": {
    "device_id": "WIN-LAPTOP-01",
    "machine_name": "WIN-LAPTOP-01",
    "windows_username": "aqn",
    "ip_address": "192.168.1.10",
    "platform": "win32",
    "platform_release": "10",
    "platform_version": "10.0.19045",
    "cpu_percent": 12.5,
    "memory_percent": 55.2
  },
  "top_processes": [
    {"pid": 1234, "name": "chrome.exe", "rss_mb": 512.4}
  ],
  "recent_log_lines": [
    "2026-03-19 12:00:00 INFO Bootstrapping tracker ..."
  ],
  "binding": {
    "name": "TD-0001"
  }
}
```

Backend logic:

- upsert by `device_id`
- store latest:
  - report time
  - app version
  - queue count
  - tracker process count
  - DNS resolution status
  - memory/cpu summary
  - last recent log bundle
- support dashboards for:
  - stale devices
  - queue backlog
  - DNS failures
  - repeated multi-process issues
  - old app versions

### 3.3 `cclms.api.desktop_tracker.get_device_actions`

Purpose:

- deliver pending remote-control actions for a specific laptop

Expected request:

```json
{
  "device_id": "WIN-LAPTOP-01",
  "system_info": {
    "device_id": "WIN-LAPTOP-01",
    "machine_name": "WIN-LAPTOP-01",
    "windows_username": "aqn"
  }
}
```

Expected response:

```json
{
  "message": [
    {
      "action_id": "DA-0001",
      "device_id": "WIN-LAPTOP-01",
      "action_type": "collect_diagnostics",
      "payload": {},
      "expires_at": "2026-03-19 12:30:00"
    }
  ]
}
```

Only return actions that are:

- for this device
- not expired
- not already completed/failed/cancelled

Supported action types in the current client:

- `collect_diagnostics`
- `flush_dns`
- `clear_offline_queue`
- `reset_notification_cache`
- `repair_tracker_runtime`
- `terminate_duplicate_tracker_processes`
- `clear_temp_files`
- `open_task_manager`
- `open_device_manager`
- `change_local_password`
- `clear_prefetch`

Important:

- `clear_prefetch` is blocked on the client unless local config explicitly enables `allow_aggressive_cleanup`
- backend should not expose arbitrary command execution

### 3.4 `cclms.api.desktop_tracker.ack_device_action`

Purpose:

- receive action completion/failure state from the device

Expected payload:

```json
{
  "action_id": "DA-0001",
  "device_id": "WIN-LAPTOP-01",
  "status": "success",
  "message": "",
  "result": {
    "deleted_rows": 5
  },
  "time_utc": "2026-03-19 12:05:00",
  "system_info": {
    "device_id": "WIN-LAPTOP-01",
    "machine_name": "WIN-LAPTOP-01",
    "windows_username": "aqn"
  }
}
```

Backend logic:

- mark action status
- save result payload
- save human-readable message
- stop returning terminal actions in `get_device_actions`

## 4. Existing Tracking Endpoints

These remain required:

- `cclms.api.desktop_tracker.ingest_activity`
- `cclms.api.desktop_tracker.ingest_call`
- `cclms.api.desktop_tracker.ingest_logout`

### 4.1 `ingest_call` expected metadata

The Windows client currently sends inferred call metadata only. Backend should support these optional fields:

- `call_id`
- `start_time`
- `end_time`
- `duration_seconds`
- `active_app`
- `window_title`
- `phone_number`
- `caller_phone`
- `caller_id`
- `status`
- `source_system`
- `system_info`

Important:

- this is metadata, not raw audio
- do not make backend assume voice recording is being uploaded

## 5. Recommended Backend Data Model

### 5.1 Tracker Device

Already used for:

- `device_id`
- tracked CRM user
- employee
- sales agent
- allowed service user
- policy settings

Recommended extra fields:

- `latest_app_version`
- `latest_health_report_at`
- `latest_queue_count`
- `latest_tracker_process_count`
- `latest_dns_ok`
- `latest_dns_ip`
- `latest_memory_percent`
- `latest_cpu_percent`
- `latest_log_excerpt`
- `device_health_status`

### 5.2 Device Action

Recommended fields:

- `name`
- `device_id`
- `tracker_device`
- `action_type`
- `payload_json`
- `status`
- `created_by`
- `approved_by`
- `created_at`
- `expires_at`
- `started_at`
- `completed_at`
- `result_json`
- `message`

Statuses:

- `Pending`
- `Success`
- `Failed`
- `Expired`
- `Cancelled`

### 5.3 Device Health Snapshot

You can either:

- store latest state directly on `Tracker Device`
- or maintain a separate log/history doctype

If storing history, fields should include:

- `device_id`
- `tracker_device`
- `reported_at`
- `app_version`
- `queue_count`
- `tracker_process_count`
- `dns_host`
- `dns_resolved`
- `dns_ip`
- `system_info_json`
- `top_processes_json`
- `recent_log_lines_json`

## 6. Business Logic Rules

### 6.1 Device health state

Suggested health classification:

- `Healthy`
  - recently reported
  - queue count normal
  - tracker process count acceptable
  - DNS resolves
- `Warning`
  - queue backlog present
  - repeated multi-process issue
  - high memory %
- `Offline`
  - no report for configured threshold
- `Error`
  - repeated failed actions
  - DNS unresolved for several reports

### 6.2 Action security

- only admins or approved roles can create actions
- password-change actions should require stronger approval
- every action should be device-specific
- every action should expire
- no arbitrary shell/PowerShell commands from CRM

### 6.3 Cleanup policy

Client-side safe cleanup already includes:

- offline queue clear
- temp-file cleanup
- duplicate tracker process cleanup
- DNS flush

Aggressive cleanup:

- `clear_prefetch` should be opt-in only
- backend should not schedule it by default

## 7. Suggested Backend Dashboard

Create a report/dashboard showing:

- device
- employee / sales agent
- app version
- last seen
- queue count
- tracker process count
- DNS status
- latest memory %
- latest action result
- last action time
- health status

Useful filters:

- unhealthy devices
- stale devices
- devices with queue backlog
- devices with failed password-change or repair actions

## 8. Deployment Priority

Backend should be implemented in this order:

1. extend `get_tracking_policy` optional keys
2. implement `report_device_health`
3. implement `get_device_actions`
4. implement `ack_device_action`
5. extend `ingest_call` metadata fields and reporting
6. add dashboards and action workflows

## 9. Explicit Non-Goals For This Phase

Do not assume phase-1 backend must include:

- map scouting APIs
- competitor kiosk sync
- ZIP intelligence
- biometric device sync
- local voice recording upload
- browser overlays

Those belong to later phases after this current Windows repo is stabilized and deployed.
