import { recordingMarkup, stopRecordings } from "./recording-player.js";
import { getLanguage, locale, t, translateHTML, translateText } from "./i18n.js";

const $ = s => document.querySelector(s);
const number = new Intl.NumberFormat(locale());
const decimal = new Intl.NumberFormat(locale(), {minimumFractionDigits:1, maximumFractionDigits:1});
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const n = value => value == null ? "—" : number.format(value);
const pct = value => value == null ? t("Sin base de cálculo") : `${decimal.format(value * 100)} %`;
const pageSize = () => matchMedia("(max-width:680px)").matches ? 25 : 50;
const seconds = value => value == null ? "—" : value < 60 ? `${decimal.format(value)} s` : `${Math.floor(value / 60)} min ${Math.round(value % 60)} s`;
function trunkIdLabel(id, storedName = "") {
  if (!id) return t("Sin asignar");
  const name = storedName || ctx.state.status?.trunks?.find(trunk => trunk.id === id)?.name;
  return ctx.commercialText(name || id);
}
function trunkLabel(row, role = "customer") {
  const id = row?.[`${role}_trunk_id`];
  if (!id) return t("Sin asignar");
  const name = row?.[`${role}_trunk_name`];
  return ctx.commercialText(name || trunkIdLabel(id));
}
const localizedMap = source => Object.fromEntries(Object.entries(source).map(([key,value])=>[key,t(value)]));
const actors = localizedMap({customer:"Cliente", agent:"Agente", system:"Plataforma", operator:"Operador", trunk:"Proveedor", unknown:"No identificado"});
const amd = localizedMap({human:"Persona probable", machine:"Buzón probable", unknown:"Respuesta no identificada", pending:"Pendiente", disabled:"Sin evaluación", unmeasured:"Sin información anterior"});
const responseReasons = localizedMap({short_greeting:"Saludo breve seguido de una pausa",long_greeting:"Saludo prolongado",many_words:"Saludo con varias frases",beep:"Tono de buzón",initial_silence:"No se escuchó un saludo",analysis_timeout:"No fue posible identificar la respuesta a tiempo",no_audio:"No se recibió voz",audio_overflow:"La recepción de voz se interrumpió",invalid_audio:"No fue posible reconocer el audio"});
const lightColors = ["#171714", "#73921b", "#d28c28", "#8e9188", "#ba6257", "#62547f", "#94a88b", "#a87951", "#4d5a48"];
const darkColors = ["#edf0e7", "#a7c93a", "#efb55a", "#aeb1a6", "#e27e73", "#a997cb", "#abc3a3", "#d1a174", "#93a68c"];
const darkTheme = () => document.documentElement.dataset.theme === "dark";
const colors = () => darkTheme() ? darkColors : lightColors;
let ctx, initialized = false, lastFetch = 0, request = 0, offset = 0, detailId = null, summary = null, downloaded = false;
let detailOrigin = "calls", detailOriginId = null;
let query = new URLSearchParams(), charts = new Map();
const labels = localizedMap({dashboard:"El pulso de tus llamadas", calls:"Todas las llamadas", reports:"Reportes y exportaciones"});

export function installAnalytics(context) {
  ctx = context;
  for (const [key, label] of Object.entries(ctx.labels)) {
    if (!["draft","running","paused","stopped","queued"].includes(key)) $("#call-status-filter").add(new Option(label, key));
  }
  $("#filter-period").addEventListener("change", () => dates($("#filter-period").value));
  for (const id of ["#filter-from", "#filter-to"]) $(id).addEventListener("change", () => { $("#filter-period").value = "custom"; });
  $("#analytics-filters").addEventListener("submit", event => {
    event.preventDefault(); applyFilters().catch(error => ctx.notice(error.message));
  });
  $("#call-search-form").addEventListener("submit", event => {
    event.preventDefault(); offset = 0; fetchCalls().catch(error => ctx.notice(error.message));
  });
  window.addEventListener("blaster:theme-change", () => {
    for (const item of charts.values()) item.instance.destroy();
    charts.clear();
    if (summary) renderSummary(summary);
  });
}

