# CCLMS Chrome Extension

This folder contains a lightweight Chrome extension for Google Maps and optional Google Chat assistance.

## Structure

- `manifest.json`
- `background.js`
- `shared/`
- `content/`
- `options.html`
- `options.js`
- `BROWSER_EXTENSION_BACKEND_CONTRACT.md`

## What It Does

- detects an opened Google Maps place
- extracts place context conservatively
- calls CRM validation APIs through the background service worker
- shows a small overlay with ZIP and duplicate guidance
- can open a prefilled ATM Lead flow
- can upsert current place as Competitor Kiosk
- can optionally show CRM reminders inside Google Chat context

## Important Limits

- no heavy scraping
- no blind clicks or crawling
- no system-level controls
- no raw audio or desktop capture
- no uncontrolled polling

## Install Locally

1. Open Chrome extensions page.
2. Enable Developer mode.
3. Click `Load unpacked`.
4. Select this `browser_extension` folder.
5. Optional: prefill the extension defaults from the tracker config:

```powershell
.\sync_browser_extension_config.ps1
```

This reads:

- [config.json](/c:/Users/AQN/data/windows_tracker_client_clean/config.json)

and writes:

- [browser_extension/local.defaults.js](/c:/Users/AQN/data/windows_tracker_client_clean/browser_extension/local.defaults.js)

6. Open the extension options page and configure:
   - CRM base URL
   - auth mode
   - API token or cookie-session mode
   - device ID
   - employee

## Backend Work

Use:

- [BROWSER_EXTENSION_BACKEND_CONTRACT.md](/c:/Users/AQN/Downloads/windows_tracker_client/browser_extension/BROWSER_EXTENSION_BACKEND_CONTRACT.md)

The backend in `cclms` must implement the validation, prefill, competitor upsert, and optional browser notification APIs.

## Auth Choice

Best default for this extension:

- use a scoped token for the extension

Why:

- simpler than cookie-session CORS handling from an extension origin
- works on Google Maps pages without requiring the user to keep a CRM tab open
- avoids fragile session/cookie dependency across tabs

If you later implement stronger browser-session integration in CRM, cookie-session mode can also be supported, but token mode is the practical default for now.
