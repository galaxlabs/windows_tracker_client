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

const inMemoryCache = new Map();

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
    return cached;
  }
  const result = await CCLMSApi.post(settings, settings.validateMethod, payload);
  setCached("validate", payload, result);
  return result;
}

async function saveCompetitor(place) {
  const settings = await getSettings();
  return await CCLMSApi.post(settings, settings.competitorMethod, {
    place,
    device_id: settings.deviceId || "",
    employee: settings.employee || "",
    source_system: "chrome_extension"
  });
}

async function prefillLead(place) {
  const settings = await getSettings();
  return await CCLMSApi.post(settings, settings.prefillMethod, {
    place,
    device_id: settings.deviceId || "",
    employee: settings.employee || "",
    source_system: "google_maps"
  });
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
      if (message.type === "SAVE_SETTINGS") {
        await CCLMSStorage.saveSettings(message.settings || {});
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
      sendResponse({ ok: false, error: error.message || String(error) });
    }
  })();
  return true;
});
