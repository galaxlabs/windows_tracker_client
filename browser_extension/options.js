const fields = [
  "crmBaseUrl",
  "authMode",
  "apiToken",
  "deviceId",
  "employee",
  "cacheTtlSeconds",
  "mapsEnabled",
  "chatEnabled"
];

async function loadSettings() {
  const response = await chrome.runtime.sendMessage({ type: "GET_SETTINGS" });
  if (!response?.ok) {
    return;
  }
  const settings = response.settings || {};
  for (const field of fields) {
    const node = document.getElementById(field);
    if (!node) {
      continue;
    }
    if (node.type === "checkbox") {
      node.checked = Boolean(settings[field]);
    } else {
      node.value = settings[field] ?? "";
    }
  }
  await refreshStorage();
  await refreshLogs();
}

async function saveSettings() {
  const payload = {};
  for (const field of fields) {
    const node = document.getElementById(field);
    if (!node) {
      continue;
    }
    payload[field] = node.type === "checkbox" ? node.checked : node.value;
  }
  payload.cacheTtlSeconds = Number(payload.cacheTtlSeconds || 180);
  const response = await chrome.runtime.sendMessage({ type: "SAVE_SETTINGS", settings: payload });
  const status = document.getElementById("status");
  status.textContent = response?.ok ? "Settings saved." : (response?.error || "Save failed.");
  await refreshStorage();
  await refreshLogs();
}

async function refreshStorage() {
  const response = await chrome.runtime.sendMessage({ type: "GET_STORAGE_STATE" });
  document.getElementById("storageView").textContent = response?.ok
    ? JSON.stringify(response.data || {}, null, 2)
    : (response?.error || "Failed to load storage");
}

async function refreshLogs() {
  const response = await chrome.runtime.sendMessage({ type: "GET_DEBUG_LOGS" });
  document.getElementById("logsView").textContent = response?.ok
    ? JSON.stringify(response.logs || [], null, 2)
    : (response?.error || "Failed to load logs");
}

async function clearLogs() {
  const response = await chrome.runtime.sendMessage({ type: "CLEAR_DEBUG_LOGS" });
  const status = document.getElementById("status");
  status.textContent = response?.ok ? "Debug logs cleared." : (response?.error || "Failed to clear logs.");
  await refreshLogs();
  await refreshStorage();
}

document.getElementById("saveButton").addEventListener("click", saveSettings);
document.getElementById("refreshStorageButton").addEventListener("click", refreshStorage);
document.getElementById("refreshLogsButton").addEventListener("click", refreshLogs);
document.getElementById("clearLogsButton").addEventListener("click", clearLogs);
loadSettings();
