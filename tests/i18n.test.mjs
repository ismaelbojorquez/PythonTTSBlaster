import assert from "node:assert/strict";
import test from "node:test";

globalThis.localStorage = {getItem: () => "en"};
const {getLanguage, locale, t, translateText} = await import("../src/blaster/static/i18n.js");

test("English selection translates fixed and dynamic interface text", () => {
  assert.equal(getLanguage(), "en");
  assert.equal(locale(), "en-US");
  assert.equal(t("Nueva campaña"), "New campaign");
  assert.equal(translateText("12 contactos"), "12 contacts");
  assert.equal(
    translateText("Disponibilidad de agentes · 2 de 4 libres · 1 en espera"),
    "Agent availability · 2 of 4 available · 1 waiting",
  );
});
