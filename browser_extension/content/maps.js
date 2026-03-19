(function () {
  const OVERLAY_ID = "cclms-map-overlay";
  let currentFingerprint = null;
  let currentValidation = null;
  let observer = null;

  function findButtonByDataItem(dataItemPrefix) {
    return Array.from(document.querySelectorAll("button[data-item-id], a[data-item-id]")).find((node) =>
      (node.getAttribute("data-item-id") || "").startsWith(dataItemPrefix)
    );
  }

  function textFromSelector(selector) {
    const node = document.querySelector(selector);
    return CCLMSCommon.normalizeWhitespace(node?.textContent || "");
  }

  function extractPlace() {
    const name =
      textFromSelector("h1.DUwDvf") ||
      textFromSelector("h1") ||
      document.title.replace(/\s*-\s*Google Maps.*$/, "").trim();
    const addressButton = findButtonByDataItem("address");
    const phoneButton = findButtonByDataItem("phone");
    const websiteButton = findButtonByDataItem("authority");
    const category = textFromSelector("button[jsaction*='pane.rating.category']");
    const address = CCLMSCommon.normalizeWhitespace(addressButton?.textContent || "");
    const phone = CCLMSCommon.normalizeWhitespace(phoneButton?.textContent || "");
    const website = websiteButton?.getAttribute("href") || websiteButton?.textContent || "";
    const coordinates = CCLMSCommon.parseCoordinatesFromUrl(location.href);

    const place = {
      source_url: location.href,
      source_type: "google_maps",
      name,
      address,
      phone,
      website: CCLMSCommon.normalizeWhitespace(website),
      category,
      coordinates,
      zip_code: extractZip(address),
      city: "",
      state: extractState(address)
    };
    place.place_fingerprint = CCLMSCommon.fingerprint(place);
    return place;
  }

  function extractZip(address) {
    const match = (address || "").match(/\b(\d{5})(?:-\d{4})?\b/);
    return match ? match[1] : "";
  }

  function extractState(address) {
    const match = (address || "").match(/\b([A-Z]{2})\s+\d{5}(?:-\d{4})?\b/);
    return match ? match[1] : "";
  }

  function ensureOverlay() {
    let root = document.getElementById(OVERLAY_ID);
    if (root) {
      return root;
    }
    root = document.createElement("div");
    root.id = OVERLAY_ID;
    root.innerHTML = `
      <div class="cclms-card cclms-card--idle">
        <div class="cclms-title">CCLMS</div>
        <div class="cclms-body">Waiting for a Google Maps place...</div>
        <div class="cclms-actions"></div>
      </div>
    `;
    document.body.appendChild(root);
    return root;
  }

  function renderOverlay(place, validation, error) {
    const root = ensureOverlay();
    const card = root.querySelector(".cclms-card");
    const body = root.querySelector(".cclms-body");
    const actions = root.querySelector(".cclms-actions");
    actions.innerHTML = "";

    if (error) {
      card.className = "cclms-card cclms-card--red";
      body.innerHTML = `<strong>CRM error</strong><br>${escapeHtml(error)}`;
      return;
    }

    if (!place?.name) {
      card.className = "cclms-card cclms-card--idle";
      body.textContent = "Waiting for a Google Maps place...";
      return;
    }

    const info = validation?.message || validation || {};
    const zoneColor = (info.zone_color || info.status_color || "yellow").toLowerCase();
    card.className = `cclms-card cclms-card--${mapColor(zoneColor)}`;

    const lines = [
      `<strong>${escapeHtml(place.name)}</strong>`,
      place.address ? escapeHtml(place.address) : "",
      info.exists_in_atm_leads ? `Already exists: ${escapeHtml(info.workflow_state || "Existing")}` : "",
      info.zip_score !== undefined ? `ZIP score: ${escapeHtml(String(info.zip_score))}` : "",
      info.competitor_count !== undefined ? `Competitors: ${escapeHtml(String(info.competitor_count))}` : "",
      info.recommendation ? `Action: ${escapeHtml(info.recommendation)}` : ""
    ].filter(Boolean);
    body.innerHTML = lines.join("<br>");

    if (info.open_existing_lead_url) {
      actions.appendChild(actionButton("Open Existing Lead", () => openUrl(info.open_existing_lead_url)));
    }
    actions.appendChild(actionButton("Create Prefilled ATM Lead", () => createPrefilledLead(place)));
    actions.appendChild(actionButton("Save Competitor", () => saveCompetitor(place)));
    actions.appendChild(actionButton("Refresh Validation", () => validateCurrentPlace(true)));
  }

  function mapColor(value) {
    if (value === "green") {
      return "green";
    }
    if (value === "light-green" || value === "light_green") {
      return "light-green";
    }
    if (value === "red") {
      return "red";
    }
    return "yellow";
  }

  function actionButton(label, handler) {
    const button = document.createElement("button");
    button.className = "cclms-action";
    button.textContent = label;
    button.addEventListener("click", handler);
    return button;
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function sendMessage(message) {
    return chrome.runtime.sendMessage(message);
  }

  async function logContentEvent(event, details) {
    try {
      await sendMessage({
        type: "LOG_EVENT",
        scope: "maps_content",
        event,
        details: details || {}
      });
    } catch (error) {
    }
  }

  async function openUrl(url) {
    await sendMessage({ type: "OPEN_URL", url });
  }

  async function createPrefilledLead(place) {
    const response = await sendMessage({ type: "PREFILL_LEAD", place });
    if (!response?.ok) {
      logContentEvent("prefill_lead_error", { error: response?.error || "unknown" });
      renderOverlay(place, currentValidation, response?.error || "Failed to prefill ATM lead");
      return;
    }
    const data = response.data?.message || response.data || {};
    if (data.warning) {
      renderOverlay(place, currentValidation, data.warning);
      return;
    }
    if (data.open_url) {
      await openUrl(data.open_url);
      return;
    }
    const query = new URLSearchParams({
      business_name: place.name || "",
      address: place.address || "",
      zip_code: place.zip_code || "",
      state: place.state || "",
      phone: place.phone || "",
      website: place.website || "",
      latitude: place.coordinates?.lat || "",
      longitude: place.coordinates?.lng || "",
      source: "Google Maps"
    });
    await openUrl(`${data.crm_base_url || ""}/app/atm-lead/new-atm-lead-1?${query.toString()}`);
  }

  async function saveCompetitor(place) {
    const response = await sendMessage({ type: "SAVE_COMPETITOR", place });
    if (!response?.ok) {
      logContentEvent("save_competitor_error", { error: response?.error || "unknown" });
      renderOverlay(place, currentValidation, response?.error || "Failed to save competitor");
      return;
    }
    await validateCurrentPlace(true);
  }

  async function validateCurrentPlace(forceRefresh) {
    const place = extractPlace();
    if (!place.name || !place.address) {
      renderOverlay(place, null, null);
      return;
    }
    const fingerprint = place.place_fingerprint;
    if (!forceRefresh && fingerprint === currentFingerprint) {
      return;
    }
    currentFingerprint = fingerprint;
    renderOverlay(place, null, null);
    const response = await sendMessage({ type: "VALIDATE_PLACE", place });
    if (!response?.ok) {
      logContentEvent("validate_place_error", {
        error: response?.error || "unknown",
        fingerprint
      });
      renderOverlay(place, null, response?.error || "Validation failed");
      return;
    }
    currentValidation = response.data;
    logContentEvent("validate_place_success", {
      fingerprint,
      name: place.name || ""
    });
    renderOverlay(place, currentValidation, null);
  }

  const debouncedValidate = CCLMSCommon.debounce(() => validateCurrentPlace(false), 1200);

  function startObservers() {
    if (observer) {
      observer.disconnect();
    }
    observer = new MutationObserver(() => debouncedValidate());
    observer.observe(document.body, { childList: true, subtree: true, characterData: false });
    window.addEventListener("popstate", debouncedValidate);
    window.addEventListener("hashchange", debouncedValidate);
  }

  startObservers();
  validateCurrentPlace(false);
})();
