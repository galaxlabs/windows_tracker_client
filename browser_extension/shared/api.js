const CCLMSApi = {
  async post(settings, method, payload) {
    const baseUrl = (settings.crmBaseUrl || "").replace(/\/+$/, "");
    if (!baseUrl) {
      throw new Error("CRM base URL is missing");
    }
    const response = await fetch(`${baseUrl}/api/method/${method}`, {
      method: "POST",
      headers: this._headers(settings),
      credentials: settings.authMode === "cookie" ? "include" : "omit",
      body: JSON.stringify(payload || {})
    });
    const text = await response.text();
    if (!response.ok) {
      throw new Error(`HTTP ${response.status} from ${method}: ${text.slice(0, 500)}`);
    }
    return text ? JSON.parse(text) : {};
  },

  _headers(settings) {
    const headers = {
      "Content-Type": "application/json",
      "Accept": "application/json"
    };
    if (settings.authMode === "token" && settings.apiToken) {
      headers["Authorization"] = `token ${settings.apiToken}`;
    }
    return headers;
  }
};
