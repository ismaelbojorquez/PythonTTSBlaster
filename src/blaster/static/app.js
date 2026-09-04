"use strict";

import { cleanPhoneInput, removeCsvPhonePlus, removePhonePlus } from "./phone-input.js";
import { analyticsAction, analyticsRefresh, analyticsView, installAnalytics } from "./analytics.js";
import { installAudioPreview, clearAudioPreview } from "./audio-preview.js";
import { installCountryFields, countryLabel } from "./countries.js";
import { installAgentPool, renderAgentPool } from "./agent-pool.js";
import { installContactImport } from "./contact-import.js";
import { installCampaignExecution, updateExecutionStatus, validCampaignForm, scheduleDescription } from "./campaign-execution.js";
import { installCampaignHistory, renderCampaignHistory, refreshCampaignHistory, campaignHistoryAction } from "./campaign-history.js";
import { installCampaignRetries, renderCampaignRetries, readRetryPolicy, retryDate } from "./campaign-retries.js";
import { recordingMarkup, stopRecordings, installRecordingPlayback } from "./recording-player.js";
import { installTraceability, traceabilityAction } from "./traceability.js";

import { installManagement, managementAction, bootSession, loadTemplates, expireSession, applyRole } from "./management.js";

const $ = (selector) => document.querySelector(selector);
const state = { campaigns: [], current: null, selected: null, selectedContact: null, jobs: [], status: null, view: "dashboard", user: null, offset: 0, busy: false };
const labels = { draft: "Borrador", running: "En curso", paused: "Pausada", stopped: "Detenida", queued: "Pendiente", dialing: "Marcando", synthesizing: "Generando voz", detecting: "Detectando voz", machine: "Buzón probable", amd_unknown: "AMD incierto", playing: "Mensaje", menu: "Espera de opción", agent_dialing: "Llamando al agente", agent_waiting: "Esperando agente libre", bridged: "Con agente", completed: "Finalizada", failed: "Fallida", temporary_error: "Fallo temporal de la troncal", busy: "Ocupado", no_answer: "Sin respuesta", cancelled: "Cancelada", interrupted: "Interrumpida", no_input: "Sin selección" };
labels.scheduled = "Programada";
const terminal = new Set(["completed", "failed", "temporary_error", "busy", "no_answer", "cancelled", "interrupted", "no_input", "machine", "amd_unknown"]);
const demo = { name: "Demostración · Recordatorios", agent_number: "525550009999", template: "Hola {nombre}. Te recordamos tu cita del {fecha}. Tu folio es {folio}. Gracias por confirmar tu asistencia.", csv_text: "Credito,Telefono,nombre,fecha,folio\nDEMO-101,525550000101,Ana Martínez,viernes 12 de septiembre,A 102\nDEMO-102,525550000102,Carlos López,lunes 15 de septiembre,B 208\nDEMO-103,525550000103,Lucía Torres,martes 16 de septiembre,C 315\nDEMO-104,525550000104,Miguel Reyes,miércoles 17 de septiembre,D 420\nDEMO-105,525550000105,Sofía Ramírez,jueves 18 de septiembre,E 531" };

