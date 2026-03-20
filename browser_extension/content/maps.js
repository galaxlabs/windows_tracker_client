(function () {
  const OVERLAY_ID = "cclms-map-overlay";
  const LEAD_LAYER_EVENT = "CCLMS_RENDER_LEAD_LAYER";
  const LEAD_LAYER_SCRIPT_ID = "cclms-lead-layer-bridge";
  const BUILD_LABEL = "v0.1.3";
  let currentFingerprint = null;
  let currentValidation = null;
  let currentDecisionPanel = null;
  let observer = null;
  let lastLeadLayerKey = null;

  function findButtonByDataItem(dataItemPrefix) {
    return Array.from(document.querySelectorAll("button[data-item-id], a[data-item-id]")).find((node) =>
      (node.getAttribute("data-item-id") || "").startsWith(dataItemPrefix)
    );
  }

  function textFromSelector(selector) {
    const node = document.querySelector(selector);
    return CCLMSCommon.normalizeWhitespace(node?.textContent || "");
  }

  function extractRatingInfo() {
    const texts = Array.from(document.querySelectorAll("span, button, div"))
      .map((node) => CCLMSCommon.normalizeWhitespace(node.textContent || node.getAttribute("aria-label") || ""))
      .filter(Boolean)
      .slice(0, 300);

    let googleRating = null;
    let userRatingsTotal = null;
    for (const text of texts) {
      if (googleRating == null) {
        const ratingMatch = text.match(/\b([1-5]\.\d)\b/);
        if (ratingMatch) {
          googleRating = Number(ratingMatch[1]);
        }
      }
      if (userRatingsTotal == null) {
        const reviewsMatch = text.match(/\b([\d,]+)\s+reviews?\b/i);
        if (reviewsMatch) {
          userRatingsTotal = Number(reviewsMatch[1].replace(/,/g, ""));
        }
      }
      if (googleRating != null && userRatingsTotal != null) {
        break;
      }
    }

    return {
      google_rating: Number.isFinite(googleRating) ? googleRating : null,
      user_ratings_total: Number.isFinite(userRatingsTotal) ? userRatingsTotal : null
    };
  }

  function fullAddressCandidate(value) {
    const text = CCLMSCommon.normalizeWhitespace(value || "");
    if (!text) {
      return "";
    }
    if (/\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b/.test(text)) {
      return text;
    }
    return text;
  }

  function extractBestAddress(addressButton) {
    const candidates = [];
    const pushCandidate = (value) => {
      const text = fullAddressCandidate(value);
      if (text) {
        candidates.push(text);
      }
    };

    pushCandidate(addressButton?.textContent);
    pushCandidate(addressButton?.getAttribute("aria-label"));
    pushCandidate(addressButton?.getAttribute("data-tooltip"));
    pushCandidate(addressButton?.title);

    document.querySelectorAll("[data-item-id^='address'], button[aria-label*='Address'], div[aria-label*='Address']").forEach((node) => {
      pushCandidate(node.textContent);
      pushCandidate(node.getAttribute("aria-label"));
      pushCandidate(node.getAttribute("data-tooltip"));
      pushCandidate(node.title);
    });

    const preferred = candidates.find((item) => /\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b/.test(item));
    return preferred || candidates.sort((a, b) => b.length - a.length)[0] || "";
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
    const openingHours = extractOpeningHours();
    const ratingInfo = extractRatingInfo();
    const address = extractBestAddress(addressButton);
    const phone = CCLMSCommon.normalizeWhitespace(phoneButton?.textContent || "");
    const website = websiteButton?.getAttribute("href") || websiteButton?.textContent || "";
    const coordinates = CCLMSCommon.parseCoordinatesFromUrl(location.href);
    const locationParts = extractLocationParts(address);
    const genericMapTitle = !name || /^google maps$/i.test(name);

    const place = {
      source_url: location.href,
      source_type: "google_maps",
      name: genericMapTitle ? "" : name,
      address,
      phone,
      website: CCLMSCommon.normalizeWhitespace(website),
      category,
      opening_hours: openingHours,
      google_rating: ratingInfo.google_rating,
      user_ratings_total: ratingInfo.user_ratings_total,
      coordinates,
      zip_code: locationParts.zip_code,
      city: locationParts.city,
      state: locationParts.state,
      business_name: genericMapTitle ? "" : name,
      normalized_business_name: genericMapTitle ? "" : CCLMSCommon.normalizeBusinessName(name),
      normalized_address: CCLMSCommon.normalizeAddress(address)
    };
    place.dedup_keys = {
      business_name: place.business_name,
      normalized_business_name: place.normalized_business_name,
      address: place.address,
      normalized_address: place.normalized_address,
      zip_code: place.zip_code,
      city: place.city,
      state: place.state,
      latitude: place.coordinates?.lat || null,
      longitude: place.coordinates?.lng || null,
      phone: place.phone || "",
      website: place.website || ""
    };
    place.place_fingerprint = CCLMSCommon.fingerprint(place);
    return place;
  }

  function extractOpeningHours() {
    const candidates = [];
    const pushCandidate = (value) => {
      const text = String(value || "")
        .replace(/\u202f/g, " ")
        .replace(/\xa0/g, " ")
        .replace(/\r\n/g, "\n")
        .replace(/\r/g, "\n");
      if (text && /\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i.test(text)) {
        candidates.push(text);
      }
    };
    const directNodes = document.querySelectorAll("[data-item-id^='oh'], button[aria-label*='Hours'], div[aria-label*='Hours']");
    directNodes.forEach((node) => {
      pushCandidate(node.innerText || node.textContent || "");
      pushCandidate(node.getAttribute("aria-label") || "");
    });

    const rows = Array.from(document.querySelectorAll("table tr, [role='row']"))
      .map((row) => {
        const pieces = Array.from(row.querySelectorAll("td, th, div, span"))
          .map((node) => String(node.innerText || node.textContent || "").trim())
          .filter(Boolean);
        if (pieces.length >= 2 && /monday|tuesday|wednesday|thursday|friday|saturday|sunday/i.test(pieces[0])) {
          return `${pieces[0]}\n${pieces.slice(1).join(" ")}`;
        }
        return String(row.innerText || row.textContent || "");
      })
      .map((text) => text.replace(/\u202f/g, " ").replace(/\xa0/g, " ").replace(/\r\n/g, "\n").replace(/\r/g, "\n"))
      .filter((text) => /monday|tuesday|wednesday|thursday|friday|saturday|sunday/i.test(text));
    candidates.push(...rows);

    const unique = [];
    const seen = new Set();
    for (const item of candidates) {
      const value = item
        .split("\n")
        .map((line) => CCLMSCommon.normalizeWhitespace(line))
        .filter(Boolean)
        .join("\n");
      if (!value || seen.has(value)) {
        continue;
      }
      seen.add(value);
      unique.push(value);
    }
    return unique.join("\n");
  }

  function extractLocationParts(address) {
    const text = CCLMSCommon.normalizeWhitespace(address);
    const stateZipMatch = text.match(/\b([A-Z]{2})\s+(\d{5})(?:-\d{4})?\b/);
    const cityStateZipMatch = text.match(/,\s*([^,]+),\s*([A-Z]{2})\s+\d{5}(?:-\d{4})?/);
    return {
      zip_code: stateZipMatch ? stateZipMatch[2] : "",
      state: stateZipMatch ? stateZipMatch[1] : "",
      city: cityStateZipMatch ? CCLMSCommon.normalizeWhitespace(cityStateZipMatch[1]) : ""
    };
  }

  function canCreateLead(place, resolvedPrefill) {
    const prefill = resolvedPrefill || {};
    return Boolean(
      (prefill.business_name || place?.business_name) &&
      (prefill.address || place?.address) &&
      (prefill.zip_code || place?.zip_code)
    );
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
        <div class="cclms-title">CCLMS <span style="opacity:0.65;font-size:11px;">${BUILD_LABEL}</span></div>
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

    if (!place?.business_name) {
      card.className = "cclms-card cclms-card--idle";
      body.textContent = "Open a real Google Maps place panel to validate it.";
      return;
    }

    const info = validation?.message || validation || {};
    const panel = currentDecisionPanel?.message?.control_panel || info.control_panel || {};
    const resolvedPrefill = currentDecisionPanel?.message?.prefill || info.prefill || {};
    const panelZip = panel.zip || {};
    const panelLeadScope = panel.lead_scope || {};
    const panelAi = panel.ai || {};
    const panelMetrics = panel.metrics || {};
    const decisionCopy = panel.decision_copy || "";
    const zipSummaryText = panelZip.summary?.suggestion || "";
    const existingLeadCount = Array.isArray(info.scope_leads) ? info.scope_leads.length : 0;
    const zoneColor = (info.zone_color || info.status_color || "yellow").toLowerCase();
    card.className = `cclms-card cclms-card--${mapColor(zoneColor)}`;

    const leadRows = (panelLeadScope.leads || []).slice(0, 6).map((row) => {
      const state = [row.city, row.state, row.zip_code].filter(Boolean).join(", ");
      return `
        <div style="padding:6px 0;border-top:1px solid rgba(255,255,255,0.08);">
          <div style="font-weight:600;">${escapeHtml(row.business_name || row.atm_lead_name || "ATM Lead")}</div>
          <div style="font-size:11px;opacity:0.86;">${escapeHtml(row.address || state || "")}</div>
          <div style="font-size:11px;opacity:0.86;">${escapeHtml(row.workflow_state || "Draft")}</div>
        </div>
      `;
    }).join("");

    const aiBlock = panelAi.available && panelAi.raw_text
      ? `<div style="margin-top:8px;padding:8px;border-radius:10px;background:rgba(255,255,255,0.06);font-size:12px;line-height:1.5;white-space:pre-wrap;">${escapeHtml(panelAi.raw_text)}</div>`
      : `<div style="margin-top:8px;font-size:12px;opacity:0.82;">AI summary unavailable for this ZIP yet.${panelAi.reason ? ` (${escapeHtml(panelAi.reason)})` : ""}</div>`;

    const debugBlock = `
      <div style="margin-top:8px;padding:8px;border-radius:10px;background:rgba(255,255,255,0.05);font-size:11px;line-height:1.45;opacity:0.9;">
        <div><strong>Debug</strong></div>
        <div>Build: ${escapeHtml(BUILD_LABEL)}</div>
        <div>ZIP sent: ${escapeHtml(String(resolvedPrefill.zip_code || place.zip_code || ""))}</div>
        <div>Rating sent: ${escapeHtml(String(place.google_rating ?? "none"))}</div>
        <div>Reviews sent: ${escapeHtml(String(place.user_ratings_total ?? "none"))}</div>
        <div>AI available: ${escapeHtml(String(Boolean(panelAi.available)))}</div>
        <div>AI reason: ${escapeHtml(panelAi.reason || "none")}</div>
      </div>
    `;

    body.innerHTML = `
      <div style="display:grid;gap:10px;">
        <div>
          <div style="font-size:16px;font-weight:700;">${escapeHtml(place.business_name || place.name)}</div>
          <div style="font-size:12px;opacity:0.86;">${escapeHtml(resolvedPrefill.address || place.address || "")}</div>
          <div style="font-size:12px;opacity:0.86;">${escapeHtml([resolvedPrefill.city || place.city, resolvedPrefill.state_code || place.state, resolvedPrefill.zip_code || place.zip_code].filter(Boolean).join(", "))}</div>
          ${place.category ? `<div style="margin-top:4px;font-size:12px;">Type: ${escapeHtml(place.category)}</div>` : ""}
        </div>
        <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;">
          <div style="padding:8px;border-radius:10px;background:rgba(255,255,255,0.06);">
            <div style="font-size:11px;opacity:0.8;">Decision</div>
            <div style="font-size:14px;font-weight:700;">${escapeHtml(info.recommendation || panelZip.status || "Review")}</div>
            ${info.duplicate_reason ? `<div style="font-size:11px;margin-top:4px;">${escapeHtml(info.duplicate_reason)}</div>` : ""}
          </div>
          <div style="padding:8px;border-radius:10px;background:rgba(255,255,255,0.06);">
            <div style="font-size:11px;opacity:0.8;">ZIP</div>
            <div style="font-size:14px;font-weight:700;">${escapeHtml(String(panelZip.zip_code || resolvedPrefill.zip_code || place.zip_code || ""))} ${panelZip.zone_color ? `(${escapeHtml(panelZip.zone_color)})` : ""}</div>
            <div style="font-size:11px;margin-top:4px;">Score: ${escapeHtml(String(panelZip.zip_score ?? info.zip_score ?? ""))}</div>
          </div>
        </div>
        ${decisionCopy ? `<div style="font-size:12px;padding:8px;border-left:3px solid rgba(255,255,255,0.35);background:rgba(255,255,255,0.04);">${escapeHtml(decisionCopy)}</div>` : ""}
        <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;">
          <div style="padding:8px;border-radius:10px;background:rgba(255,255,255,0.06);">
            <div style="font-size:11px;opacity:0.8;">Nearest Bitcoin Depot</div>
            <div style="font-size:14px;font-weight:700;">${escapeHtml(panelMetrics.nearest_company_miles == null ? "No nearby record" : `${panelMetrics.nearest_company_miles} mi`)}</div>
          </div>
          <div style="padding:8px;border-radius:10px;background:rgba(255,255,255,0.06);">
            <div style="font-size:11px;opacity:0.8;">Nearest Competitor</div>
            <div style="font-size:14px;font-weight:700;">${escapeHtml(panelMetrics.nearest_competitor_miles == null ? "No nearby record" : `${panelMetrics.nearest_competitor_miles} mi`)}</div>
          </div>
        </div>
        ${zipSummaryText ? `<div style="font-size:12px;padding:8px;border-left:3px solid rgba(255,255,255,0.35);background:rgba(255,255,255,0.04);">${escapeHtml(zipSummaryText)}</div>` : ""}
        <div>
          <div style="font-size:12px;font-weight:700;opacity:0.9;">AI Summary</div>
          ${aiBlock}
          ${debugBlock}
        </div>
        <div>
          <div style="font-size:12px;font-weight:700;opacity:0.9;">Existing ATM Leads In Scope (${escapeHtml(String(panelLeadScope.count || existingLeadCount || 0))})</div>
          ${leadRows || `<div style="font-size:12px;opacity:0.82;margin-top:6px;">No existing ATM Leads found in this ZIP scope.</div>`}
        </div>
      </div>
    `;

    if (info.open_existing_lead_url) {
      actions.appendChild(actionButton("Open Existing Lead", () => openUrl(info.open_existing_lead_url)));
    }
    if (canCreateLead(place, resolvedPrefill) && !info.exists_in_atm_leads) {
      let leadLabel = "Create Smart Lead Draft";
      const zone = String(panelZip.zone_color || info.zone_color || "").toLowerCase();
      const status = String(info.status || panelZip.status || "").toLowerCase();
      const meetsDistance = panelMetrics.meets_distance_rule !== false;
      if ((zone === "green" || zone === "light green" || zone === "light_green" || zone === "yellow") && meetsDistance) {
        leadLabel = "Create Smart ATM Lead";
      } else if (status === "avoid" || zone === "red") {
        leadLabel = "Create Review Lead Draft";
      }
      actions.appendChild(actionButton(leadLabel, () => createPrefilledLead(place)));
    }
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
      logContentEvent("prefill_lead_error", {
        error: response?.error || "unknown",
        name: place.business_name || place.name || "",
        zip_code: place.zip_code || ""
      });
      renderOverlay(place, currentValidation, response?.error || "Failed to prefill ATM lead");
      return;
    }
    const data = response.data?.message || response.data || {};
    const openUrlValue = data.open_url || data.route || response.data?.open_url || response.data?.route;
    if (data.warning) {
      renderOverlay(place, currentValidation, data.warning);
      return;
    }
    if (openUrlValue) {
      await openUrl(openUrlValue);
      return;
    }
    logContentEvent("prefill_lead_error", {
      error: "Backend did not return open_url for ATM Lead prefill",
      name: place.business_name || place.name || "",
      zip_code: place.zip_code || ""
    });
    renderOverlay(place, currentValidation, "CRM did not return a valid ATM Lead creation URL.");
  }

  async function saveCompetitor(place) {
    const response = await sendMessage({ type: "SAVE_COMPETITOR", place });
    if (!response?.ok) {
      logContentEvent("save_competitor_error", {
        error: response?.error || "unknown",
        name: place.business_name || place.name || "",
        zip_code: place.zip_code || ""
      });
      renderOverlay(place, currentValidation, response?.error || "Failed to save competitor");
      return;
    }
    await validateCurrentPlace(true);
  }

  async function fetchLeadScope(place) {
    const response = await sendMessage({ type: "GET_LEAD_SCOPE", place });
    if (!response?.ok) {
      return { leads: [], crm_base_url: "" };
    }
    const data = response.data?.message || response.data || {};
    return {
      leads: Array.isArray(data.leads) ? data.leads : [],
      crm_base_url: data.crm_base_url || response.data?.crm_base_url || ""
    };
  }

  async function fetchCompetitorScope(place) {
    const response = await sendMessage({ type: "GET_COMPETITOR_SCOPE", place });
    if (!response?.ok) {
      return { competitors: [] };
    }
    const data = response.data?.message || response.data || {};
    return {
      competitors: Array.isArray(data.competitors) ? data.competitors : []
    };
  }

  async function fetchDecisionPanel(place) {
    const response = await sendMessage({ type: "GET_DECISION_PANEL", place });
    if (!response?.ok) {
      return null;
    }
    return response.data || null;
  }

  function ensureLeadLayerBridge() {
    if (document.getElementById(LEAD_LAYER_SCRIPT_ID)) {
      return;
    }
    const script = document.createElement("script");
    script.id = LEAD_LAYER_SCRIPT_ID;
    script.src = chrome.runtime.getURL("content/lead_layer_bridge.js");
    (document.head || document.documentElement).appendChild(script);
    script.addEventListener("load", () => script.remove(), { once: true });
  }

  function renderLeadLayer(payload) {
    ensureLeadLayerBridge();
    window.dispatchEvent(new CustomEvent(LEAD_LAYER_EVENT, { detail: payload || {} }));
  }

  async function validateCurrentPlace(forceRefresh) {
    const place = extractPlace();
    if (!place.business_name || !place.address) {
      renderOverlay(place, null, null);
      return;
    }
    const fingerprint = place.place_fingerprint;
    if (!forceRefresh && fingerprint === currentFingerprint) {
      return;
    }
    currentFingerprint = fingerprint;
    currentDecisionPanel = null;
    renderOverlay(place, null, null);
    const leadScope = await fetchLeadScope(place);
    const competitorScope = await fetchCompetitorScope(place);
    const response = await sendMessage({ type: "VALIDATE_PLACE", place });
    if (!response?.ok) {
      logContentEvent("validate_place_error", {
        error: response?.error || "unknown",
        fingerprint,
        name: place.business_name || place.name || "",
        zip_code: place.zip_code || "",
        city: place.city || "",
        state: place.state || ""
      });
      renderOverlay(place, null, response?.error || "Validation failed");
      return;
    }
    currentValidation = response.data;
    const validationMessage = currentValidation?.message || currentValidation || {};
    validationMessage.scope_leads = leadScope.leads || [];
    validationMessage.competitor_scope = competitorScope.competitors || [];
    const needsDecisionFallback = !validationMessage.control_panel || !validationMessage.prefill || !(validationMessage.prefill.zip_code || place.zip_code);
    if (needsDecisionFallback) {
      const fallbackPanel = await fetchDecisionPanel(place);
      if (fallbackPanel?.message?.control_panel || fallbackPanel?.message?.prefill) {
        currentDecisionPanel = fallbackPanel;
        if (!validationMessage.control_panel && fallbackPanel.message.control_panel) {
          validationMessage.control_panel = fallbackPanel.message.control_panel;
        }
        if (!validationMessage.prefill && fallbackPanel.message.prefill) {
          validationMessage.prefill = fallbackPanel.message.prefill;
        }
      }
    }
    if (currentValidation?.message) {
      currentValidation.message = validationMessage;
    } else {
      currentValidation = validationMessage;
    }
    if (!currentDecisionPanel) {
      currentDecisionPanel = {
        message: {
          prefill: validationMessage.prefill || {},
          control_panel: validationMessage.control_panel || {}
        }
      };
    }
    const crmBaseUrl = String(leadScope.crm_base_url || "").replace(/\/+$/, "");
    const layerPayload = {
      leads: (leadScope.leads || []).map((row) => ({
        ...row,
        open_url: crmBaseUrl ? `${crmBaseUrl}/app/atm-leads/${row.atm_lead_name}` : ""
      })),
      competitors: competitorScope.competitors || []
    };
    const layerKey = JSON.stringify({
      leads: layerPayload.leads.map((row) => [row.atm_lead_name, row.latitude, row.longitude, row.workflow_state]),
      competitors: layerPayload.competitors.map((row) => [row.crm_competitor_kiosk_name || row.name, row.latitude, row.longitude])
    });
    if (forceRefresh || layerKey !== lastLeadLayerKey) {
      renderLeadLayer(layerPayload);
      lastLeadLayerKey = layerKey;
    }
    logContentEvent("validate_place_success", {
      fingerprint,
      name: place.business_name || place.name || "",
      zip_code: place.zip_code || "",
      city: place.city || "",
      state: place.state || ""
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
  ensureLeadLayerBridge();
  validateCurrentPlace(false);
})();