function dayInZone(value = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {timeZone: ctx.state.status?.reporting_timezone || "America/Mexico_City", year:"numeric", month:"2-digit", day:"2-digit"}).format(value);
}
function dates(period) {
  if (period === "custom") return;
  const end = dayInZone();
  const start = new Date(`${end}T12:00:00Z`);
  start.setUTCDate(start.getUTCDate() - (Number(period) - 1));
  $("#filter-from").value = period === "all" ? "" : start.toISOString().slice(0,10);
  $("#filter-to").value = period === "all" ? "" : end;
}
function currentFilters() {
  const result = new URLSearchParams();
  for (const [id,key] of [["from","date_from"],["to","date_to"],["campaign","campaign_id"],["mode","mode"]]) {
    const value = $(`#filter-${id}`).value;
    if (value) result.set(key, value);
  }
  return result;
}
async function applyFilters() {
  if ($("#filter-from").value && $("#filter-to").value && $("#filter-from").value > $("#filter-to").value) throw new Error(t("La fecha inicial debe ser anterior o igual a la final."));
  stopRecordings();
  query = currentFilters(); offset = 0; detailId = null; lastFetch = 0;
  ctx.notice(); await analyticsRefresh(true);
}
function time(value, full = false) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(locale(), {timeZone:ctx.state.status?.reporting_timezone || "America/Mexico_City", ...(full ? {day:"2-digit", month:"short", year:"numeric"} : {}),hour:"2-digit", minute:"2-digit", second:"2-digit", hour12:false}).format(new Date(value));
}

export function analyticsView(name) {
  const enabled = ["dashboard", "calls", "reports"].includes(name);
  for (const id of ["analytics-heading", "analytics-filters", "analytics-context"]) $(`#${id}`).hidden = !enabled;
  $(".capacity-strip").hidden = !["campaign", "editor", "empty"].includes(name);
  $("#analytics-title").textContent = labels[name] || "";
  $("#analytics-subtitle").textContent = t(name === "calls" ? "Cada respuesta, transferencia y finalización, en un solo registro." : name === "reports" ? "Convierte el recorrido de tus llamadas en información útil." : "De la primera marcación a la conversación con tu agente.");
  const nav = ["campaign", "editor", "empty"].includes(name) ? "campaigns" : name;
  document.querySelectorAll(".primary-nav button").forEach(button => {
    if (button.dataset.action === `nav-${nav}`) button.setAttribute("aria-current","page"); else button.removeAttribute("aria-current");
  });
  $(".topbar-title").textContent = t({dashboard:"Resumen",campaigns:"Campañas",calls:"Historial de llamadas",traceability:"Historial por cliente",reports:"Reportes",operations:"Operación"}[nav]);
  document.title = `Blaster · ${$(".topbar-title").textContent}`;
  lastFetch = 0;
}

export async function analyticsRefresh(force = false) {
  if (!ctx.state.status) return;
  if (!initialized) {
    initialized = true; $("#filter-mode").value = ctx.state.status.mode;
    dates("30"); query = currentFilters();
  }
  $("#live-count").textContent = translateText(`${ctx.state.status.active_sessions} en curso`);
  const selector = $("#filter-campaign"), old = selector.value;
  const options = `<option value="">${t("Todas las campañas")}</option>` + ctx.state.campaigns.map(c => `<option value="${esc(c.id)}">${esc(c.name)}${c.lineage?.execution_number > 1 ? ` · ${translateText(`Envío ${c.lineage.execution_number}`)}` : ""}</option>`).join("");
  if (selector._options !== options) { selector.innerHTML = translateHTML(options); selector._options = options; selector.value = old; }
  if (ctx.state.view === "campaigns") renderCampaignOverview();
  if (!["dashboard","reports","calls"].includes(ctx.state.view)) return;
  if (!force && Date.now() - lastFetch < (ctx.state.view === "calls" ? 5000 : 15000)) return;
  lastFetch = Date.now();
  if (ctx.state.view === "calls") { await fetchCalls(); return; }
  const version = ++request, key = query.toString();
  $("#dashboard-view").setAttribute("aria-busy", "true");
  try {
    const data = await ctx.api(`/api/analytics/summary?${key}`);
    if (version !== request || key !== query.toString()) return;
    summary = data; renderSummary(data);
  } finally { $("#dashboard-view").setAttribute("aria-busy", "false"); }
}

