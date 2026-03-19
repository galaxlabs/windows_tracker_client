# Windows Tracker Runbook

This repo is the Windows-side tracker client used for local testing, scheduled-task setup, build troubleshooting, and runtime hardening.

The Linux/Frappe backend is handled separately.

## Current Runtime Model

- Background runtime uses a Windows scheduled task named `CCLMS-Tracker`
- Built EXE path: `dist\cclms-tracker.exe`
- Local log path: `dist\tracker.log`
- Local offline queue DB: `dist\tracker_queue.sqlite3`

Do not rely on `python agent.py config.json` for normal use. That is only for foreground debugging and stops when the terminal closes.

## Normal Verification

Run these commands in PowerShell from the repo root:

```powershell
Get-ScheduledTaskInfo -TaskName "CCLMS-Tracker"
Get-Process cclms-tracker -ErrorAction SilentlyContinue
Get-Content .\dist\tracker.log -Tail 30
python -c "import sqlite3; conn=sqlite3.connect(r'.\dist\tracker_queue.sqlite3'); print(conn.execute('select count(*) from outbound_queue').fetchone()[0]); conn.close()"
```

Healthy state:

- `LastTaskResult : 267009`
- tracker process is running
- no fresh traceback in `dist\tracker.log`
- queue count is `0` when internet is available

Offline-but-healthy state:

- process is still running
- queue count is greater than `0`
- when internet returns, queue count should go back to `0`

## Rebuild And Restart

Use this when source changed:

```powershell
Get-Process cclms-tracker -ErrorAction SilentlyContinue | Stop-Process -Force
python -m PyInstaller --clean --noconfirm .\tracker.spec
.\install_service.ps1
```

If task definition did not change, starting the task is enough:

```powershell
Start-ScheduledTask -TaskName "CCLMS-Tracker"
```

If task definition changed, rerun `install_service.ps1`.

## Clean Log Test

To test from a clean log:

```powershell
Get-Process cclms-tracker -ErrorAction SilentlyContinue | Stop-Process -Force
Rename-Item .\dist\tracker.log tracker.old.log
Start-ScheduledTask -TaskName "CCLMS-Tracker"
Get-Content .\dist\tracker.log -Tail 30
```

## What Has Already Been Fixed

Windows-side:

- scheduled-task background runtime
- task install stops old processes before start
- restart on failure
- 1 minute delayed start after logon
- MySQL-safe datetime formatting
- backend-compatible request payload style
- GitHub Releases auto-update support
- offline queue with local SQLite
- retry/restart behavior for transient DNS/network failures
- `build_exe.ps1` now uses `python -m PyInstaller`

Backend-side was fixed separately for:

- Frappe `save_file()` signature mismatch in `desktop_tracker.py`

## What Counts As Backend-Owned

If the task is running, the process is running, and the client reaches CRM but gets:

- HTTP 500
- Frappe exception
- server-side validation error

Then that is backend-owned unless the payload contract was changed locally.

## Prompt For Future Agent

```text
You are continuing work on the Windows tracker client repo on a Windows machine.

Current state:
- Background runtime uses scheduled task `CCLMS-Tracker`
- Built EXE is `dist\\cclms-tracker.exe`
- Log file is `dist\\tracker.log`
- Offline queue DB is `dist\\tracker_queue.sqlite3`
- Installer is `install_service.ps1`
- Build uses `python -m PyInstaller`

Already implemented:
- backend-compatible payload style
- MySQL-safe datetime strings
- offline queue to SQLite when CRM/DNS is unreachable
- retry/restart behavior for transient network failures
- scheduled-task startup
- installer stops old tracker processes before start
- task restart on failure
- 1 minute delayed start after logon

Verification commands:
1. `Get-ScheduledTaskInfo -TaskName "CCLMS-Tracker"`
2. `Get-Process cclms-tracker -ErrorAction SilentlyContinue`
3. `Get-Content .\\dist\\tracker.log -Tail 30`
4. `python -c "import sqlite3; conn=sqlite3.connect(r'.\\dist\\tracker_queue.sqlite3'); print(conn.execute('select count(*) from outbound_queue').fetchone()[0]); conn.close()"`

Interpretation:
- `LastTaskResult : 267009` means task is running
- queue count `0` means no pending offline events
- queue count increasing during outage then returning to `0` means offline recovery works
- fresh traceback in `dist\\tracker.log` is the current issue to investigate

Working rule:
- Fix Windows-side runtime/build/install issues in this repo
- Treat server-side Frappe exceptions as backend-owned unless a local contract change caused them
```
