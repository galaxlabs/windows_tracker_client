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
5. Open the extension options page and configure:
   - CRM base URL
   - auth mode
   - API token or cookie-session mode
   - device ID
   - employee

## Backend Work

Use:

- [BROWSER_EXTENSION_BACKEND_CONTRACT.md](/c:/Users/AQN/Downloads/windows_tracker_client/browser_extension/BROWSER_EXTENSION_BACKEND_CONTRACT.md)

The backend in `cclms` must implement the validation, prefill, competitor upsert, and optional browser notification APIs.