function contextLine(total) {
  const mode = t({sip:"En vivo",simulation:"Prueba",all:"Todas las operaciones"}[query.get("mode")]);
  $("#filter-description").textContent = `${translateText(`${n(total)} llamadas`)} · ${mode} · ${ctx.state.status.reporting_timezone}`;
  $("#analytics-updated").textContent = translateText(`Actualizado ${time(new Date().toISOString())}`);
}
function chart(id, type, data, options = {}) {
  const signature = JSON.stringify({theme:darkTheme() ? "dark" : "light", data, options});
  const existing = charts.get(id);
  if (existing?.signature === signature) { existing.instance.resize(); return; }
  existing?.instance.destroy();
  const instance = new window.Chart($("#" + id), {type, data, options: {
    responsive:true, maintainAspectRatio:false, animation:false,
    interaction:{mode:"index",intersect:false},
    plugins:{legend:{position:"bottom", align:"start", labels:{usePointStyle:true,pointStyle:"rectRounded",boxWidth:7,boxHeight:7,padding:20,color:darkTheme()?"#aeb0a7":"#66685f",font:{size:11}}},tooltip:{backgroundColor:"#171714",padding:12,cornerRadius:7}},
    scales:type === "doughnut" ? {} : {x:{grid:{display:false},border:{display:false},ticks:{maxTicksLimit:7,maxRotation:0,color:darkTheme()?"#aeb0a7":"#66685f",font:{size:11}}},y:{beginAtZero:true,border:{display:false},grid:{color:darkTheme()?"#353731":"#e5e1d6"},ticks:{precision:0,maxTicksLimit:5,color:darkTheme()?"#aeb0a7":"#66685f",font:{size:11}}}},
    ...options
  }});
  charts.set(id, {signature, instance});
}
function bars(id, values, names, maximum = null) {
  const entries = Object.entries(values), max = maximum || Math.max(1, ...Object.values(values));
  ctx.setHTML($(id), entries.length ? entries.map(([key,value],i) => {
    const label = t(names[key] || key);
    return `<div class="bar-row series-${i % lightColors.length}"><div><span>${esc(label)}</span><strong>${n(value)}</strong></div><meter min="0" max="${max}" value="${value}" aria-label="${esc(label)}">${value} ${t("de")} ${max}</meter></div>`;
  }).join("") : '<p class="no-measurements">Sin mediciones en este período.</p>');
}
function renderSummary(data) {
  const c = data.counts; contextLine(c.total);
  $("#analytics-empty").hidden = c.total > 0;
  $("#coverage-note").hidden = c.legacy === 0;
  $("#coverage-note").textContent = translateText(`${n(c.legacy)} registros anteriores conservan su resultado original. Los porcentajes y tiempos se calculan con la información disponible; los datos faltantes aparecen como «—».`);
  $("#metric-total").textContent = n(c.total);
  $("#metric-total-note").textContent = translateText(`${n(c.attempted)} intentos realizados · ${n(c.active)} en curso`);
  $("#metric-answer").textContent = n(c.answered);
  $("#metric-answer-note").textContent = data.answer_rate == null
    ? t("Sin tasa de respuesta · incluye buzones")
    : translateText(`${pct(data.answer_rate)} de respuesta · incluye buzones`);
  $("#metric-bridge").textContent = n(c.bridged);
  $("#metric-bridge-note").textContent = data.transfer_rate == null
    ? translateText(`${n(c.transfer_requested)} solicitudes · Sin tasa de transferencia`)
    : translateText(`${n(c.transfer_requested)} solicitudes · ${pct(data.transfer_rate)}`);
  const duration = data.durations.customer_connected_seconds;
  $("#metric-duration").textContent = seconds(duration?.average);
  $("#metric-duration-note").textContent = translateText(`${n(duration?.samples || 0)} llamadas finalizadas`);
  $("#outcome-total").textContent = n(c.total);
  const outcomes = Object.entries(data.outcomes).sort((a,b) => b[1] - a[1]);
  const outcomeLabels = outcomes.map(([key]) => ctx.labels[key] || key);
  chart("outcome-chart", "doughnut", {labels:outcomeLabels,datasets:[{data:outcomes.map(([,v]) => v),backgroundColor:colors(),borderWidth:3,borderColor:darkTheme()?"#1b1c19":"#ffffff",hoverOffset:4}]}, {cutout:"78%",plugins:{legend:{display:false},tooltip:{backgroundColor:"#171714",padding:12}}});
  ctx.setHTML($("#outcome-legend"), outcomes.map(([key,value],i) => `<button data-action="outcome-filter" data-status="${esc(key)}" class="legend-row series-${i % lightColors.length}"><span class="legend-dot" aria-hidden="true"></span><span>${esc(ctx.labels[key] || key)}</span><strong>${n(value)}</strong><small>${c.total ? Math.round(value / c.total * 100) : 0}%</small></button>`).join("") || '<p class="no-measurements">Los resultados aparecerán aquí.</p>');
  const daily = fillDays(data.daily);
  chart("trend-chart", "line", {labels:daily.map(d => `${d.date.slice(8,10)}/${d.date.slice(5,7)}`),datasets:[
    {label:t("Llamadas"),data:daily.map(d=>d.total),borderColor:colors()[0],backgroundColor:"#d9ff4324",fill:true},
    {label:t("Respuestas"),data:daily.map(d=>d.answered),borderColor:colors()[1]},
    {label:t("Con agente"),data:daily.map(d=>d.bridged),borderColor:colors()[2]}
  ].map(d => ({...d,borderWidth:2,pointRadius:daily.length < 3 ? 4 : 0,pointHoverRadius:5,tension:0.18}))});
  ctx.setHTML($("#trend-data"), table(["Fecha","Llamadas","Respuestas","Con agente"], daily.map(d=>[d.date,n(d.total),n(d.answered),n(d.bridged)])));
  bars("#connection-funnel", {attempted:c.attempted, answered:c.answered, transfer:c.transfer_requested, bridged:c.bridged}, localizedMap({attempted:"Marcaciones observadas",answered:"Cliente contesta",transfer:"Solicita agente · opción 2",bridged:"Conversación conectada"}), c.attempted);
  bars("#hangup-bars", data.hangup_actors, actors);
  bars("#amd-bars", data.amd, amd);
  bars("#duration-bars", data.duration_buckets, {});
  const timing = [["customer_pdd_seconds",t("Inicio del timbrado"),false],["customer_setup_seconds",t("Respuesta del cliente"),false],["tts_ms",t("Preparación del mensaje"),true],["agent_setup_seconds",t("Respuesta del agente"),false],["bridge_seconds",t("Conversación con agente"),false]];
  ctx.setHTML($("#timing-metrics"), timing.map(([key,label,ms])=>`<div><span>${label}</span><strong>${seconds(data.durations[key]?.average == null ? null : data.durations[key].average / (ms ? 1000 : 1))}</strong><small>${n(data.durations[key]?.samples || 0)} ${t("mediciones")}</small></div>`).join(""));
  ctx.setHTML($("#analytics-campaigns"), data.campaigns.length ? table(["Campaña","Llamadas","Respuestas","Con agente"], data.campaigns.map(c=>[`<button class="text-link table-link" data-action="select-campaign" data-id="${esc(c.id)}">${esc(c.name)}</button>`,n(c.total),n(c.answered),n(c.bridged)]),true) : '<p class="no-measurements">Las campañas con llamadas iniciadas aparecerán aquí.</p>');
  $("#report-scope").textContent = translateText(`${n(c.total)} llamadas en este período. Cada archivo puede incluir hasta ${n(ctx.state.status.report_max_rows)} registros y reúne resultados, tiempos y actividad.`);
}
function fillDays(items) {
  let from = query.get("date_from") || items[0]?.date;
  let to = query.get("date_to") || items.at(-1)?.date;
  if (!from || !to) return [];
  const start = Date.parse(`${from}T12:00:00Z`), end = Date.parse(`${to}T12:00:00Z`);
  if ((end - start) / 86400000 > 3660) return items;
  const map = new Map(items.map(d=>[d.date,d]));
  const result = [];
  for (let tick = start; tick <= end; tick += 86400000) {
    const date = new Date(tick).toISOString().slice(0,10);
    result.push(map.get(date) || {date,total:0,answered:0,bridged:0});
  }
  return result;
}
function table(headers, rows, html = false) {
  return `<table><thead><tr>${headers.map(h=>`<th scope="col">${esc(t(h))}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(v=>`<td>${html ? v : esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function renderCampaignOverview() {
  const campaigns = ctx.state.campaigns;
  if (!campaigns.length) {
    ctx.setHTML($("#campaign-overview"), `<div class="campaign-empty"><h2>Tu próxima conversación comienza aquí</h2><p>Crea una campaña con tus contactos y un mensaje personalizado. Al iniciar, podrás seguir cada llamada y analizar sus resultados.</p><button class="primary" data-action="new">Crear primera campaña</button>${ctx.state.status.mode === "simulation" ? '<button class="secondary" data-action="demo">Probar demostración</button>' : ""}</div>`);
    return;
  }
  ctx.setHTML($("#campaign-overview"), `<div class="campaign-list-table">${campaigns.map(c => {
    const done = Object.entries(c.counts).filter(([key]) => ctx.terminal.has(key)).reduce((sum,[,value])=>sum+value,0);
    return `<article class="campaign-summary-row"><div><button class="table-link" data-action="select-campaign" data-id="${esc(c.id)}">${esc(c.name)}</button><p>${t(c.mode === "sip" ? "En vivo" : "Prueba")} · ${translateText(`Envío ${c.lineage?.execution_number || 1}`)} · ${n(c.agent_numbers?.length || 1)} ${t("teléfonos de transferencia")}</p></div><div>${ctx.badge(c.display_status || c.status)}</div><div class="campaign-progress"><label>${n(done)} ${t("de")} ${n(c.total)} ${t("finalizadas")}</label><meter min="0" max="${c.total || 1}" value="${done}">${n(done)} ${t("de")} ${n(c.total)}</meter></div><div class="campaign-pending"><strong>${n(c.counts.queued || 0)}</strong><span>${t("pendientes")}</span></div><button class="secondary" data-action="select-campaign" data-id="${esc(c.id)}">${t("Abrir campaña")}</button></article>`;
  }).join("")}</div>`);
}
function callQuery() {
  const params = new URLSearchParams(query);
  if ($("#call-search").value.trim()) params.set("search",$("#call-search").value.trim());
  if ($("#call-status-filter").value) params.set("status",$("#call-status-filter").value);
  return params;
}
async function fetchCalls() {
  if (detailId) { await openDetail(detailId, false); return; }
  const limit = pageSize();
  const params = callQuery(); params.set("offset",offset); params.set("limit",limit);
  const version = ++request;
  const result = await ctx.api(`/api/calls?${params}`);
  if (version !== request || ctx.state.view !== "calls") return;
  contextLine(result.total);
  $("#cdr-detail").hidden = true; $("#calls-explorer").hidden = false;
  ctx.setHTML($("#cdr-rows"), result.items.map(row => `<tr><td><time datetime="${esc(row.started_at)}">${esc(time(row.started_at,true))}</time><span class="cell-meta">${esc(row.campaign_name)} · ${t("Intento")} ${n(row.attempt_number || 1)}</span></td><td><button class="contact-button" data-action="open-cdr" data-id="${esc(row.id)}">${esc(row.contact_name || row.phone)}${row.contact_name ? `<span>${esc(row.phone)}</span>` : ""}<span>${t("Crédito")} ${esc(row.credit_id || t("Sin crédito histórico"))}</span><span class="detail-affordance">${t("Ver detalle de llamada")}</span></button>${row.coverage === "legacy" ? `<span class="cell-meta">${t("Histórico")}</span>` : ""}</td><td><span class="trunk-cell">${esc(trunkLabel(row))}</span></td><td>${ctx.badge(row.status)}</td><td><span class="amd-text ${esc(row.amd_verdict)}">${esc(translateText(row.amd_label))}</span></td><td class="numeric">${seconds(row.customer_connected_seconds)}</td><td class="numeric">${seconds(row.bridge_seconds)}</td><td>${esc(actors[row.end_actor] || t("No identificado"))}</td></tr>`).join("") || `<tr><td colspan="8" class="table-empty">${t("No hay llamadas con estos filtros. Prueba otro período o resultado.")}</td></tr>`);
  $("#cdr-page-info").textContent = result.total ? `${n(offset + 1)}–${n(Math.min(offset + limit,result.total))} ${t("de")} ${n(result.total)}` : translateText("0 llamadas");
  $("#cdr-previous").disabled = offset === 0;
  $("#cdr-next").disabled = offset + limit >= result.total;
}

const eventNames = localizedMap({agent_pool_waiting:"Esperando un teléfono disponible",agent_pool_timeout:"No hubo un teléfono disponible",agent_selected:"Teléfono de transferencia seleccionado",route_selected:"Proveedor seleccionado",route_failover:"Cambio al proveedor de respaldo",recording_started:"Grabación iniciada",recording_ready:"Grabación disponible",created:"Llamada preparada",invite_sent:"Llamada enviada",response:"Respuesta del proveedor",ringing:"Timbrando",answered:"Llamada contestada",media_ready:"Audio disponible",identity:"Referencia asignada",termination:"Finalización iniciada",closed:"Llamada desconectada",dtmf:"Opción seleccionada",amd:"Respuesta identificada",tts_ready:"Mensaje personalizado listo",message_started:"Mensaje iniciado",message_completed:"Mensaje finalizado",repeat_requested:"Cliente solicita repetición",transfer_requested:"Cliente solicita agente",bridged:"Cliente y agente conectados",session_end:"Llamada finalizada",finalized:"Historial guardado",redirect_reported:"Llamada redirigida",refer_rejected:"No fue posible redirigir la llamada"});
const reasons = localizedMap({bye:"La otra persona finalizó",cancel:"Llamada cancelada",sip_response:"Respuesta final del proveedor",cleanup:"Cierre de la llamada",session_cleanup:"Fin de la llamada",campaign_stopped:"Campaña detenida",shutdown:"Blaster fue cerrado",process_interrupted:"Operación interrumpida",disconnected:"No se pudo identificar quién finalizó",machine:"Buzón probable",amd_unknown:"Respuesta no identificada",no_answer:"No hubo respuesta",no_input:"No seleccionó una opción",completed:"Recorrido completado",failed:"La llamada no se completó",temporary_error:"Proveedor no disponible",agent_timeout:"El agente no respondió a tiempo"});
async function openDetail(id, focus = true) {
  detailId = id;
  const result = await ctx.api(`/api/calls/${encodeURIComponent(id)}`);
  if (detailId !== id || ctx.state.view !== "calls") return;
  $("#calls-explorer").hidden = true; $("#cdr-detail").hidden = false;
  const legRows = result.legs.map(leg=>[t(leg.role.startsWith("customer") ? (leg.role === "customer" ? "Cliente" : "Cliente · intento previo") : "Agente"),leg.number,trunkIdLabel(leg.trunk_id,leg.trunk_name),time(leg.invite_at),time(leg.ringing_at),time(leg.answered_at),time(leg.ended_at),seconds(leg.connected_seconds),actors[leg.end_actor] || t("No identificado")]);
  const events = result.events.filter(event=>event.kind !== "identity");
  const roleById = Object.fromEntries(result.legs.map(leg=>[leg.id,t(leg.role.startsWith("customer") ? (leg.role === "customer" ? "Cliente" : "Cliente · intento previo") : "Agente")]));
  const history = events.map(event=> {
    const details = [];
    if (event.data.trunk_id) details.push(`${t("Proveedor")} ${trunkIdLabel(event.data.trunk_id)}`);
    if (event.data.next) details.push(`${trunkIdLabel(event.data.previous)} → ${trunkIdLabel(event.data.next)}`);
    if (event.data.digit) details.push(`${t("Tecla")} ${event.data.digit}`);
    if (event.data.verdict) details.push(amd[event.data.verdict]);
    if (event.data.actor) details.push(actors[event.data.actor] || t("Responsable no identificado"));
    if (event.data.reason) details.push(reasons[event.data.reason] || responseReasons[event.data.reason] || t("Motivo registrado"));
    if (event.data.evidence) details.push(ctx.commercialText(event.data.evidence));
    return `<li><time datetime="${esc(event.created_at)}">${esc(time(event.created_at))}</time><div><strong>${esc(eventNames[event.kind] || t("Actividad actualizada"))}</strong><p>${esc(details.join(" · "))}</p></div><span class="event-role">${esc(roleById[event.leg_id] || t("Llamada"))}</span></li>`;
  }).join("");
  const active = ctx.state.status.sessions.some(s=>s.id === id);
  const canChoose = ["playing","menu"].includes(result.status);
  const keypad = ctx.state.status.mode === "simulation" && active ? `<section class="detail-simulation"><h2>Probar esta llamada</h2><div class="report-actions"><button class="secondary" data-action="cdr-digit" data-value="1" ${canChoose ? "" : "disabled"}>1 · Repetir</button><button class="secondary" data-action="cdr-digit" data-value="2" ${canChoose ? "" : "disabled"}>2 · Agente</button><button class="danger-quiet" data-action="cdr-digit" data-value="hangup">Cliente cuelga</button>${result.agent_id ? '<button class="danger-quiet" data-action="cdr-digit" data-value="agent_hangup">Agente cuelga</button>' : ""}</div></section>` : "";
  const backLabel = t(detailOrigin === "traceability" ? "Volver al historial del cliente" : "Volver a las llamadas");
  ctx.setHTML($("#cdr-detail"), `<button class="text-link back-link" data-action="back-calls">${backLabel}</button><div class="section-heading"><div><h2 class="detail-title">${esc(result.contact_name || result.phone)}</h2><p>${esc(result.phone)} · ${t("Crédito")} ${esc(result.credit_id || t("Sin crédito histórico"))} · ${esc(result.campaign_name)} · ${t("Intento")} ${n(result.attempt_number || 1)}</p><p class="detail-route">${t("Proveedor:")} ${esc(trunkLabel(result))}</p></div>${ctx.badge(result.status)}</div>${result.coverage === "legacy" ? '<p class="coverage-note">Este registro conserva únicamente la información disponible en el momento de la llamada.</p>' : ""}<div class="detail-kpis"><div><span>Respuesta del cliente</span><strong>${result.customer_answered_at ? esc(time(result.customer_answered_at)) : "Sin información"}</strong><small>${esc(translateText(result.amd_label))}</small></div><div><span>Tiempo conectado</span><strong>${seconds(result.customer_connected_seconds)}</strong><small>Conversación con el cliente</small></div><div><span>Con agente</span><strong>${seconds(result.bridge_seconds)}</strong><small>${result.transfer_requested_at ? "Solicitado por el cliente · opción 2" : "No solicitó transferencia"}</small></div><div><span>Finalizó la llamada</span><strong>${esc(actors[result.end_actor])}</strong><small>${esc(reasons[result.end_reason] || "Sin información")}</small></div></div>${keypad}${recordingMarkup(result, ctx.state.user?.role)}<section class="chart-panel detail-legs"><h2>Etapas de la llamada</h2><div class="table-scroll">${legRows.length ? table(["Participante","Número","Proveedor","Inicio","Timbrado","Respuesta","Finalización","Tiempo conectado","Finalizó"],legRows) : '<p class="no-measurements">No hay etapas disponibles para esta llamada.</p>'}</div><p class="chart-footnote">${esc(time(result.started_at,true))} · ${esc(ctx.state.status.reporting_timezone)}. Cada intento conserva el proveedor utilizado, incluidos los cambios al respaldo.</p></section><div class="detail-bottom"><section class="chart-panel"><h2>Recorrido de la llamada</h2><ol class="call-timeline">${history || '<li>No hay actividad detallada disponible.</li>'}</ol><details class="history-details"><summary>Ver actividad completa (${result.history.length})</summary><ol class="event-list">${result.history.map(e=>`<li><strong>${esc(ctx.labels[e.status] || t("Actividad actualizada"))}</strong>${e.detail ? ` · ${esc(ctx.commercialText(e.detail))}` : ""}<time>${esc(time(e.created_at,true))}</time></li>`).join("")}</ol></details></section><aside class="evidence-panel"><h2>Información de seguimiento</h2><dl><dt>Crédito</dt><dd>${esc(result.credit_id || t("Sin crédito histórico"))}</dd><dt>Proveedor del cliente</dt><dd>${esc(trunkLabel(result))}</dd><dt>Proveedor de transferencia</dt><dd>${esc(trunkLabel(result,"agent"))}</dd><dt>Referencia de llamada</dt><dd>${esc(result.id)}</dd><dt>Referencia del contacto</dt><dd>${esc(result.contact_id)}</dd><dt>Intento anterior</dt><dd>${result.retry_of ? `<button class="text-link" data-action="open-cdr" data-id="${esc(result.retry_of)}">Ver intento anterior</button>` : "Primera llamada"}</dd><dt>Información disponible</dt><dd>${result.coverage === "legacy" ? "Registro anterior" : "Registro completo"}</dd><dt>Tipo de respuesta</dt><dd>${esc(translateText(result.amd_label))}${result.amd_reason ? ` · ${esc(responseReasons[result.amd_reason] || t("Motivo registrado"))}` : ""}</dd><dt>Tiempo para identificar la respuesta</dt><dd>${result.amd_elapsed_ms == null ? "—" : seconds(result.amd_elapsed_ms/1000)}</dd><dt>Preparación del mensaje</dt><dd>${result.tts_ms == null ? "—" : seconds(result.tts_ms/1000)}</dd><dt>Repeticiones</dt><dd>${n(result.replays)}</dd><dt>Finalización</dt><dd>${esc(ctx.commercialText(result.end_evidence || "No identificada"))}</dd><dt>Resultado final</dt><dd>${esc(ctx.commercialText(result.detail))}</dd></dl></aside></div>`);
  if (focus) { $("#cdr-detail").focus({preventScroll:true}); $("#cdr-detail").scrollIntoView({block:"start"}); }
}

async function download(format) {
  if (downloaded) return;
  downloaded = true;
  const buttons = [...document.querySelectorAll('[data-action="download-xlsx"], [data-action="download-csv"]')];
  buttons.forEach(b=>b.disabled=true);
  $("#report-progress").textContent = t("Preparando el archivo… Las llamadas continúan en segundo plano.");
  try {
    const params = ctx.state.view === "calls" ? callQuery() : new URLSearchParams(query);
    params.set("lang", getLanguage());
    const response = await fetch(`/api/reports/${format}?${params}`, {headers:{"Accept-Language":getLanguage()}});
    if (!response.ok) { const error = await response.json(); throw new Error(ctx.commercialError(error.detail || "No fue posible generar el reporte.")); }
    const url = URL.createObjectURL(await response.blob()), anchor = document.createElement("a");
    anchor.href = url; anchor.download = `blaster-${dayInZone()}.${format}`;
    anchor.click(); setTimeout(()=>URL.revokeObjectURL(url),10000);
    $("#report-progress").textContent = t("Archivo generado. La descarga está lista.");
  } catch(error) { $("#report-progress").textContent = t("No se pudo generar el archivo."); throw error; }
  finally { downloaded = false; buttons.forEach(b=>b.disabled=false); }
}

export async function analyticsAction(name, element) {
  if (["nav-dashboard","nav-campaigns","nav-calls","nav-reports","nav-operations"].includes(name)) {
    ++request; detailId = null; detailOrigin = "calls"; detailOriginId = null;
    ctx.view(name.slice(4)); await analyticsRefresh(true); return true;
  }
  if (name === "outcome-filter") {
    $("#call-status-filter").value = element.dataset.status; $("#call-search").value = "";
    detailId = null; offset = 0; ctx.view("calls"); await fetchCalls(); return true;
  }
  if (name === "open-cdr") {
    if (ctx.state.view !== "calls") {
      detailOrigin = element.dataset.origin || "calls";
      detailOriginId = element.dataset.id;
    }
    ctx.view("calls"); await openDetail(element.dataset.id); return true;
  }
  if (name === "back-calls") {
    stopRecordings(); detailId = null;
    if (detailOrigin === "traceability") {
      const originId = detailOriginId;
      ctx.view("traceability");
      document.dispatchEvent(new CustomEvent("traceability:restore", {detail:{id:originId}}));
      return true;
    }
    await fetchCalls(); $("#call-search").focus(); return true;
  }
  if (name === "cdr-previous" || name === "cdr-next") { offset = Math.max(0,offset+(name === "cdr-next" ? pageSize() : -pageSize())); await fetchCalls(); return true; }
  if (name === "cdr-digit") { await ctx.api(`/api/jobs/${detailId}/simulate`, {action:element.dataset.value}); await ctx.refresh(); await openDetail(detailId,false); return true; }
  if (name === "download-xlsx" || name === "download-csv") { await download(name.slice(9)); return true; }
  return false;
}
