try {
  importScripts("local.defaults.js");
} catch (error) {
}

importScripts("shared/storage.js", "shared/api.js");

const DEFAULTS = {
  crmBaseUrl: "https://crm.galaxylabs.online",
  validateMethod: "cclms.api.browser_extension.validate_location_scope",
  competitorMethod: "cclms.api.browser_extension.upsert_competitor_kiosk",
  prefillMethod: "cclms.api.browser_extension.prefill_atm_lead_context",
  notificationsMethod: "cclms.api.browser_extension.get_browser_notifications",
  ackNotificationMethod: "cclms.api.browser_extension.ack_browser_notification",
  cacheTtlSeconds: 180,
  chatEnabled: false,
  mapsEnabled: true,
  authMode: "token",
  apiToken: "",
  deviceId: "",
  employee: ""
};

if (typeof CCLMS_LOCAL_DEFAULTS === "object" && CCLMS_LOCAL_DEFAULTS) {
  Object.assign(DEFAULTS, CCLMS_LOCAL_DEFAULTS);
}

const inMemoryCache = new Map();

async function logEvent(scope, event, details) {
  try {
    await CCLMSStorage.appendLog({
      scope,
      event,
      details: details || {}
    });
  } catch (error) {
  }
}

function cacheKey(prefix, payload) {
  return `${prefix}:${JSON.stringify(payload)}`;
}

async function getSettings() {
  return await CCLMSStorage.getSettings(DEFAULTS);
}

async function getCached(prefix, payload) {
  const settings = await getSettings();
  const key = cacheKey(prefix, payload);
  const row = inMemoryCache.get(key);
  if (!row) {
    return null;
  }
  if (Date.now() - row.createdAt > settings.cacheTtlSeconds * 1000) {
    inMemoryCache.delete(key);
    return null;
  }
  return row.value;
}

function setCached(prefix, payload, value) {
  inMemoryCache.set(cacheKey(prefix, payload), { value, createdAt: Date.now() });
}

async function validatePlace(place) {
  const settings = await getSettings();
  const payload = {
    place,
    device_id: settings.deviceId || "",
    employee: settings.employee || "",
    browser_context: {
      source: "google_maps_extension"
    }
  };
  const cached = await getCached("validate", payload);
  if (cached) {
    await logEvent("background", "validate_place_cache_hit", {
      fingerprint: place.place_fingerprint || "",
      name: place.name || ""
    });
    return cached;
  }
  await logEvent("background", "validate_place_request", {
    fingerprint: place.place_fingerprint || "",
    name: place.name || ""
  });
  const result = await CCLMSApi.post(settings, settings.validateMethod, payload);
  setCached("validate", payload, result);
  await logEvent("background", "validate_place_success", {
    fingerprint: place.place_fingerprint || "",
    name: place.name || ""
  });
  return result;
}

async function saveCompetitor(place) {
  const settings = await getSettings();
  await logEvent("background", "save_competitor_request", {
    fingerprint: place.place_fingerprint || "",
    name: place.name || ""
  });
  const result = await CCLMSApi.post(settings, settings.competitorMethod, {
    place,
    device_id: settings.deviceId || "",
    employee: settings.employee || "",
    source_system: "chrome_extension"
  });
  await logEvent("background", "save_competitor_success", {
    fingerprint: place.place_fingerprint || "",
    name: place.name || ""
  });
  return result;
}

async function prefillLead(place) {
  const settings = await getSettings();
  await logEvent("background", "prefill_lead_request", {
    fingerprint: place.place_fingerprint || "",
    name: place.name || ""
  });
  const result = await CCLMSApi.post(settings, settings.prefillMethod, {
    place,
    device_id: settings.deviceId || "",
    employee: settings.employee || "",
    source_system: "google_maps"
  });
  await logEvent("background", "prefill_lead_success", {
    fingerprint: place.place_fingerprint || "",
    name: place.name || ""
  });
  return result;
}

async function getBrowserNotifications(pageContext) {
  const settings = await getSettings();
  if (!settings.chatEnabled) {
    return { message: [] };
  }
  return await CCLMSApi.post(settings, settings.notificationsMethod, {
    device_id: settings.deviceId || "",
    employee: settings.employee || "",
    page_context: pageContext || {}
  });
}

async function ackBrowserNotification(notificationId) {
  const settings = await getSettings();
  return await CCLMSApi.post(settings, settings.ackNotificationMethod, {
    notification_id: notificationId,
    device_id: settings.deviceId || "",
    employee: settings.employee || ""
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    try {
      if (message.type === "GET_SETTINGS") {
        sendResponse({ ok: true, settings: await getSettings() });
        return;
      }
      if (message.type === "LOG_EVENT") {
        await logEvent(message.scope || "extension", message.event || "log", message.details || {});
        sendResponse({ ok: true });
        return;
      }
      if (message.type === "GET_STORAGE_STATE") {
        sendResponse({
          ok: true,
          data: await chrome.storage.local.get(null)
        });
        return;
      }
      if (message.type === "GET_DEBUG_LOGS") {
        sendResponse({
          ok: true,
          logs: await CCLMSStorage.getValue("debugLogs", [])
        });
        return;
      }
      if (message.type === "CLEAR_DEBUG_LOGS") {
        await CCLMSStorage.clearLogs();
        sendResponse({ ok: true });
        return;
      }
      if (message.type === "SAVE_SETTINGS") {
        await CCLMSStorage.saveSettings(message.settings || {});
        await logEvent("background", "save_settings", {
          keys: Object.keys(message.settings || {})
        });
        sendResponse({ ok: true });
        return;
      }
      if (message.type === "VALIDATE_PLACE") {
        sendResponse({ ok: true, data: await validatePlace(message.place || {}) });
        return;
      }
      if (message.type === "SAVE_COMPETITOR") {
        sendResponse({ ok: true, data: await saveCompetitor(message.place || {}) });
        return;
      }
      if (message.type === "PREFILL_LEAD") {
        sendResponse({ ok: true, data: await prefillLead(message.place || {}) });
        return;
      }
      if (message.type === "OPEN_URL") {
        chrome.tabs.create({ url: message.url });
        await logEvent("background", "open_url", { url: message.url || "" });
        sendResponse({ ok: true });
        return;
      }
      if (message.type === "GET_BROWSER_NOTIFICATIONS") {
        sendResponse({ ok: true, data: await getBrowserNotifications(message.pageContext || {}) });
        return;
      }
      if (message.type === "ACK_BROWSER_NOTIFICATION") {
        sendResponse({ ok: true, data: await ackBrowserNotification(message.notificationId) });
        return;
      }
      sendResponse({ ok: false, error: "Unsupported message type" });
    } catch (error) {
      await logEvent("background", "message_error", {
        type: message?.type || "",
        error: error.message || String(error)
      });
      sendResponse({ ok: false, error: error.message || String(error) });
    }
  })();
  return true;
});
