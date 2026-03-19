## Backend Agent Prompt

You are working only on the Frappe backend side for the Windows tracker ecosystem. Do not change the Windows runtime/service layer; the Windows repo already handles that locally.

### Current Windows Client Behavior

The Windows client now supports these optional capabilities when CRM policy enables them:

- `report_device_health`
- `get_device_actions`
- `ack_device_action`
- offline queueing to local SQLite
- retry/restart for transient DNS/network failures
- inferred call metadata from softphone app focus and window title
- whitelisted troubleshooting actions only

The backend app is `cclms`.

### Implement These APIs

#### 1. `cclms.api.desktop_tracker.report_device_health`

Expected request payload:

```json
{
  "device_id": "WIN-LAPTOP-01",
  "machine_name": "WIN-LAPTOP-01",
  "windows_username": "aqn",
  "version": "0.1.0",
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
    "cpu_percent": 13.2,
    "memory_percent": 66.4
  },
  "top_processes": [
    {"pid": 1111, "name": "chrome.exe", "rss_mb": 523.1}
  ],
  "recent_log_lines": ["2026-03-19 12:00:00 INFO Bootstrapping tracker ..."],
  "binding": {
    "name": "TD-0001"
  }
}
```

Backend should:

- store latest health snapshot per tracker device
- expose last report time, queue count, process count, version, DNS status
- support dashboards/reports for stale or unhealthy devices
- keep updates idempotent by device

#### 2. `cclms.api.desktop_tracker.get_device_actions`

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

Supported action types already implemented in the Windows client:

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

- `clear_prefetch` is disabled locally unless `allow_aggressive_cleanup` is explicitly enabled in config
- do not add arbitrary command execution
- actions must be device-specific and auditable

#### 3. `cclms.api.desktop_tracker.ack_device_action`

Expected request:

```json
{
  "action_id": "DA-0001",
  "device_id": "WIN-LAPTOP-01",
  "status": "success",
  "message": "",
  "result": {
    "queue_count": 0
  },
  "time_utc": "2026-03-19 12:05:00",
  "system_info": {
    "device_id": "WIN-LAPTOP-01",
    "machine_name": "WIN-LAPTOP-01",
    "windows_username": "aqn"
  }
}
```

Backend should:

- mark action success or failure
- store result payload and operator-visible message
- prevent the same pending action from being returned forever after terminal state

### Call Metadata

The Windows client already sends inferred call records to:

- `cclms.api.desktop_tracker.ingest_call`

The payload can now include:

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

Treat this as metadata only. Do not implement local raw audio capture through the Windows agent by default.

### Backend Security Rules

- no arbitrary remote shell
- all device actions must be device-specific
- log who created and approved each action
- enforce action expiry
- store audit trail
- restrict password-change actions tightly

### Reporting Needed

Create backend visibility for:

- devices not reporting
- DNS resolution failures
- offline queue backlog
- duplicate tracker process problems
- repeated cleanup/repair actions
- stale client versions

### Deliverables

- Frappe doctypes or schema changes
- API methods above
- permission model and audit fields
- example payload handling
- notes about deployed Frappe compatibility if relevant
