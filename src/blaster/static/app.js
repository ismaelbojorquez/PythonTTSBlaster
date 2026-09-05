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
import { getLanguage, initI18n, locale, t, translateHTML, translateText } from "./i18n.js";

import { installManagement, managementAction, bootSession, loadTemplates, expireSession, applyRole } from "./management.js";

initI18n();

const $ = (selector) => document.querySelector(selector);
const LANGUAGE_CONTEXT_KEY = "blaster.language-context";
const state = { campaigns: [], current: null, selected: null, selectedContact: null, jobs: [], status: null, view: "dashboard", user: null, offset: 0, busy: false, scheduleEditorFor: null };
const labels = Object.fromEntries(Object.entries({ draft: "Borrador", running: "En curso", paused: "Pausada", stopped: "Detenida", queued: "Pendiente", dialing: "Marcando", synthesizing: "Preparando mensaje", detecting: "Identificando respuesta", machine: "Buzón probable", amd_unknown: "Respuesta no identificada", playing: "Mensaje en curso", menu: "Esperando respuesta", agent_dialing: "Contactando al agente", agent_waiting: "Esperando un agente disponible", bridged: "Con agente", completed: "Finalizada", failed: "No completada", temporary_error: "Proveedor no disponible", busy: "Ocupado", no_answer: "Sin respuesta", cancelled: "Cancelada", interrupted: "Interrumpida", no_input: "Sin selección", scheduled: "Programada" }).map(([key, value]) => [key, t(value)]));
const terminal = new Set(["completed", "failed", "temporary_error", "busy", "no_answer", "cancelled", "interrupted", "no_input", "machine", "amd_unknown"]);
const demo = () => getLanguage() === "en"
  ? { name: "Demo · Reminders", agent_number: "525550009999", template: "Hello {name}. This is a reminder for your appointment on {date}. Your reference is {reference}. Thank you for confirming.", csv_text: "Credito,Telefono,name,date,reference\nDEMO-101,525550000101,Ana Martinez,Friday September 12,A 102\nDEMO-102,525550000102,Carlos Lopez,Monday September 15,B 208\nDEMO-103,525550000103,Lucia Torres,Tuesday September 16,C 315\nDEMO-104,525550000104,Miguel Reyes,Wednesday September 17,D 420\nDEMO-105,525550000105,Sofia Ramirez,Thursday September 18,E 531" }
  : { name: "Demostración · Recordatorios", agent_number: "525550009999", template: "Hola {nombre}. Te recordamos tu cita del {fecha}. Tu folio es {folio}. Gracias por confirmar tu asistencia.", csv_text: "Credito,Telefono,nombre,fecha,folio\nDEMO-101,525550000101,Ana Martínez,viernes 12 de septiembre,A 102\nDEMO-102,525550000102,Carlos López,lunes 15 de septiembre,B 208\nDEMO-103,525550000103,Lucía Torres,martes 16 de septiembre,C 315\nDEMO-104,525550000104,Miguel Reyes,miércoles 17 de septiembre,D 420\nDEMO-105,525550000105,Sofía Ramírez,jueves 18 de septiembre,E 531" };

