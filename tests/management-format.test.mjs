import test from "node:test";
import assert from "node:assert/strict";
globalThis.localStorage = {getItem: () => "es"};
const {formatTimestamp, auditPresentation} = await import("../src/blaster/static/management.js");

test("programmed times retain their own timezone across seasonal offsets", () => {
  const september="2026-09-15T14:00:00Z";
  assert.match(formatTimestamp(september,"America/Mexico_City"), /8:00/);
  assert.match(formatTimestamp(september,"America/New_York"), /10:00/);
  assert.match(formatTimestamp("2026-01-15T14:00:00Z","America/New_York"), /9:00/);
});

test("audit presents an operational label and keeps the original evidence intact", () => {
  const row={action:"POST /api/manage/users/"+"a".repeat(32),target:"/api/manage/users/"+"a".repeat(32),detail:'{"fields":["role"],"status":200}'};
  const original=JSON.stringify(row);
  assert.deepEqual(auditPresentation(row), {title:"Acceso de usuario actualizado",target:"Usuario · aaaaaaaa",result:"Completado"});
  assert.equal(JSON.stringify(row),original);
  assert.equal(auditPresentation({action:"unknown.action"}).title,"Actividad registrada");
});
