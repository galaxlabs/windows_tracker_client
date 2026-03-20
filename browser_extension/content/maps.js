(function () {
  const OVERLAY_ID = "cclms-map-overlay";
  const LEAD_LAYER_EVENT = "CCLMS_RENDER_LEAD_LAYER";
  const LEAD_LAYER_SCRIPT_ID = "cclms-lead-layer-bridge";
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
    const address = CCLMSCommon.normalizeWhitespace(addressButton?.textContent || "");
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
    const directNodes = document.querySelectorAll("[data-item-id^='oh'], button[aria-label*='Hours'], div[aria-label*='Hours']");
    directNodes.forEach((node) => {
      const text = CCLMSCommon.normalizeWhitespace(node.textContent || node.getAttribute("aria-label") || "");
      if (text) {
        candidates.push(text);
      }
    });

    const rows = Array.from(document.querySelectorAll("table tr, [role='row']"))
      .map((row) => CCLMSCommon.normalizeWhitespace(row.textContent || ""))
      .filter((text) => /monday|tuesday|wednesday|thursday|friday|saturday|sunday/i.test(text));
    candidates.push(...rows);

    const unique = [];
    const seen = new Set();
    for (const item of candidates) {
      const value = CCLMSCommon.normalizeWhitespace(item);
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

  function canCreateLead(place) {
    return Boolean(place?.business_name && place?.address && place?.zip_code);
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

    if (!place?.business_name) {
      card.className = "cclms-card cclms-card--idle";
      body.textContent = "Open a real Google Maps place panel to validate it.";
      return;
    }

    const info = validation?.message || validation || {};
    const panel = currentDecisionPanel?.message?.control_panel || info.control_panel || {};
    const panelZip = panel.zip || {};
    const panelLeadScope = panel.lead_scope || {};
    const panelAi = panel.ai || {};
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
      : `<div style="margin-top:8px;font-size:12px;opacity:0.82;">AI summary unavailable for this ZIP yet.</div>`;

    body.innerHTML = `
      <div style="display:grid;gap:10px;">
        <div>
          <div style="font-size:16px;font-weight:700;">${escapeHtml(place.business_name || place.name)}</div>
          <div style="font-size:12px;opacity:0.86;">${escapeHtml(place.address || "")}</div>
          <div style="font-size:12px;opacity:0.86;">${escapeHtml([place.city, place.state, place.zip_code].filter(Boolean).join(", "))}</div>
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
            <div style="font-size:14px;font-weight:700;">${escapeHtml(String(panelZip.zip_code || place.zip_code || ""))} ${panelZip.zone_color ? `(${escapeHtml(panelZip.zone_color)})` : ""}</div>
            <div style="font-size:11px;margin-top:4px;">Score: ${escapeHtml(String(panelZip.zip_score ?? info.zip_score ?? ""))}</div>
          </div>
        </div>
        ${zipSummaryText ? `<div style="font-size:12px;padding:8px;border-left:3px solid rgba(255,255,255,0.35);background:rgba(255,255,255,0.04);">${escapeHtml(zipSummaryText)}</div>` : ""}
        <div>
          <div style="font-size:12px;font-weight:700;opacity:0.9;">AI Summary</div>
          ${aiBlock}
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
    if (canCreateLead(place)) {
      actions.appendChild(actionButton("Create Prefilled ATM Lead", () => createPrefilledLead(place)));
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
    script.textContent = `
      (() => {
        const EVENT_NAME = ${JSON.stringify(LEAD_LAYER_EVENT)};
        let markers = [];
        let infoWindow = null;

        function clearMarkers() {
          markers.forEach((marker) => marker.setMap(null));
          markers = [];
        }

        function iconForState(workflowState) {
          const value = String(workflowState || "").toLowerCase();
          let color = "#2563eb";
          if (value.includes("approved") || value.includes("installed") || value.includes("signed") || value.includes("converted")) {
            color = "#15803d";
          } else if (value.includes("rejected") || value.includes("removed") || value.includes("cancelled")) {
            color = "#b91c1c";
          } else if (value.includes("pending") || value.includes("review")) {
            color = "#b45309";
          }
          return {
            path: google.maps.SymbolPath.CIRCLE,
            fillColor: color,
            fillOpacity: 0.9,
            strokeColor: "#ffffff",
            strokeWeight: 2,
            scale: 7
          };
        }

        function render(payload) {
          if (!window.google || !google.maps) {
            return;
          }
          const mapElement = document.querySelector("#scene, [role='main'] .widget-scene");
          const map = mapElement && mapElement.__gm ? mapElement.__gm.map : null;
          if (!map) {
            return;
          }
          clearMarkers();
          const rows = Array.isArray(payload?.leads) ? payload.leads : [];
          if (!rows.length) {
            return;
          }
          infoWindow = infoWindow || new google.maps.InfoWindow();
          rows.forEach((row) => {
            const lat = Number(row.latitude);
            const lng = Number(row.longitude);
            if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
              return;
            }
            const marker = new google.maps.Marker({
              position: { lat, lng },
              map,
              title: row.business_name || row.atm_lead_name || "ATM Lead",
              icon: iconForState(row.workflow_state)
            });
            marker.addListener("click", () => {
              const route = row.open_url || "";
              const html = [
                '<div style="min-width:220px;line-height:1.4;">',
                '<strong>' + String(row.business_name || row.atm_lead_name || "ATM Lead") + '</strong><br>',
                row.address ? String(row.address) + '<br>' : '',
                row.workflow_state ? 'State: ' + String(row.workflow_state) + '<br>' : '',
                route ? '<a href="' + route + '" target="_blank" rel="noopener">Open CRM Lead</a>' : '',
                '</div>'
              ].join('');
              infoWindow.setContent(html);
              infoWindow.open({ map, anchor: marker });
            });
            markers.push(marker);
          });
        }

        window.addEventListener(EVENT_NAME, (event) => {
          try {
            render(event.detail || {});
          } catch (error) {
          }
        });
      })();
    `;
    (document.head || document.documentElement).appendChild(script);
    script.remove();
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
    currentDecisionPanel = await fetchDecisionPanel(place);
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
    if (currentValidation?.message) {
      currentValidation.message = validationMessage;
    } else {
      currentValidation = validationMessage;
    }
    const crmBaseUrl = String(leadScope.crm_base_url || "").replace(/\/+$/, "");
    const layerPayload = {
      leads: (leadScope.leads || []).map((row) => ({
        ...row,
        open_url: crmBaseUrl ? `${crmBaseUrl}/app/atm-leads/${row.atm_lead_name}` : ""
      }))
    };
    const layerKey = JSON.stringify(layerPayload.leads.map((row) => [row.atm_lead_name, row.latitude, row.longitude, row.workflow_state]));
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
