(() => {
  const EVENT_NAME = "CCLMS_RENDER_LEAD_LAYER";
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
        ].join("");
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
