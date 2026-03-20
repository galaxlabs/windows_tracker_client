# Browser Extension Backend Contract

This document defines the backend contract for the Chrome extension in `browser_extension/`.

## 1. Validation Endpoint

Method:

- `cclms.api.browser_extension.validate_location_scope`

Request:

```json
{
  "place": {
    "source_url": "https://www.google.com/maps/place/...",
    "source_type": "google_maps",
    "name": "ABC Fuel",
    "business_name": "ABC Fuel",
    "normalized_business_name": "abc fuel",
    "address": "123 Main St, Dallas, TX 75001, USA",
    "normalized_address": "123 main st dallas tx 75001 usa",
    "phone": "1234567890",
    "website": "https://example.com",
    "category": "Gas station",
    "coordinates": {"lat": 32.99, "lng": -96.82},
    "zip_code": "75001",
    "city": "Dallas",
    "state": "TX",
    "place_fingerprint": "abc fuel|123 main st...",
    "dedup_keys": {
      "business_name": "ABC Fuel",
      "normalized_business_name": "abc fuel",
      "address": "123 Main St, Dallas, TX 75001, USA",
      "normalized_address": "123 main st dallas tx 75001 usa",
      "zip_code": "75001",
      "city": "Dallas",
      "state": "TX",
      "latitude": 32.99,
      "longitude": -96.82,
      "phone": "1234567890",
      "website": "https://example.com"
    }
  },
  "device_id": "WIN-LAPTOP-01",
  "employee": "EMP-0001",
  "browser_context": {
    "source": "google_maps_extension"
  }
}
```

Response:

```json
{
  "message": {
    "exists_in_atm_leads": true,
    "existing_lead_name": "ATM-LEAD-0001",
    "workflow_state": "Approved",
    "exists_in_competitors": false,
    "zip_score": 87,
    "zone_color": "green",
    "recommendation": "Open Existing Lead",
    "duplicate_reason": "Address and business name match",
    "matched_by": "business_name + normalized_address + zip_code",
    "competitor_count": 4,
    "open_existing_lead_url": "https://crm.example.com/app/atm-lead/ATM-LEAD-0001"
  }
}
```

Backend should validate ATM Lead duplicates using a layered strategy:

- exact lead or location-lock match if available
- `normalized_business_name + normalized_address + zip_code`
- `business_name + zip_code + city`
- nearby coordinate match inside a small configured radius
- phone match when available
- website/domain match when available

## 2. Prefill Lead Endpoint

Method:

- `cclms.api.browser_extension.prefill_atm_lead_context`

Request:

```json
{
  "place": {
    "name": "ABC Fuel",
    "business_name": "ABC Fuel",
    "address": "123 Main St, Dallas, TX 75001, USA",
    "city": "Dallas",
    "zip_code": "75001",
    "state": "TX",
    "phone": "1234567890",
    "website": "https://example.com",
    "coordinates": {"lat": 32.99, "lng": -96.82},
    "category": "Gas station"
  },
  "device_id": "WIN-LAPTOP-01",
  "employee": "EMP-0001",
  "source_system": "google_maps"
}
```

Response:

```json
{
  "message": {
    "open_url": "https://crm.example.com/app/atm-leads/new-atm-leads-srltkcnnxj?prefill_token=abc123"
  }
}
```

Important:

- backend must return the exact Frappe route in `open_url`
- the extension should not guess the doctype route
- this is required because your CRM may use dynamic/new-document routes
- backend should also enforce create permission before returning `open_url`

If duplicate blocks creation:

```json
{
  "message": {
    "warning": "This location already exists at workflow state: Approved",
    "open_existing_lead_url": "https://crm.example.com/app/atm-lead/ATM-LEAD-0001"
  }
}
```

Recommended backend behavior:

- if user can create ATM Leads:
  - return `open_url`
- if user cannot create ATM Leads:
  - return `warning`
- if duplicate exists:
  - return `warning` and `open_existing_lead_url`

## 3. Competitor Upsert Endpoint

Method:

- `cclms.api.browser_extension.upsert_competitor_kiosk`

Request:

```json
{
  "place": {
    "name": "ABC Fuel",
    "business_name": "ABC Fuel",
    "address": "123 Main St, Dallas, TX 75001, USA",
    "city": "Dallas",
    "zip_code": "75001",
    "state": "TX",
    "coordinates": {"lat": 32.99, "lng": -96.82},
    "source_url": "https://www.google.com/maps/place/...",
    "place_fingerprint": "abc fuel|123 main st..."
  },
  "device_id": "WIN-LAPTOP-01",
  "employee": "EMP-0001",
  "source_system": "chrome_extension"
}
```

Response:

```json
{
  "message": {
    "status": "upserted",
    "competitor_kiosk_name": "COMP-0001",
    "dedup_reason": ""
  }
}
```

## 4. Browser Notifications

Optional methods:

- `cclms.api.browser_extension.get_browser_notifications`
- `cclms.api.browser_extension.ack_browser_notification`

`get_browser_notifications` request:

```json
{
  "device_id": "WIN-LAPTOP-01",
  "employee": "EMP-0001",
  "page_context": {
    "source": "google_chat",
    "url": "https://chat.google.com/...",
    "title": "Google Chat"
  }
}
```

Response:

```json
{
  "message": [
    {
      "notification_id": "crm-reminder-001",
      "title": "Follow Up",
      "message": "Lead ATM-LEAD-0001 needs a callback today."
    }
  ]
}
```