function escapeHTML(value) { return String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]); }
function badge(value) { return `<span class="badge ${escapeHTML(value)}">${escapeHTML(labels[value] || value)}</span>`; }
function notice(message = "") { $("#notice").hidden = !message; $("#notice").textContent = message; }
function setHTML(element, html) {
  if (element._rendered === html) return;
  const active = document.activeElement;
  const identity = element.contains(active) && active.dataset ? { ...active.dataset } : null;
  element.innerHTML = html;
  element._rendered = html;
  if (identity?.action) {
    const target = [...element.querySelectorAll("button")].find(el => el.dataset.action === identity.action && el.dataset.id === identity.id);
    target?.focus({ preventScroll: true });
  }
}
async function api(path, payload) {
  const response = await fetch(path, payload === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  if (response.status === 401 && !path.startsWith("/api/auth/")) expireSession();
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const message = Array.isArray(data.detail) ? data.detail.map(e => e.msg).join(". ") : data.detail;
    throw new Error(message || "No se pudo completar la operación. Intenta de nuevo.");
  }
  return response.json();
}
function view(name) {
  stopRecordings();
  if(name !== "editor") clearAudioPreview();
  state.view = name;
  for (const id of ["dashboard", "campaigns", "calls", "traceability", "reports", "empty", "editor", "campaign", "operations"]) $(`#${id}-view`).hidden = id !== name;
  analyticsView(name);
}
function formData() {
  cleanPhoneInput($("#agent-number"), removePhonePlus);
  cleanPhoneInput($("#contacts"), removeCsvPhonePlus);
  return {...Object.fromEntries(new FormData($("#campaign-form"))), retry_policy:readRetryPolicy($("#creator-retries"))};
}
function renderStatus() {
  const s = state.status;
  if (!s) return;
  updateExecutionStatus(s);
  $("#connection-state").textContent = s.trunk_status;
  $("#live-count").textContent = `${s.active_sessions} en curso`;
  const mode = $("#mode-badge");
  mode.textContent = s.mode === "simulation" ? "Simulación" : "SIP real";
  mode.className = `badge ${s.mode === "simulation" ? "simulation" : "live"}`;
  setHTML($("#active-count"), `${s.active_sessions} <span>/ ${s.concurrency}</span>`);
  setHTML($("#channel-count"), `${s.channels_in_use} <span>/ ${s.trunk_channels}</span>`);
  $("#concurrency").max = Math.min(30, Math.floor(s.trunk_channels / 2));
  if (document.activeElement !== $("#concurrency")) $("#concurrency").value = s.concurrency;
  $("#demo-button").hidden = s.mode !== "simulation";
  $("#simulation-note").hidden = s.mode !== "simulation";
  $("#amd-note").hidden = !s.amd_enabled;
  $("#amd-note").textContent = s.amd_enabled
    ? `Detección de buzón activa. ${s.amd_unknown_action === "hangup" ? "Se cuelga si se detecta buzón o el resultado es incierto." : "Se cuelga ante buzón; los resultados inciertos continúan."}${s.mode === "simulation" ? " En simulación se usa un saludo artificial." : ""}`
    : "";
}
function renderCampaigns() {
  $("#campaign-count").textContent = state.campaigns.length;
  const html = state.campaigns.map(c => `<button class="campaign-nav ${c.id === state.current && state.view === "campaign" ? "active" : ""}" data-action="select-campaign" data-id="${c.id}" ${c.id === state.current && state.view === "campaign" ? 'aria-current="page"' : ""}>${escapeHTML(c.name)}<span class="nav-meta">${c.total} contactos · Ejecución ${c.lineage?.execution_number || 1} · ${escapeHTML(labels[c.display_status || c.status])}</span></button>`).join("");
  setHTML($("#campaign-list"), html || '<p class="rail-empty">Tus campañas aparecerán aquí.</p>');
}
function renderCampaign() {
  const c = state.campaigns.find(c => c.id === state.current);
  if (!c || !state.status) return;
  renderCampaignHistory(c);
  renderCampaignRetries(c);
  $("#campaign-title").textContent = c.name;
  $("#campaign-state").className = `badge ${c.display_status || c.status}`;
  $("#campaign-state").textContent = labels[c.display_status || c.status];
  $("#campaign-schedule-notice").hidden = !c.schedule;
  $("#campaign-schedule-description").textContent = scheduleDescription(c.schedule);
  $("#campaign-description").textContent = `${c.total} contactos${c.country ? " · " + countryLabel(c.country) : ""} · ${c.agent_numbers.length} teléfonos de transferencia`;
  renderAgentPool(c, state.status, escapeHTML, setHTML);
  const s = state.status;
  const start = $("#start-button");
  start.hidden = c.status === "running" || !(c.counts.queued > 0);
  start.textContent = c.schedule ? "Iniciar ahora y cancelar horario" : c.status === "paused" ? "Reanudar" : s.mode === "simulation" ? "Iniciar simulación" : "Iniciar llamadas";
  start.disabled = !s.ready || c.mode !== s.mode || !!(s.active_campaign && s.active_campaign !== c.id);
  $("#pause-button").hidden = c.status !== "running";
  $("#stop-button").hidden = !["running", "paused"].includes(c.status);
  let info = s.mode === "simulation" ? "Modo simulación. Selecciona una llamada activa para probar las opciones del teclado. Se simula la duración del mensaje, sin voz real." : "SIP real. Al iniciar se realizarán llamadas a los contactos de esta campaña a través de tu troncal.";
  if (c.mode !== s.mode) info = "Esta campaña pertenece a otro modo. Crea una nueva campaña para usar la configuración actual.";
  else if (c.status === "paused") info = "Campaña pausada. Las llamadas que ya estaban en curso continúan hasta terminar.";
  else if (c.id === s.active_campaign && s.origination_paused) info = "Pausa automática por capacidad: todos los teléfonos de transferencia están ocupados. Las llamadas activas continúan y la marcación se reanudará al quedar uno libre.";
  const modeInformation = $("#mode-information");
  if (modeInformation.textContent !== info) modeInformation.textContent = info;
  const done = Object.entries(c.counts).filter(([key]) => terminal.has(key)).reduce((sum, [, value]) => sum + value, 0);
  $("#campaign-summary").textContent = `${done} de ${c.total} finalizadas · ${c.counts.queued || 0} pendientes · ${c.retry_summary?.attempts || 0} intentos realizados`;
  $("#export-link").href = `/api/campaigns/${c.id}/export`;
  const rows = state.jobs.map(job => `<tr class="${job.contact_id === state.selectedContact ? "selected" : ""}"><td><button class="contact-button" data-action="select-job" data-id="${job.id}" aria-pressed="${job.contact_id === state.selectedContact}">${escapeHTML(job.variables.nombre || job.phone)}${job.variables.nombre ? `<span>${escapeHTML(job.phone)}</span>` : ""}<span>Credito ${escapeHTML(job.credit_id || "Sin crédito histórico")}</span></button></td><td>${badge(job.status)}<span class="attempt-number">Intento ${job.attempt_number} de ${c.retry_policy.max_attempts}</span></td><td>${escapeHTML(job.status === "queued" && job.available_at ? `Reintento disponible: ${retryDate(job.available_at)}` : job.detail || "Lista para llamar")}</td></tr>`).join("");
  setHTML($("#job-rows"), rows);
  $("#page-info").textContent = `${Math.min(state.offset + 1, c.total)}–${Math.min(state.offset + state.jobs.length, c.total)} de ${c.total}`;
  $("#previous-page").disabled = state.offset === 0;
  $("#next-page").disabled = state.offset + 100 >= c.total;
}
async function renderDetail() {
  if (!state.selected) {
    stopRecordings($("#call-detail"));
    setHTML($("#call-detail-summary"), '<h2>Detalle de llamada</h2><p class="muted">Selecciona un contacto para escuchar su grabación y ver el recorrido de la llamada.</p>');
    setHTML($("#call-recording"), "");
    $("#call-recording").hidden = true;
    setHTML($("#call-detail-activity"), "");
    return;
  }
  const id = state.selected;
  const detail = await api(`/api/calls/${encodeURIComponent(id)}`);
  if (state.selected !== id || state.view !== "campaign") return;
  const job = detail;
  const events = detail.history.slice().reverse();
  const canChoose = ["playing", "menu"].includes(job.status);
  const active = state.status.sessions.some(s => s.id === id);
  const keypad = state.status.mode === "simulation" && active ? `<h3>Teclado de simulación</h3><div class="keypad"><button data-action="digit-1" ${canChoose ? "" : "disabled"}><strong>1</strong>Repetir mensaje</button><button data-action="digit-2" ${canChoose ? "" : "disabled"}><strong>2</strong>Hablar con agente</button><button class="end-call" data-action="hangup">Finalizar llamada</button>${job.status === "bridged" ? '<button class="end-call" data-action="agent-hangup">El agente cuelga</button>' : ""}</div>` : "";
  const history = events.slice(0, 8).map(event => `<li>${escapeHTML(labels[event.status])}${event.detail ? ` · ${escapeHTML(event.detail)}` : ""}<time datetime="${escapeHTML(event.created_at)}">${new Date(event.created_at).toLocaleTimeString("es-MX")}</time></li>`).join("");
  setHTML($("#call-detail-summary"), `<button class="subtle back-to-contact" data-action="back-to-contact">Volver al contacto</button><h2>${escapeHTML(job.contact_name || "Detalle de llamada")}</h2><p class="detail-phone">${escapeHTML(job.phone)}</p><p class="detail-phone">Credito ${escapeHTML(job.credit_id || "Sin crédito histórico")}</p>${badge(job.status)}<p class="field-help">Intento ${job.attempt_number} de ${state.campaigns.find(c => c.id === state.current)?.retry_policy.max_attempts || 1}</p>${job.started_at ? `<button class="text-link cdr-link" data-action="open-cdr" data-id="${job.id}">Ver CDR completo</button>` : ""}`);
  // Keep the audio element separate from the activity refreshed by polling.
  $("#call-recording").hidden = false;
  setHTML($("#call-recording"), recordingMarkup(detail, state.user?.role, 3));
  const retryReasons = {unconfirmed_disconnect:"Sin reintento automático: no se confirmó el cierre de la llamada anterior.", contact_reached:"Sin más reintentos: se detectó humano probable, interacción o inicio del mensaje.", attempt_limit:"Se alcanzó el máximo de intentos.", outcome_excluded:"Este resultado no permite reintentar según la política de la campaña.", campaign_stopped:"Sin más reintentos: la campaña está detenida.", interrupted:"Sin reintento automático: la llamada se interrumpió al cerrar la aplicación."};
  const retryReason = retryReasons[detail.retry_decision?.reason] || "";
  const attempts = (detail.attempts || []).map(attempt => `<li><button type="button" class="text-link" data-action="select-attempt" data-id="${escapeHTML(attempt.id)}" aria-current="${attempt.id === id}">Intento ${attempt.attempt_number} · ${escapeHTML(labels[attempt.status])}</button>${attempt.available_at && !attempt.started_at && attempt.status === "queued" ? `<time datetime="${escapeHTML(attempt.available_at)}">Disponible: ${escapeHTML(retryDate(attempt.available_at))}</time>` : attempt.started_at ? `<time datetime="${escapeHTML(attempt.started_at)}">${escapeHTML(retryDate(attempt.started_at))}</time>` : ""}</li>`).join("");
  setHTML($("#call-detail-activity"), `<h3>Intentos de este contacto</h3><ol class="attempt-list">${attempts}</ol>${retryReason ? `<p class="field-help">${escapeHTML(retryReason)}</p>` : ""}<h3>Mensaje personalizado</h3><p class="detail-message">${escapeHTML(job.message)}</p>${keypad}<h3>Actividad</h3><ol class="event-list">${history || '<li class="muted">La llamada aún no ha iniciado.</li>'}</ol>`);
}
async function refresh() {
  const [status, campaigns] = await Promise.all([api("/api/status"), api("/api/campaigns")]);
  state.status = status;
  state.campaigns = campaigns;
  renderStatus();
  renderCampaigns();
  if (state.current && state.view === "campaign") {
    const id = state.current, offset = state.offset;
    const jobs = await api(`/api/campaigns/${id}/jobs?offset=${offset}`);
    if (state.current !== id || state.offset !== offset) return;
    state.jobs = jobs;
    renderCampaign();
    await renderDetail();
    await refreshCampaignHistory();
  }
  await analyticsRefresh();
}
async function action(name, element) {
  notice();
  if (await managementAction(name, element)) return;
  if (await traceabilityAction(name, element)) return;
  if (await analyticsAction(name, element)) return;
  if (await campaignHistoryAction(name, element)) return;
  if (name === "new") { await loadTemplates(); view("editor"); $("#campaign-name").focus(); return; }
  if (name === "back") { view(state.current ? "campaign" : "empty"); await refresh(); return; }
  if (name === "back-to-contact") {
    const latest = state.jobs.find(job => job.contact_id === state.selectedContact);
    const contact = latest ? $(`#job-rows button[data-id="${latest.id}"]`) : null;
    contact?.focus({preventScroll:true});
    contact?.scrollIntoView({block:"center"});
    return;
  }
  if (name === "select-campaign") {
    stopRecordings();
    state.current = element.dataset.id;
    state.selected = null;
    state.selectedContact = null;
    state.offset = 0;
    view("campaign");
  } else if (name === "select-job" || name === "select-attempt") {
    if (state.selected !== element.dataset.id) stopRecordings();
    state.selected = element.dataset.id;
    if (name === "select-job") state.selectedContact = state.jobs.find(job => job.id === state.selected)?.contact_id;
  } else if (name === "preview") {
    if (!validCampaignForm(true)) return;
    const payload = formData();
    const result = await api("/api/preview", payload);
    if(JSON.stringify(payload) !== JSON.stringify(formData())) return;
    $("#message-preview").textContent = result.samples[0].message;
    $("#preview-result").textContent = `${result.count} contactos validados. Vista previa del primero: ${result.samples[0].phone}.`;
    return;
  } else if (name === "demo") {
    if (state.status?.mode !== "simulation") return;
    const result = await api("/api/campaigns", demo);
    state.current = result.id;
    state.selected = null;
    state.selectedContact = null;
    view("campaign");
  } else if (name === "cancel-campaign-schedule") {
    const campaign = state.campaigns.find(c => c.id === state.current);
    if (campaign?.schedule) await api(`/api/manage/schedules/${campaign.schedule.id}/cancel`, {});
  } else if (["start", "pause", "stop"].includes(name)) {
    await api(`/api/campaigns/${state.current}/${name}`, {});
  } else if (["digit-1", "digit-2", "hangup", "agent-hangup"].includes(name)) {
    const value = { "digit-1": "1", "digit-2": "2", "hangup": "hangup", "agent-hangup": "agent_hangup" }[name];
    await api(`/api/jobs/${state.selected}/simulate`, { action: value });
  } else if (name === "previous" || name === "next") {
    state.offset = Math.max(0, state.offset + (name === "next" ? 100 : -100));
    state.selected = null;
    state.selectedContact = null;
  }
  await refresh();
  if (name === "select-campaign") {
    $("#campaign-title").focus({preventScroll:true});
    $("#campaign-title").scrollIntoView({block:"start"});
  }
  if (name === "select-job" && matchMedia("(max-width:1000px)").matches) {
    $("#call-detail").focus({preventScroll:true});
    $("#call-detail").scrollIntoView({block:"start"});
  }
}
async function run(operation, button) {
  if (button) button.disabled = true;
  while (state.busy) await new Promise(resolve => setTimeout(resolve, 20));
  state.busy = true;
  try { await operation(); }
  catch (error) { notice(error.message); }
  finally { state.busy = false; if (button?.isConnected) button.disabled = false; renderStatus(); renderCampaign(); }
}
document.addEventListener("click", event => {
  const button = event.target.closest("button[data-action]");
  if (button && !button.disabled) run(() => action(button.dataset.action, button), button);
});
$("#campaign-form").addEventListener("submit", event => {
  event.preventDefault();
  if (!validCampaignForm()) return;
  const payload = formData();
  run(async () => {
    notice();
    $("#campaign-save-error").textContent = "";
    let result;
    try { result = await api("/api/campaigns", payload); }
    catch (error) { $("#campaign-save-error").textContent = error.message; throw error; }
    state.current = result.id;
    state.selected = null;
    state.selectedContact = null;
    state.offset = 0;
    $("#campaign-form").reset();
    $("#message-preview").textContent = "Completa los datos y revisa el mensaje antes de crear la campaña.";
    $("#preview-result").textContent = "";
    view("campaign");
    await refresh();
    if (result.start_error) notice(`La campaña quedó guardada como borrador: ${result.start_error}`);
  }, event.submitter);
});
$("#capacity-form").addEventListener("submit", event => {
  event.preventDefault();
  run(async () => { notice(); state.status = await api("/api/settings", { concurrency: Number($("#concurrency").value) }); renderStatus(); }, event.submitter);
});
for (const [selector, normalize] of [["#agent-number", removePhonePlus], ["#contacts", removeCsvPhonePlus]]) {
  const field = $(selector);
  field.addEventListener("input", event => {
    if (!event.isComposing) cleanPhoneInput(field, normalize);
  });
  field.addEventListener("compositionend", () => cleanPhoneInput(field, normalize));
  field.addEventListener("change", () => cleanPhoneInput(field, normalize));
}
installAnalytics({ state, labels, terminal, api, view, refresh, notice, setHTML, badge });
async function poll() {
  try { if (state.user && !state.busy && !document.hidden) await refresh(); }
  catch { $("#connection-state").textContent = "Sin conexión · reintentando"; }
  finally { setTimeout(poll, 1500); }
}
installAudioPreview({api});
installRecordingPlayback();
installTraceability({state, api, view, run, setHTML, badge});
installContactImport({api, expireSession, clearAudioPreview});
installCountryFields();
installAgentPool();
installCampaignExecution();
installCampaignRetries({state, api, refresh, run});
installCampaignHistory({state, api, view, refresh, notice, run, escapeHTML, setHTML, badge});
installManagement({ state, api, view, refresh, notice, run, escapeHTML, clearAudioPreview });
await bootSession();
applyRole();
poll();