function escapeHTML(value) { return String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]); }
function badge(value) { return `<span class="badge ${escapeHTML(value)}">${escapeHTML(labels[value] || t("Estado actualizado"))}</span>`; }
function trunkLabel(row, role = "customer") {
  const id = row?.[`${role}_trunk_id`];
  if (!id) return t("Sin asignar");
  const configured = state.status?.trunks?.find(trunk => trunk.id === id);
  const name = row?.[`${role}_trunk_name`] || configured?.name;
  return commercialText(name || id);
}
function notice(message = "") { $("#notice").hidden = !message; $("#notice").textContent = translateText(message); }
function commercialText(value = "") {
  const raw = String(value);
  const internalEvidence = {
    remote_bye: "El otro lado finalizó la llamada",
    local_bye: "La plataforma finalizó la llamada",
    tx_bye: "La plataforma finalizó la llamada",
    rx_bye: "El otro lado finalizó la llamada",
    unconfirmed_disconnect: "La conexión terminó sin confirmar quién finalizó",
    sip_response: "El proveedor informó el resultado de la llamada",
    registered: "Disponible",
    unregistered: "No disponible",
    registration_failed: "No disponible",
    simulation_ready: "Prueba disponible",
  };
  if (internalEvidence[raw]) return t(internalEvidence[raw]);
  const providerResponse = raw.match(/(?:Respuesta\s+)?SIP\s+(\d{3})/i);
  if (providerResponse) {
    return t(({
      100: "El proveedor está procesando la llamada",
      180: "El teléfono está timbrando",
      183: "El proveedor está preparando la conexión",
      200: "La llamada fue conectada",
      401: "El proveedor está verificando el acceso",
      403: "El proveedor no autorizó la llamada",
      404: "El número no fue encontrado",
      408: "El proveedor no respondió a tiempo",
      480: "El destinatario no está disponible",
      486: "La línea está ocupada",
      487: "La llamada terminó antes de conectarse",
      503: "El proveedor no está disponible",
      504: "El proveedor no pudo completar la llamada a tiempo",
      603: "El destinatario rechazó la llamada",
    })[providerResponse[1]] || "El proveedor no pudo completar la llamada");
  }
  if (/RX\s+BYE|BYE\s+recibido/i.test(raw)) return t("El otro lado finalizó la llamada");
  if (/TX\s+BYE|BYE\s+enviado/i.test(raw)) return t("La plataforma finalizó la llamada");
  if (/Call-ID|CSeq|Via:|tag=|branch=|PJSIP|REGISTER|INVITE|RTP|(?:trunk|call|leg|job|sip)_id\s*[=:]/i.test(raw)) return t("Información de la llamada actualizada");
  if (/^[a-z][a-z0-9_]+$/i.test(raw)) return t("Información registrada");
  return translateText(raw
    .replace(/simulaci[oó]n lista/gi, "Prueba disponible")
    .replace(/SIP real/gi, "En vivo")
    .replace(/\bsimulaci[oó]n\b/gi, "prueba")
    .replace(/\bSIP\b/gi, "proveedor")
    .replace(/\bPJSIP\b/gi, "servicio de llamadas")
    .replace(/\bTTS\b/gi, "mensaje de voz")
    .replace(/\bAMD\b/gi, "detección de buzón")
    .replace(/\bCDRs?\b/gi, "historial de llamadas")
    .replace(/\bINVITE\b/gi, "intento de llamada")
    .replace(/\bRTP\b/gi, "audio")
    .replace(/\bREGISTER\b/gi, "identificación del proveedor")
    .replace(/config\.toml/gi, "la configuración")
    .replace(/\btroncal(?:es)?\b/gi, match => {
      const replacement = match.toLowerCase().endsWith("es") ? "proveedores" : "proveedor";
      return match[0] === match[0].toUpperCase() ? replacement[0].toUpperCase() + replacement.slice(1) : replacement;
    }));
}
function commercialError(message = "") {
  const raw = String(message || "");
  if (/respuesta SIP\s+\d{3}/i.test(raw)) return commercialText(raw);
  if (/PJSIP|REGISTER|INVITE|RTP/i.test(raw)) return t("El proveedor de llamadas no pudo completar la operación. Revisa su disponibilidad e intenta nuevamente.");
  if (/TTS|Piper|Kokoro|onnx|voice model/i.test(raw)) return t("No pudimos preparar el mensaje de voz. Revisa la voz seleccionada e intenta nuevamente.");
  if (/Field required|Input should|validation|Traceback|\bHTTP\s*\d{3}|[A-Za-z]+Error|\/api\/|\.py(?::\d+)?/i.test(raw)) return t("No pudimos completar la acción. Revisa la información e intenta nuevamente.");
  return commercialText(raw) || t("No pudimos completar la acción. Revisa la información e intenta nuevamente.");
}
function setHTML(element, html) {
  const localized = translateHTML(html);
  if (element._rendered === localized) return;
  const active = document.activeElement;
  const identity = element.contains(active) && active.dataset ? { ...active.dataset } : null;
  element.innerHTML = localized;
  element._rendered = localized;
  if (identity?.action) {
    const target = [...element.querySelectorAll("button")].find(el => el.dataset.action === identity.action && el.dataset.id === identity.id);
    target?.focus({ preventScroll: true });
  }
}
async function api(path, payload) {
  const headers = { "Accept-Language": getLanguage() };
  if (payload !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, payload === undefined ? {headers} : { method: "POST", headers, body: JSON.stringify(payload) });
  if (response.status === 401 && !path.startsWith("/api/auth/")) expireSession();
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const message = Array.isArray(data.detail) ? data.detail.map(e => e.msg).join(". ") : data.detail;
    throw new Error(commercialError(message));
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
function saveLanguageContext() {
  const fields = [...document.querySelectorAll("main input[id], main select[id], main textarea[id]")]
    .filter(element => element.type !== "file")
    .map(element => ({id:element.id, value:element.value, checked:element.checked, checkable:["checkbox","radio"].includes(element.type)}));
  const details = [...document.querySelectorAll("main details[id]")].filter(element => element.open).map(element => element.id);
  try {
    sessionStorage.setItem(LANGUAGE_CONTEXT_KEY, JSON.stringify({view:state.view,current:state.current,selected:state.selected,fields,details,scrollY:window.scrollY}));
  } catch {}
}
async function restoreLanguageContext() {
  let saved;
  try {
    saved = JSON.parse(sessionStorage.getItem(LANGUAGE_CONTEXT_KEY) || "null");
    sessionStorage.removeItem(LANGUAGE_CONTEXT_KEY);
  } catch { return; }
  if (!saved || !state.user) return;
  if (saved.view === "campaign" && saved.current && state.campaigns.some(item => item.id === saved.current)) {
    state.current = saved.current;
    state.selected = saved.selected;
    view("campaign");
    await refresh();
  } else if (saved.view === "editor") {
    await action("new", document.createElement("button"));
  } else if (["dashboard","campaigns","calls","traceability","reports","operations"].includes(saved.view)) {
    await action(`nav-${saved.view}`, document.createElement("button"));
  }
  for (const field of saved.fields || []) {
    const element = document.getElementById(field.id);
    if (!element || element.type === "file") continue;
    if (field.checkable) element.checked = field.checked;
    else element.value = field.value;
  }
  for (const id of saved.details || []) document.getElementById(id)?.setAttribute("open", "");
  if (saved.view === "editor") {
    for (const id of ["country","agent-country"]) document.getElementById(id)?.dispatchEvent(new Event("change", {bubbles:true}));
    for (const id of ["contacts","message"]) document.getElementById(id)?.dispatchEvent(new Event("input", {bubbles:true}));
    document.querySelector('input[name="execution"]:checked')?.dispatchEvent(new Event("change", {bubbles:true}));
  }
  requestAnimationFrame(() => window.scrollTo({top:Number(saved.scrollY) || 0}));
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
  $("#connection-state").textContent = t(s.mode === "simulation" ? "Prueba disponible" : s.ready ? "Proveedor disponible" : "Proveedor no disponible");
  $("#live-count").textContent = translateText(`${s.active_sessions} en curso`);
  const mode = $("#mode-badge");
  mode.textContent = t(s.mode === "simulation" ? "Prueba" : "En vivo");
  mode.className = `badge ${s.mode === "simulation" ? "simulation" : "live"}`;
  setHTML($("#active-count"), `${s.active_sessions} <span>/ ${s.concurrency}</span>`);
  setHTML($("#channel-count"), `${s.channels_in_use} <span>/ ${s.trunk_channels}</span>`);
  $("#concurrency").max = Math.min(30, Math.floor(s.trunk_channels / 2));
  if (document.activeElement !== $("#concurrency")) $("#concurrency").value = s.concurrency;
  $("#demo-button").hidden = s.mode !== "simulation";
  $("#simulation-note").hidden = s.mode !== "simulation";
  $("#amd-note").hidden = !s.amd_enabled;
  $("#amd-note").textContent = s.amd_enabled
    ? translateText(`Filtro de buzón activo. ${s.amd_unknown_action === "hangup" ? "La llamada finaliza cuando se detecta un buzón o no es posible identificar la respuesta." : "La llamada finaliza ante un buzón; las respuestas no identificadas continúan."}${s.mode === "simulation" ? " En el modo de prueba se utiliza un saludo de ejemplo." : ""}`)
    : "";
}
function renderCampaigns() {
  $("#campaign-count").textContent = state.campaigns.length;
  const html = state.campaigns.map(c => `<button class="campaign-nav ${c.id === state.current && state.view === "campaign" ? "active" : ""}" data-action="select-campaign" data-id="${c.id}" ${c.id === state.current && state.view === "campaign" ? 'aria-current="page"' : ""}>${escapeHTML(c.name)}<span class="nav-meta">${c.total} contactos · Envío ${c.lineage?.execution_number || 1} · ${escapeHTML(labels[c.display_status || c.status])}</span></button>`).join("");
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
  $("#campaign-schedule-description").textContent = translateText(scheduleDescription(c.schedule));
  $("#campaign-description").textContent = translateText(`${c.total} contactos${c.country ? " · " + countryLabel(c.country) : ""} · ${c.agent_numbers.length} teléfonos de transferencia`);
  renderAgentPool(c, state.status, escapeHTML, setHTML);
  const s = state.status;
  const start = $("#start-button");
  start.hidden = c.status === "running" || !(c.counts.queued > 0);
  start.textContent = t(c.schedule ? "Iniciar ahora y cancelar horario" : c.status === "paused" ? "Reanudar" : s.mode === "simulation" ? "Iniciar prueba" : "Iniciar llamadas");
  start.disabled = !s.ready || c.mode !== s.mode || !!(s.active_campaign && s.active_campaign !== c.id);
  const canSchedule = c.status === "draft" && c.counts.queued > 0 && !c.schedule;
  const scheduleButton = $("#schedule-button");
  scheduleButton.hidden = !canSchedule;
  scheduleButton.disabled = c.mode !== s.mode;
  scheduleButton.title = t(c.mode !== s.mode
    ? "La campaña fue creada para otro tipo de operación"
    : !s.automation_enabled
    ? "Activa las tareas programadas en Configuración antes de programar"
    : "Elegir fecha y hora de inicio");
  if (!canSchedule && state.scheduleEditorFor === c.id) state.scheduleEditorFor = null;
  $("#draft-schedule-form").hidden = state.scheduleEditorFor !== c.id || !canSchedule;
  $("#draft-schedule-warning").textContent = t(!s.automation_enabled
    ? "Las tareas programadas están desactivadas. Actívalas en Operación → Configuración antes de guardar el horario."
    : "El horario se guardará en la zona seleccionada. Blaster debe permanecer abierto.");
  $("#pause-button").hidden = c.status !== "running";
  $("#stop-button").hidden = !["running", "paused"].includes(c.status);
  let info = s.mode === "simulation" ? "Modo de prueba. Selecciona una llamada activa para revisar las opciones del mensaje sin realizar llamadas reales." : "Operación en vivo. Al iniciar se llamará a los contactos de esta campaña con el proveedor disponible.";
  if (c.mode !== s.mode) info = "Esta campaña fue creada para otro tipo de operación. Crea una nueva campaña para utilizar la selección actual.";
  else if (c.status === "paused") info = "Campaña pausada. Las llamadas que ya estaban en curso continúan hasta terminar.";
  else if (c.id === s.active_campaign && s.origination_paused) info = "Pausa automática por capacidad: todos los teléfonos de transferencia están ocupados. Las llamadas activas continúan y la marcación se reanudará al quedar uno libre.";
  const modeInformation = $("#mode-information");
  info = t(info);
  if (modeInformation.textContent !== info) modeInformation.textContent = info;
  const done = Object.entries(c.counts).filter(([key]) => terminal.has(key)).reduce((sum, [, value]) => sum + value, 0);
  $("#campaign-summary").textContent = translateText(`${done} de ${c.total} finalizadas · ${c.counts.queued || 0} pendientes · ${c.retry_summary?.attempts || 0} intentos realizados`);
  $("#export-link").href = `/api/campaigns/${c.id}/export`;
  const rows = state.jobs.map(job => `<tr class="${job.contact_id === state.selectedContact ? "selected" : ""}"><td><button class="contact-button" data-action="select-job" data-id="${job.id}" aria-pressed="${job.contact_id === state.selectedContact}">${escapeHTML(job.variables.nombre || job.phone)}${job.variables.nombre ? `<span>${escapeHTML(job.phone)}</span>` : ""}<span>Crédito ${escapeHTML(job.credit_id || "Sin crédito histórico")}</span></button></td><td><span class="trunk-cell">${escapeHTML(trunkLabel(job))}</span></td><td>${badge(job.status)}<span class="attempt-number">Intento ${job.attempt_number} de ${c.retry_policy.max_attempts}</span></td><td>${escapeHTML(job.status === "queued" && job.available_at ? `Próximo intento: ${retryDate(job.available_at)}` : commercialText(job.detail || "Lista para llamar"))}</td></tr>`).join("");
  setHTML($("#job-rows"), rows);
  $("#page-info").textContent = `${Math.min(state.offset + 1, c.total)}–${Math.min(state.offset + state.jobs.length, c.total)} ${t("de")} ${c.total}`;
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
  const keypad = state.status.mode === "simulation" && active ? `<h3>Opciones de prueba</h3><div class="keypad"><button data-action="digit-1" ${canChoose ? "" : "disabled"}><strong>1</strong>Repetir mensaje</button><button data-action="digit-2" ${canChoose ? "" : "disabled"}><strong>2</strong>Hablar con agente</button><button class="end-call" data-action="hangup">Finalizar llamada</button>${job.status === "bridged" ? '<button class="end-call" data-action="agent-hangup">Finalizar como agente</button>' : ""}</div>` : "";
  const history = events.slice(0, 8).map(event => `<li>${escapeHTML(labels[event.status])}${event.detail ? ` · ${escapeHTML(commercialText(event.detail))}` : ""}<time datetime="${escapeHTML(event.created_at)}">${new Date(event.created_at).toLocaleTimeString(locale())}</time></li>`).join("");
  setHTML($("#call-detail-summary"), `<button class="subtle back-to-contact" data-action="back-to-contact">Volver al contacto</button><h2>${escapeHTML(job.contact_name || "Detalle de llamada")}</h2><p class="detail-phone">${escapeHTML(job.phone)}</p><p class="detail-phone">Crédito ${escapeHTML(job.credit_id || "Sin crédito histórico")}</p><p class="detail-phone">Proveedor: ${escapeHTML(trunkLabel(job))}</p>${badge(job.status)}<p class="field-help">Intento ${job.attempt_number} de ${state.campaigns.find(c => c.id === state.current)?.retry_policy.max_attempts || 1}</p>${job.started_at ? `<button class="text-link cdr-link" data-action="open-cdr" data-id="${job.id}">Ver historial completo</button>` : ""}`);
  // Keep the audio element separate from the activity refreshed by polling.
  $("#call-recording").hidden = false;
  setHTML($("#call-recording"), recordingMarkup(detail, state.user?.role, 3));
  const retryReasons = {unconfirmed_disconnect:"Sin reintento automático: no se confirmó el cierre de la llamada anterior.", contact_reached:"Sin más reintentos: se detectó humano probable, interacción o inicio del mensaje.", attempt_limit:"Se alcanzó el máximo de intentos.", outcome_excluded:"Este resultado no permite reintentar según la política de la campaña.", campaign_stopped:"Sin más reintentos: la campaña está detenida.", interrupted:"Sin reintento automático: la llamada se interrumpió al cerrar la aplicación."};
  const retryReason = retryReasons[detail.retry_decision?.reason] || "";
  const attempts = (detail.attempts || []).map(attempt => `<li><button type="button" class="text-link" data-action="select-attempt" data-id="${escapeHTML(attempt.id)}" aria-current="${attempt.id === id}">Intento ${attempt.attempt_number} · ${escapeHTML(labels[attempt.status])}</button><span class="attempt-trunk">${escapeHTML(trunkLabel(attempt))}</span>${attempt.available_at && !attempt.started_at && attempt.status === "queued" ? `<time datetime="${escapeHTML(attempt.available_at)}">Disponible: ${escapeHTML(retryDate(attempt.available_at))}</time>` : attempt.started_at ? `<time datetime="${escapeHTML(attempt.started_at)}">${escapeHTML(retryDate(attempt.started_at))}</time>` : ""}</li>`).join("");
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
    state.scheduleEditorFor = null;
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
    $("#preview-result").textContent = translateText(`${result.count} contactos validados. Vista previa del primero: ${result.samples[0].phone}.`);
    return;
  } else if (name === "demo") {
    if (state.status?.mode !== "simulation") return;
    const result = await api("/api/campaigns", demo());
    state.current = result.id;
    state.selected = null;
    state.selectedContact = null;
    view("campaign");
  } else if (name === "cancel-campaign-schedule") {
    const campaign = state.campaigns.find(c => c.id === state.current);
    if (campaign?.schedule) await api(`/api/manage/schedules/${campaign.schedule.id}/cancel`, {});
  } else if (name === "schedule-campaign") {
    state.scheduleEditorFor = state.current;
    const source = $("#campaign-timezone"), target = $("#draft-schedule-timezone");
    target.replaceChildren(...[...source.options].map(option => option.cloneNode(true)));
    target.value = state.status.reporting_timezone || "America/Mexico_City";
    $("#draft-schedule-error").textContent = "";
    renderCampaign();
    $("#draft-schedule-at").focus();
    $("#draft-schedule-form").scrollIntoView({block:"nearest"});
    return;
  } else if (name === "cancel-draft-schedule") {
    state.scheduleEditorFor = null;
    $("#draft-schedule-form").reset();
    $("#draft-schedule-error").textContent = "";
    renderCampaign();
    $("#schedule-button").focus();
    return;
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
    if (result.start_error) notice(`${t("La campaña quedó guardada como borrador:")} ${commercialText(result.start_error)}`);
  }, event.submitter);
});
$("#draft-schedule-form").addEventListener("submit", event => {
  event.preventDefault();
  if (!event.currentTarget.reportValidity()) return;
  const form = event.currentTarget;
  const campaignId = state.current;
  run(async () => {
    $("#draft-schedule-error").textContent = "";
    try {
      await api("/api/manage/schedules", {
        campaign_id: campaignId,
        local_at: form.elements.local_at.value,
        timezone: form.elements.timezone.value,
      });
    } catch (error) {
      $("#draft-schedule-error").textContent = error.message;
      throw error;
    }
    state.scheduleEditorFor = null;
    form.reset();
    await refresh();
    $("#campaign-schedule-notice").scrollIntoView({block:"nearest"});
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
installAnalytics({ state, labels, terminal, api, view, refresh, notice, setHTML, badge, commercialText, commercialError });
async function poll() {
  try { if (state.user && !state.busy && !document.hidden) await refresh(); }
  catch { $("#connection-state").textContent = t("Reconectando…"); }
  finally { setTimeout(poll, 1500); }
}
installAudioPreview({api});
installRecordingPlayback();
installTraceability({state, api, view, run, setHTML, badge, commercialText, commercialError});
installContactImport({api, expireSession, clearAudioPreview});
installCountryFields();
installAgentPool();
installCampaignExecution();
installCampaignRetries({state, api, refresh, run});
installCampaignHistory({state, api, view, refresh, notice, run, escapeHTML, setHTML, badge, commercialText});
installManagement({ state, api, view, refresh, notice, run, escapeHTML, clearAudioPreview, commercialText });
window.addEventListener("blaster:before-language-change", saveLanguageContext);
await bootSession();
applyRole();
if (state.user) {
  await refresh();
  await restoreLanguageContext();
}
poll();
