(function () {
  const PANEL_ID = "cclms-chat-panel";
  let lastIds = new Set();

  function ensurePanel() {
    let panel = document.getElementById(PANEL_ID);
    if (panel) {
      return panel;
    }
    panel = document.createElement("div");
    panel.id = PANEL_ID;
    panel.className = "cclms-chat-panel";
    panel.innerHTML = `
      <div class="cclms-title">CCLMS Notices</div>
      <div class="cclms-chat-body">No active CRM reminders.</div>
    `;
    document.body.appendChild(panel);
    return panel;
  }

  function renderNotifications(items) {
    const panel = ensurePanel();
    const body = panel.querySelector(".cclms-chat-body");
    if (!items.length) {
      body.textContent = "No active CRM reminders.";
      return;
    }
    body.innerHTML = items
      .map((item) => `<div class="cclms-chat-item"><strong>${escapeHtml(item.title || "Reminder")}</strong><br>${escapeHtml(item.message || "")}</div>`)
      .join("");
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function pollNotifications() {
    const response = await chrome.runtime.sendMessage({
      type: "GET_BROWSER_NOTIFICATIONS",
      pageContext: {
        source: "google_chat",
        url: location.href,
        title: document.title
      }
    });
    if (!response?.ok) {
      return;
    }
    const items = response.data?.message || response.data || [];
    renderNotifications(items);
    for (const item of items) {
      if (!item.notification_id || lastIds.has(item.notification_id)) {
        continue;
      }
      lastIds.add(item.notification_id);
      chrome.runtime.sendMessage({
        type: "ACK_BROWSER_NOTIFICATION",
        notificationId: item.notification_id
      });
    }
  }

  setInterval(pollNotifications, 120000);
  pollNotifications();
})();
