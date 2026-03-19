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
}

document.getElementById("saveButton").addEventListener("click", saveSettings);
loadSettings();
