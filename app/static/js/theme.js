/**
 * InterviewQ Theme Manager
 * Handles dark/light theme switching with localStorage persistence
 */
const ThemeManager = {
  STORAGE_KEY: 'interviewq-theme',
  DARK_CLASS: 'dark',

  init() {
    // Load saved theme or default to light
    const savedTheme = localStorage.getItem(this.STORAGE_KEY);
    if (savedTheme === 'dark') {
      this.enableDark();
    } else {
      this.enableLight();
    }
    // Update toggle button state
    this.updateToggle();
  },

  toggle() {
    if (this.isDark()) {
      this.enableLight();
    } else {
      this.enableDark();
    }
    localStorage.setItem(this.STORAGE_KEY, this.isDark() ? 'dark' : 'light');
    this.updateToggle();
  },

  isDark() {
    return document.documentElement.classList.contains(this.DARK_CLASS);
  },

  enableDark() {
    document.documentElement.classList.add(this.DARK_CLASS);
  },

  enableLight() {
    document.documentElement.classList.remove(this.DARK_CLASS);
  },

  updateToggle() {
    const toggleBtn = document.getElementById('theme-toggle');
    if (toggleBtn) {
      const sunIcon = toggleBtn.querySelector('.sun-icon');
      const moonIcon = toggleBtn.querySelector('.moon-icon');
      if (this.isDark()) {
        sunIcon?.classList.add('hidden');
        moonIcon?.classList.remove('hidden');
      } else {
        sunIcon?.classList.remove('hidden');
        moonIcon?.classList.add('hidden');
      }
    }
  }
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => ThemeManager.init());
