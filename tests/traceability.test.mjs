import assert from "node:assert/strict";
import test from "node:test";

import {traceIdentifier} from "../src/blaster/static/traceability.js";

test("credit identifiers preserve their exact significant content", () => {
  assert.deepEqual(traceIdentifier("credit", "  CRED-001/A  "), {
    by: "credit", query: "CRED-001/A",
  });
});

test("telephone identifiers use the same harmless visual cleanup as dialing", () => {
  assert.deepEqual(traceIdentifier("phone", " +52 (55) 1234-5678 "), {
    by: "phone", query: "525512345678",
  });
});
