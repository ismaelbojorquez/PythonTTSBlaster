import assert from "node:assert/strict";
import test from "node:test";
import {readRetryPolicy, retryDescription} from "../src/blaster/static/campaign-retries.js";

test("disabling retries permits saving even after an invalid wait was entered", () => {
  const values = {attempts:"1", delay:"", unit:"3600"};
  const root = {
    querySelector(selector) { return {value:values[selector.match(/="(\w+)"/)[1]]}; },
    querySelectorAll() { return []; },
  };
  assert.deepEqual(readRetryPolicy(root), {max_attempts:1, delay_seconds:300, outcomes:[]});
  assert.match(retryDescription(readRetryPolicy(root)), /sin reintentos/);
  values.attempts = "3"; values.delay = "2";
  assert.equal(readRetryPolicy(root).delay_seconds, 7200);
  assert.equal(retryDescription(readRetryPolicy(root)), "Hasta 3 llamadas por contacto · 2 h entre intentos");
});
