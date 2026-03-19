const CCLMSStorage = {
  async getSettings(defaults) {
    const values = await chrome.storage.local.get(defaults);
    return Object.assign({}, defaults, values);
  },

  async saveSettings(settings) {
    await chrome.storage.local.set(settings || {});
  },

  async getValue(key, fallback) {
    const result = await chrome.storage.local.get({ [key]: fallback });
    return result[key];
  },

  async setValue(key, value) {
    await chrome.storage.local.set({ [key]: value });
  }
};
