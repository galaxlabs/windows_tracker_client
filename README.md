# Windows Tracker Client

This is the standalone Windows client for CCLMS tracking.

It is separate from the `cclms` app codebase, but it sends data into the backend APIs inside `cclms`.

## What It Sends

- login and logout
- active foreground app and window title
- browser visit history from Chrome / Edge
- random hourly screenshots
- inferred softphone call sessions
- system info such as machine name, Windows username, and IP

## Backend Endpoints

- `cclms.api.desktop_tracker.ingest_activity`
- `cclms.api.desktop_tracker.ingest_call`
- `cclms.api.desktop_tracker.ingest_logout`
- `cclms.api.desktop_tracker.get_tracking_policy`

Optional CRM-driven extensions can also be enabled without breaking the normal tracker flow:

- productivity rules returned by policy
- device actions polled from CRM
- device health reporting and troubleshooting actions
- local repeating notifications polled from CRM
- map intelligence / scouting assistance with local SQLite cache
- biometric attendance sync using CRM-provided device settings
- optional call metadata extraction for softphone workflows

## Embedded Defaults

The EXE is designed to ship with your default connection details already embedded in:

- [embedded_defaults.py](/home/dg/dg-b/windows_tracker_client/embedded_defaults.py)

Set these before building:

- `site_url`
- `api_key`
- `api_secret`
- `github_repo` for auto updates, default: `galaxlabs/windows_tracker_client`

This means the installed client can work without asking each user to type those values.

## Local Override File

If you want per-device overrides, place a `config.json` next to the EXE.

Example:

```json
{
  "device_id": "WIN-LAPTOP-01"
}
```

The local `config.json` overrides the embedded defaults.

You can also override update settings locally, for example:

```json
{
  "device_id": "WIN-LAPTOP-01",
  "github_repo": "galaxlabs/windows_tracker_client",
  "github_release_asset": "cclms-tracker-windows-x64.zip",
  "auto_update_enabled": true
}
```

If `config.json` is missing or incomplete, you can launch:

- [setup_config.ps1](/home/dg/dg-b/windows_tracker_client/setup_config.ps1)

It opens a Windows setup dialog to collect:

- CRM Base URL
- API Key
- API Secret
- Device ID
- GitHub release settings
- notification, device-action, device-health, biometric, map, call-metadata, auto-update, and SSL toggles
- poll/check intervals

The UI now writes the common runtime options into `config.json`, so you do not need to keep editing hidden config keys after rebuilds.

Do not put each employee user or employee ID into the local config anymore.
The Windows client auto-detects:

- Windows username
- machine name
- device info

The backend resolves the real tracked CRM user, Employee, and Sales Agent from `Tracker Device` and `Device Profile`.

## Recommended Multi-User Rollout

1. Create one restricted service user in CRM, for example `tracker.agent@yourcompany.com`
2. Give it the `Tracker Agent` role
3. Generate one API key/secret for that service user
4. Put that API key/secret into `embedded_defaults.py`
5. Create one `Device Profile` or `Tracker Device` record per laptop in CCLMS
6. Set:
   - `device_id`
   - `tracked_user`
   - `employee`
   - `sales_agent`
   - `allowed_service_user`
7. Build the EXE once
8. On each laptop, only set a small `config.json` if you want a custom `device_id`

This means:

- one shared service API user
- no per-user API key on each laptop
- no manual `user` or `employee` fields in local config
- backend maps laptop -> tracked user -> employee -> sales agent

## Build EXE

Run on a Windows machine:

```powershell
.\build_exe.ps1
```

This will:

- create `.venv`
- recreate a broken `.venv` automatically if needed
- install runtime and build dependencies
- build `dist\cclms-tracker.exe`

Build files:

- [build_exe.ps1](/home/dg/dg-b/windows_tracker_client/build_exe.ps1)
- [tracker.spec](/home/dg/dg-b/windows_tracker_client/tracker.spec)
- [requirements-build.txt](/home/dg/dg-b/windows_tracker_client/requirements-build.txt)
- [version.py](/home/dg/dg-b/windows_tracker_client/version.py)

## GitHub Releases And Auto Update

The project now supports update checks against GitHub Releases when running as the packaged EXE.

Set these values in `embedded_defaults.py` or `config.json`:

- `github_repo` default: `galaxlabs/windows_tracker_client`
- `github_release_asset` default: `cclms-tracker-windows-x64.zip`
- `auto_update_enabled` default: `true`
- `auto_update_check_minutes` default: `360`

Other optional runtime controls:

- `device_actions_enabled`
- `device_actions_poll_seconds`
- `device_health_enabled`
- `device_health_poll_seconds`
- `notifications_enabled`
- `notifications_poll_seconds`
- `map_intelligence_enabled`
- `biometric_sync_enabled`
- `biometric_sync_interval_minutes`

How it works:

1. The installed EXE checks GitHub Releases on startup
2. If a newer version exists, it downloads the configured zip asset
3. A helper PowerShell updater stops the scheduled task, replaces the local files, and starts the task again

Release workflow:

1. Push to `main`
2. GitHub Actions builds the Windows EXE automatically
3. The workflow updates a rolling GitHub release tagged `latest`
4. Installed clients can auto-update from that newest build

Stable release workflow:

1. Bump [version.py](/home/dg/dg-b/windows_tracker_client/version.py)
2. Push a git tag like `v0.1.3`
3. GitHub Actions builds the Windows EXE
4. The workflow publishes a stable tagged release with:
   - `cclms-tracker.exe`
   - `cclms-tracker-windows-x64.zip`

Update behavior:

- branch pushes to `main` publish a rolling `latest` release for fast ongoing updates
- tagged pushes publish stable versioned releases
- the installed client checks the `latest` tagged release first, then falls back to the latest stable GitHub release
- clients update from built release assets, not from raw source code

Recommended push flow:

```bash
git push origin main
git push origin v0.1.3
```

Important:

- do not create or push a local `latest` tag manually
- `latest` is managed automatically by GitHub Actions for rolling development builds
- create only normal version tags locally, such as `v0.1.3`, `v0.1.4`, and so on

Workflow file:

- [.github/workflows/release.yml](/home/dg/dg-b/windows_tracker_client/.github/workflows/release.yml)
- [BACKEND_API_CONTRACT.md](/home/dg/dg-b/windows_tracker_client/BACKEND_API_CONTRACT.md)

## Install As Windows Service

Recommended with `nssm`.

1. Build the EXE
2. Install `nssm`
3. Run:

```powershell
.\install_service.ps1
```

Or double-click:

```bat
install_service.bat
```

Installer files:

- [install_service.ps1](/home/dg/dg-b/windows_tracker_client/install_service.ps1)
- [install_service.bat](/home/dg/dg-b/windows_tracker_client/install_service.bat)

By default this installs:

- service name: `CCLMS-Tracker`
- executable: `dist\cclms-tracker.exe`
- config: `config.json`

If `config.json` is missing or incomplete, the installer will open the setup popup automatically before installing the service.

## Recommended User Install

For normal users, do not run `python agent.py`.

Use this flow instead:

1. Build the EXE once with `.\build_exe.ps1`
2. Put the final `dist\cclms-tracker.exe` and `config.json` on the laptop
3. Open PowerShell as Administrator
4. Run `.\install_service.ps1`

This removes Python, `pip`, and `.venv` from the end-user path.

If you rerun `.\install_service.ps1`, it now refreshes an existing scheduled task or NSSM service, stops the old instance, and starts the latest one again.
If `device_id` is missing, the installer now writes the Windows computer name automatically.

You can check whether it is installed and running with:

```powershell
.\check_tracker_status.ps1
```

## Control Center

For USB rollout and simple local operation, use:

```powershell
.\tracker_control_center.ps1
```

or double-click:

```bat
tracker_control_center.bat
```

This small UI uses `config.json` as the single source of truth and can:

- edit and save tracker config
- toggle notifications, device actions, health, biometric sync, map intelligence, call metadata, auto update, and SSL verification
- edit poll/check intervals
- choose install mode: `Task`, `Service`, or `Auto`
- sync browser extension defaults from the same config
- build the EXE
- install or refresh the scheduled task
- run one-click `Install All`
- run the agent
- start or stop the tracker
- open the browser extension folder
- show tracker task/process status

## Development Run

```powershell
.\run_agent.ps1
```

Or with a specific config file:

```powershell
.\run_agent.ps1 .\config.json
```

`run_agent.ps1` will:

- create `.venv` if missing
- repair a broken virtual environment
- bootstrap `pip` if it is missing
- install dependencies from `requirements.txt`
- run the tracker with the selected config file

## Tracker Device Mapping

Use the laptop hostname as `device_id` if you want the easiest rollout.
You can see the Windows hostname with:

```powershell
hostname
```

## Notes

- Browser visits are collected from local browser history databases.
- Call duration is inferred from configured softphone foreground apps unless you later wire a direct dialer integration.
- Screenshots are uploaded to private files in Frappe.
- On startup, the agent calls `cclms.api.desktop_tracker.get_tracking_policy` and validates that the current `device_id` is enrolled in `Tracker Device`.
- The EXE writes a simple local log file named `tracker.log` next to the executable.
- If CRM provides notifications, the agent caches them locally in `notification_rules.json` and shows repeating Windows popups until CRM stops sending them.
- If CRM enables map intelligence, the agent maintains a local scouting cache in `scouting_cache.sqlite3` for ZIP guidance, lead duplicate checks, competitor caching, and scoped sync.

## Browser Extension

This repo also contains a separate browser-side helper for Google Maps and optional Google Chat:

- [browser_extension/README.md](/c:/Users/AQN/data/windows_tracker_client_clean/browser_extension/README.md)
- [browser_extension/BROWSER_EXTENSION_BACKEND_CONTRACT.md](/c:/Users/AQN/data/windows_tracker_client_clean/browser_extension/BROWSER_EXTENSION_BACKEND_CONTRACT.md)

This browser module is separate from the Windows tracker service. It is intended to:

- read the currently opened Google Maps place
- validate it with CRM
- show lightweight duplicate / ZIP guidance
- open a prefilled ATM Lead flow
- upsert competitor kiosks

To prefill browser-extension defaults from the same tracker config used by the Windows agent:

```powershell
.\sync_browser_extension_config.ps1
```

## Backend Handoff

Use:

- [BACKEND_API_CONTRACT.md](/c:/Users/AQN/data/windows_tracker_client_clean/BACKEND_API_CONTRACT.md)
- [BACKEND_AGENT_PROMPT.md](/c:/Users/AQN/data/windows_tracker_client_clean/BACKEND_AGENT_PROMPT.md)
- [BACKEND_LOGIC_SPEC.md](/c:/Users/AQN/data/windows_tracker_client_clean/BACKEND_LOGIC_SPEC.md)
- [browser_extension/BROWSER_EXTENSION_BACKEND_CONTRACT.md](/c:/Users/AQN/data/windows_tracker_client_clean/browser_extension/BROWSER_EXTENSION_BACKEND_CONTRACT.md)

These documents describe the Frappe-side work needed for:

- tracker device actions and health reporting
- call metadata persistence
- optional notifications, biometric sync, and map intelligence
- Chrome extension validation, prefill, competitor upsert, and browser notifications
