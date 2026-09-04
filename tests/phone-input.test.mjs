import assert from "node:assert/strict";
import test from "node:test";
import { cleanPhoneInput, removeCsvPhonePlus, removePhonePlus } from "../src/blaster/static/phone-input.js";

test("pasted numbers lose plus signs, keeping the other characters for validation", () => {
  assert.equal(removePhonePlus("+52 (55) 1234-5678"), "52 (55) 1234-5678");
  assert.equal(removePhonePlus("52123abc"), "52123abc");
});

test("CSV cleanup handles BOM, reordered columns, quotes and multiline variables", () => {
  const csv = '\uFEFFnombre,"telefono",nota\r\n"Ana + Luis","+525512345678","A + B, ""sí""\n+ mañana"\r\nLuis,+525512345679,C++';
  assert.equal(removeCsvPhonePlus(csv), csv.replace("+525512345678", "525512345678").replace("+525512345679", "525512345679"));
  assert.equal(removeCsvPhonePlus("telefono,nombre\n+52,Ana + Luis"), "telefono,nombre\n52,Ana + Luis");
  assert.equal(removeCsvPhonePlus("nombre\nAna + Luis"), "nombre\nAna + Luis");
});

test("typing a plus removes it without moving the caret to the end", () => {
  const field = {
    value: "52+5512345678", selectionStart: 3, selectionEnd: 3, selectionDirection: "none",
    setSelectionRange(...selection) { this.selection = selection; },
  };
  cleanPhoneInput(field, removePhonePlus);
  assert.equal(field.value, "525512345678");
  assert.deepEqual(field.selection, [2, 2, "none"]);
});

test("CSV selection stays on the same text after removing phone prefixes", () => {
  const value = 'telefono,nombre\n+525512345678,Ana + Luis\n+525512345679,Eva';
  const field = {
    value, selectionStart: value.indexOf("Eva"), selectionEnd: value.length, selectionDirection: "backward",
    setSelectionRange(...selection) { this.selection = selection; },
  };
  cleanPhoneInput(field, removeCsvPhonePlus);
  assert.equal(field.value.slice(field.selection[0], field.selection[1]), "Eva");
  assert.equal(field.selection[2], "backward");
});
