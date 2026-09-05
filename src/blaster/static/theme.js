"use strict";

(function initializeTheme() {
  const STORAGE_KEY = "blaster.theme";
  const DARK = "dark";
  const LIGHT = "light";
  const media = window.matchMedia("(prefers-color-scheme: dark)");

  function storedTheme() {
    try {
      const value = localStorage.getItem(STORAGE_KEY);
      return value === DARK || value === LIGHT ? value : null;
    } catch {
      return null;
    }
  }

  function systemTheme() {
    return media.matches ? DARK : LIGHT;
  }

  function currentTheme() {
    return document.documentElement.dataset.theme || storedTheme() || systemTheme();
  }

  function wording(theme) {
    const english = document.documentElement.lang === "en";
    if (theme === DARK) {
      return english
        ? {short: "Light", action: "Enable light mode"}
        : {short: "Claro", action: "Activar modo claro"};
    }
    return english
      ? {short: "Dark", action: "Enable dark mode"}
      : {short: "Oscuro", action: "Activar modo oscuro"};
  }

  function updateControls(theme) {
    const copy = wording(theme);
    for (const button of document.querySelectorAll("[data-theme-toggle]")) {
      button.dataset.currentTheme = theme;
      button.setAttribute("aria-pressed", String(theme === DARK));
      button.setAttribute("aria-label", copy.action);
      button.setAttribute("title", copy.action);
      const label = button.querySelector(".theme-label");
      if (label) label.textContent = copy.short;
    }
  }

  function applyTheme(theme, options = {}) {
    const next = theme === DARK ? DARK : LIGHT;
    document.documentElement.dataset.theme = next;
    document.documentElement.style.colorScheme = next;
    const color = next === DARK ? "#121210" : "#171714";
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", color);
    if (options.remember) {
      try { localStorage.setItem(STORAGE_KEY, next); } catch {}
    }
    updateControls(next);
    if (options.announce) {
      window.dispatchEvent(new CustomEvent("blaster:theme-change", {detail: {theme: next}}));
    }
    return next;
  }

  function toggleTheme() {
    return applyTheme(currentTheme() === DARK ? LIGHT : DARK, {remember: true, announce: true});
  }

  applyTheme(storedTheme() || systemTheme());
  window.blasterTheme = {applyTheme, currentTheme, toggleTheme};

  document.addEventListener("DOMContentLoaded", () => {
    updateControls(currentTheme());
    document.addEventListener("click", event => {
      const button = event.target.closest("[data-theme-toggle]");
      if (button) toggleTheme();
    });
  });

  media.addEventListener?.("change", event => {
    if (!storedTheme()) applyTheme(event.matches ? DARK : LIGHT, {announce: true});
  });
})();
