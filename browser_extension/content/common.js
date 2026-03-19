(function () {
  window.CCLMSCommon = {
    debounce(fn, delay) {
      let timer = null;
      return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
      };
    },

    normalizeWhitespace(value) {
      return (value || "").replace(/\s+/g, " ").trim();
    },

    fingerprint(place) {
      const fields = [
        place.name || "",
        place.address || "",
        place.coordinates?.lat || "",
        place.coordinates?.lng || ""
      ];
      return fields.join("|").toLowerCase();
    },

    parseCoordinatesFromUrl(urlString) {
      const url = new URL(urlString);
      const direct = url.href.match(/@(-?\d+\.\d+),(-?\d+\.\d+)/);
      if (direct) {
        return { lat: Number(direct[1]), lng: Number(direct[2]) };
      }
      const query = url.searchParams.get("q") || "";
      const qMatch = query.match(/(-?\d+\.\d+),\s*(-?\d+\.\d+)/);
      if (qMatch) {
        return { lat: Number(qMatch[1]), lng: Number(qMatch[2]) };
      }
      return null;
    }
  };
})();
