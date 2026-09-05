import assert from "node:assert/strict";
import test from "node:test";

const values = new Map();
globalThis.localStorage = {
  getItem: key => values.get(key) ?? null,
  setItem: (key, value) => values.set(key, value),
};

const label = {textContent: ""};
const attributes = new Map();
const button = {
  dataset: {},
  setAttribute: (name, value) => attributes.set(name, value),
  querySelector: selector => selector === ".theme-label" ? label : null,
};
const meta = {setAttribute: (name, value) => attributes.set(`meta:${name}`, value)};
const root = {dataset: {}, style: {}, lang: "es"};
globalThis.document = {
  documentElement: root,
  querySelectorAll: selector => selector === "[data-theme-toggle]" ? [button] : [],
  querySelector: selector => selector === 'meta[name="theme-color"]' ? meta : null,
  addEventListener() {},
};
globalThis.window = new EventTarget();
window.matchMedia = () => ({matches: false, addEventListener() {}});
if (!globalThis.CustomEvent) {
  globalThis.CustomEvent = class CustomEvent extends Event {
    constructor(type, options = {}) { super(type); this.detail = options.detail; }
  };
}

await import("../src/blaster/static/theme.js");

test("theme follows the system initially and remembers an explicit choice", () => {
  assert.equal(window.blasterTheme.currentTheme(), "light");
  assert.equal(label.textContent, "Oscuro");
  assert.equal(attributes.get("aria-label"), "Activar modo oscuro");

  window.blasterTheme.toggleTheme();
  assert.equal(root.dataset.theme, "dark");
  assert.equal(localStorage.getItem("blaster.theme"), "dark");
  assert.equal(label.textContent, "Claro");
  assert.equal(attributes.get("aria-label"), "Activar modo claro");
  assert.equal(attributes.get("meta:content"), "#121210");
});

test("theme controls use the current platform language", () => {
  root.lang = "en";
  window.blasterTheme.applyTheme("light");
  assert.equal(label.textContent, "Dark");
  assert.equal(attributes.get("aria-label"), "Enable dark mode");
  assert.equal(attributes.get("meta:content"), "#171714");
});
