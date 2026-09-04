const $ = s => document.querySelector(s);
const number = new Intl.NumberFormat("es-MX");
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const n = value => value == null ? "—" : number.format(value);
const pct = value => value == null ? "Sin base de cálculo" : `${(value * 100).toFixed(1)} %`;
const pageSize = () => matchMedia("(max-width:680px)").matches ? 25 : 50;
const seconds = value => value == null ? "—" : value < 60 ? `${value.toFixed(1)} s` : `${Math.floor(value / 60)} min ${Math.round(value % 60)} s`;
const actors = {customer:"Cliente", agent:"Agente", system:"Sistema", operator:"Operador local", trunk:"Troncal", unknown:"Desconocido"};
const amd = {human:"Humano probable", machine:"Buzón probable", unknown:"Incierto", pending:"Sin resultado", disabled:"Desactivado", unmeasured:"Sin medición histórica"};
const colors = ["#176278", "#39987d", "#ca9134", "#8499ab", "#b86666", "#756996", "#9aab9a", "#b48962", "#446477"];
let ctx, initialized = false, lastFetch = 0, request = 0, offset = 0, detailId = null, summary = null, downloaded = false;
let query = new URLSearchParams(), charts = new Map();
const labels = {dashboard:"El pulso de tus llamadas", calls:"Todas las llamadas", reports:"Reportes y exportaciones"};

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
  if ($("#filter-from").value && $("#filter-to").value && $("#filter-from").value > $("#filter-to").value) throw new Error("La fecha inicial debe ser anterior o igual a la final.");
  query = currentFilters(); offset = 0; detailId = null; lastFetch = 0;
  ctx.notice(); await analyticsRefresh(true);
}
function time(value, full = false) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("es-MX", {timeZone:ctx.state.status?.reporting_timezone || "America/Mexico_City", ...(full ? {day:"2-digit", month:"short", year:"numeric"} : {}),hour:"2-digit", minute:"2-digit", second:"2-digit", hour12:false}).format(new Date(value));
}

export function analyticsView(name) {
  const enabled = ["dashboard", "calls", "reports"].includes(name);
  for (const id of ["analytics-heading", "analytics-filters", "analytics-context"]) $(`#${id}`).hidden = !enabled;
  $(".capacity-strip").hidden = !["campaign", "editor", "empty"].includes(name);
  $("#analytics-title").textContent = labels[name] || "";
  $("#analytics-subtitle").textContent = name === "calls" ? "Cada respuesta, transferencia y finalización, en un solo registro." : name === "reports" ? "Convierte el recorrido de tus llamadas en información útil." : "De la primera marcación a la conversación con tu agente.";
  const nav = ["campaign", "editor", "empty"].includes(name) ? "campaigns" : name;
  document.querySelectorAll(".primary-nav button").forEach(button => {
    if (button.dataset.action === `nav-${nav}`) button.setAttribute("aria-current","page"); else button.removeAttribute("aria-current");
  });
  $(".topbar-title").textContent = {dashboard:"Dashboard",campaigns:"Campañas",calls:"Llamadas / CDR",reports:"Reportes",operations:"Operación"}[nav];
  document.title = `Blaster · ${$(".topbar-title").textContent}`;
  lastFetch = 0;
}

export async function analyticsRefresh(force = false) {
  if (!ctx.state.status) return;
  if (!initialized) {
    initialized = true; $("#filter-mode").value = ctx.state.status.mode;
    dates("30"); query = currentFilters();
  }
  $("#live-count").textContent = `${ctx.state.status.active_sessions} en curso`;
  const selector = $("#filter-campaign"), old = selector.value;
  const options = '<option value="">Todas las campañas</option>' + ctx.state.campaigns.map(c => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join("");
  if (selector._options !== options) { selector.innerHTML = options; selector._options = options; selector.value = old; }
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
  const mode = {sip:"SIP real",simulation:"Simulación",all:"SIP y simulación"}[query.get("mode")];
  $("#filter-description").textContent = `${n(total)} sesiones · ${mode} · ${ctx.state.status.reporting_timezone}`;
  $("#analytics-updated").textContent = `Actualizado ${time(new Date().toISOString())}`;
}
function chart(id, type, data, options = {}) {
  const signature = JSON.stringify({data, options});
  const existing = charts.get(id);
  if (existing?.signature === signature) { existing.instance.resize(); return; }
  existing?.instance.destroy();
  const instance = new window.Chart($("#" + id), {type, data, options: {
    responsive:true, maintainAspectRatio:false, animation:false,
    interaction:{mode:"index",intersect:false},
    plugins:{legend:{position:"bottom", align:"start", labels:{usePointStyle:true,pointStyle:"circle",boxWidth:7,boxHeight:7,padding:20,color:"#536b76",font:{size:11}}},tooltip:{backgroundColor:"#203841",padding:12,cornerRadius:6}},
    scales:type === "doughnut" ? {} : {x:{grid:{display:false},border:{display:false},ticks:{maxTicksLimit:7,maxRotation:0,color:"#536b76",font:{size:11}}},y:{beginAtZero:true,border:{display:false},grid:{color:"#eaf0f3"},ticks:{precision:0,maxTicksLimit:5,color:"#536b76",font:{size:11}}}},
    ...options
  }});
  charts.set(id, {signature, instance});
}
function bars(id, values, names, maximum = null) {
  const entries = Object.entries(values), max = maximum || Math.max(1, ...Object.values(values));
  ctx.setHTML($(id), entries.length ? entries.map(([key,value],i) => `<div class="bar-row series-${i % colors.length}"><div><span>${esc(names[key] || key)}</span><strong>${n(value)}</strong></div><meter min="0" max="${max}" value="${value}" aria-label="${esc(names[key] || key)}">${value} de ${max}</meter></div>`).join("") : '<p class="no-measurements">Sin mediciones en este período.</p>');
}
function renderSummary(data) {
  const c = data.counts; contextLine(c.total);
  $("#analytics-empty").hidden = c.total > 0;
  $("#coverage-note").hidden = c.legacy === 0;
  $("#coverage-note").textContent = `${n(c.legacy)} registros históricos conservan su resultado original. Las tasas y los tiempos utilizan únicamente evidencia capturada; los datos faltantes aparecen como «—».`;
  $("#metric-total").textContent = n(c.total);
  $("#metric-total-note").textContent = `${n(c.attempted)} INVITE observados · ${n(c.active)} en curso`;
  $("#metric-answer").textContent = n(c.answered);
  $("#metric-answer-note").textContent = `${pct(data.answer_rate)} de respuesta · incluye buzones`;
  $("#metric-bridge").textContent = n(c.bridged);
  $("#metric-bridge-note").textContent = `${n(c.transfer_requested)} solicitudes · ${pct(data.transfer_rate)}`;
  const duration = data.durations.customer_connected_seconds;
  $("#metric-duration").textContent = seconds(duration?.average);
  $("#metric-duration-note").textContent = `${n(duration?.samples || 0)} tramos con fin observado`;
  $("#outcome-total").textContent = n(c.total);
  const outcomes = Object.entries(data.outcomes).sort((a,b) => b[1] - a[1]);
  const outcomeLabels = outcomes.map(([key]) => ctx.labels[key] || key);
  chart("outcome-chart", "doughnut", {labels:outcomeLabels,datasets:[{data:outcomes.map(([,v]) => v),backgroundColor:colors,borderWidth:3,borderColor:"#fff",hoverOffset:4}]}, {cutout:"78%",plugins:{legend:{display:false},tooltip:{backgroundColor:"#203841",padding:12}}});
  ctx.setHTML($("#outcome-legend"), outcomes.map(([key,value],i) => `<button data-action="outcome-filter" data-status="${esc(key)}" class="legend-row series-${i % colors.length}"><span class="legend-dot" aria-hidden="true"></span><span>${esc(ctx.labels[key] || key)}</span><strong>${n(value)}</strong><small>${c.total ? Math.round(value / c.total * 100) : 0}%</small></button>`).join("") || '<p class="no-measurements">Los resultados aparecerán aquí.</p>');
  const daily = fillDays(data.daily);
  chart("trend-chart", "line", {labels:daily.map(d => `${d.date.slice(8,10)}/${d.date.slice(5,7)}`),datasets:[
    {label:"Sesiones",data:daily.map(d=>d.total),borderColor:colors[0],backgroundColor:"#17627812",fill:true},
    {label:"Respuestas",data:daily.map(d=>d.answered),borderColor:colors[1]},
    {label:"Con agente",data:daily.map(d=>d.bridged),borderColor:colors[2]}
  ].map(d => ({...d,borderWidth:2,pointRadius:daily.length < 3 ? 4 : 0,pointHoverRadius:5,tension:0.18}))});
  ctx.setHTML($("#trend-data"), table(["Fecha","Sesiones","Respuestas","Con agente"], daily.map(d=>[d.date,n(d.total),n(d.answered),n(d.bridged)])));
  bars("#connection-funnel", {attempted:c.attempted, answered:c.answered, transfer:c.transfer_requested, bridged:c.bridged}, {attempted:"Marcaciones observadas",answered:"Cliente contesta",transfer:"Solicita agente · opción 2",bridged:"Conversación conectada"}, c.attempted);
  bars("#hangup-bars", data.hangup_actors, actors);
  bars("#amd-bars", data.amd, amd);
  bars("#duration-bars", data.duration_buckets, {});
  const timing = [["customer_pdd_seconds","Hasta timbrado",false],["customer_setup_seconds","Hasta respuesta",false],["tts_ms","Generación de voz",true],["agent_setup_seconds","Respuesta del agente",false],["bridge_seconds","Conversación en puente",false]];
  ctx.setHTML($("#timing-metrics"), timing.map(([key,label,ms])=>`<div><span>${label}</span><strong>${seconds(data.durations[key]?.average == null ? null : data.durations[key].average / (ms ? 1000 : 1))}</strong><small>${n(data.durations[key]?.samples || 0)} mediciones</small></div>`).join(""));
  ctx.setHTML($("#analytics-campaigns"), data.campaigns.length ? table(["Campaña","Sesiones","Respuestas","Con agente"], data.campaigns.map(c=>[`<button class="text-link table-link" data-action="select-campaign" data-id="${esc(c.id)}">${esc(c.name)}</button>`,n(c.total),n(c.answered),n(c.bridged)]),true) : '<p class="no-measurements">Las campañas con llamadas iniciadas aparecerán aquí.</p>');
  $("#report-scope").textContent = `${n(c.total)} sesiones en este corte. Máximo por archivo: ${n(ctx.state.status.report_max_rows)}. El Excel incluye CDRs, tramos y eventos.`;
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
  return `<table><thead><tr>${headers.map(h=>`<th scope="col">${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(v=>`<td>${html ? v : esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function renderCampaignOverview() {
  const campaigns = ctx.state.campaigns;
  if (!campaigns.length) {
    ctx.setHTML($("#campaign-overview"), `<div class="campaign-empty"><h2>Tu próxima conversación comienza aquí</h2><p>Crea una campaña con tus contactos y un mensaje personalizado. Al iniciar, podrás seguir cada llamada y analizar sus resultados.</p><button class="primary" data-action="new">Crear primera campaña</button>${ctx.state.status.mode === "simulation" ? '<button class="secondary" data-action="demo">Probar demostración</button>' : ""}</div>`);
    return;
  }
  ctx.setHTML($("#campaign-overview"), `<div class="campaign-list-table">${campaigns.map(c => {
    const done = Object.entries(c.counts).filter(([key]) => ctx.terminal.has(key)).reduce((sum,[,value])=>sum+value,0);
    return `<article class="campaign-summary-row"><div><button class="table-link" data-action="select-campaign" data-id="${esc(c.id)}">${esc(c.name)}</button><p>${c.mode === "sip" ? "SIP real" : "Simulación"} · Agente ${esc(c.agent_number)}</p></div><div>${ctx.badge(c.status)}</div><div class="campaign-progress"><label>${n(done)} de ${n(c.total)} finalizadas</label><meter min="0" max="${c.total || 1}" value="${done}">${n(done)} de ${n(c.total)}</meter></div><div class="campaign-pending"><strong>${n(c.counts.queued || 0)}</strong><span>pendientes</span></div><button class="secondary" data-action="select-campaign" data-id="${esc(c.id)}">Abrir campaña</button></article>`;
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
  ctx.setHTML($("#cdr-rows"), result.items.map(row => `<tr><td><time datetime="${esc(row.started_at)}">${esc(time(row.started_at,true))}</time><span class="cell-meta">${esc(row.campaign_name)}</span></td><td><button class="contact-button" data-action="open-cdr" data-id="${esc(row.id)}">${esc(row.contact_name || row.phone)}${row.contact_name ? `<span>${esc(row.phone)}</span>` : ""}<span class="detail-affordance">Ver detalle de llamada</span></button>${row.coverage === "legacy" ? '<span class="cell-meta">Histórico</span>' : ""}</td><td>${ctx.badge(row.status)}</td><td><span class="amd-text ${esc(row.amd_verdict)}">${esc(row.amd_label)}</span></td><td class="numeric">${seconds(row.customer_connected_seconds)}</td><td class="numeric">${seconds(row.bridge_seconds)}</td><td>${esc(actors[row.end_actor] || "Desconocido")}</td></tr>`).join("") || '<tr><td colspan="7" class="table-empty">No hay llamadas con estos filtros. Prueba otro período o resultado.</td></tr>');
  $("#cdr-page-info").textContent = result.total ? `${n(offset + 1)}–${n(Math.min(offset + limit,result.total))} de ${n(result.total)}` : "0 llamadas";
  $("#cdr-previous").disabled = offset === 0;
  $("#cdr-next").disabled = offset + limit >= result.total;
}

const eventNames = {route_selected:"Ruta seleccionada",route_failover:"Cambio a respaldo",recording_started:"Grabación iniciada",recording_ready:"Audio comprimido disponible",created:"Tramo creado",invite_sent:"INVITE enviado",response:"Respuesta de la troncal",ringing:"Timbrando",answered:"Llamada contestada",media_ready:"Audio activo",identity:"Identificador SIP asignado",termination:"Inicio de finalización",closed:"Tramo desconectado",dtmf:"Opción de teclado recibida",amd:"Análisis del saludo",tts_ready:"Voz personalizada lista",message_started:"Reproducción iniciada",message_completed:"Reproducción completada",repeat_requested:"Cliente solicita repetición",transfer_requested:"Cliente solicita agente",bridged:"Cliente y agente enlazados",session_end:"Finalización de sesión",finalized:"CDR cerrado",redirect_reported:"Redirección SIP informada",refer_rejected:"Solicitud REFER rechazada"};
const reasons = {bye:"Cuelgue remoto",cancel:"Cancelación remota",sip_response:"Respuesta SIP final",cleanup:"Limpieza del tramo",session_cleanup:"Final de sesión",campaign_stopped:"Campaña detenida",shutdown:"Aplicación cerrada",process_interrupted:"Proceso interrumpido",disconnected:"Desconexión sin iniciador identificado",machine:"Buzón probable",amd_unknown:"AMD incierto",no_answer:"Tiempo de timbrado agotado",no_input:"No seleccionó una opción",completed:"Flujo finalizado",failed:"Error en el flujo",agent_timeout:"Tiempo de espera del agente agotado"};
function recordingMarkup(result) {
  const r = result.recording;
  if (!r) return '<p class="chart-footnote">Sin grabación: no se registró evidencia de voz humana o la captura estaba desactivada.</p>';
  const status = {recording:"Grabando",encoding:"Comprimiendo",ready:"Lista",expired:"Venció la conservación",failed:"No disponible"}[r.status] || r.status;
  const allowed = ctx.state.user?.role !== "analyst";
  return `<section class="recording-panel"><div><h2>Grabación · ${esc(status)}</h2><p>${r.evidence === "amd_human_probable" ? "Desde la detección de humano probable" : "Desde la interacción del teclado"}${result.mode === "simulation" ? " · audio sintético de simulación" : ""} · Ogg Opus${r.size_bytes ? ` · ${(r.size_bytes/1024).toFixed(0)} KB` : ""}</p></div>${r.status === "ready" && allowed ? `<audio controls preload="none" src="/api/recordings/${encodeURIComponent(result.id)}" aria-label="Grabación de la llamada"></audio><a class="text-link" download href="/api/recordings/${encodeURIComponent(result.id)}">Descargar audio</a>` : `<p>${esc(r.detail || (allowed ? "" : "Tu rol no permite escuchar grabaciones."))}</p>`}</section>`;
}
async function openDetail(id, focus = true) {
  detailId = id;
  const result = await ctx.api(`/api/calls/${encodeURIComponent(id)}`);
  if (detailId !== id || ctx.state.view !== "calls") return;
  $("#calls-explorer").hidden = true; $("#cdr-detail").hidden = false;
  const legRows = result.legs.map(leg=>[leg.role.startsWith("customer") ? (leg.role === "customer" ? "Cliente" : "Cliente · intento previo") : "Agente",leg.number,leg.trunk_id || "—",time(leg.invite_at),time(leg.ringing_at),time(leg.answered_at),time(leg.ended_at),seconds(leg.connected_seconds),actors[leg.end_actor] || "Desconocido",leg.sip_code || "—"]);
  const events = result.events.filter(event=>event.kind !== "identity");
  const roleById = Object.fromEntries(result.legs.map(leg=>[leg.id,leg.role.startsWith("customer") ? (leg.role === "customer" ? "Cliente" : "Cliente · intento previo") : "Agente"]));
  const history = events.map(event=> {
    const details = [];
    if (event.data.trunk_id) details.push(`Troncal ${event.data.trunk_id}`);
    if (event.data.next) details.push(`${event.data.previous} → ${event.data.next}`);
    if (event.data.code) details.push(`SIP ${event.data.code}`);
    if (event.data.digit) details.push(`Tecla ${event.data.digit}`);
    if (event.data.verdict) details.push(amd[event.data.verdict]);
    if (event.data.actor) details.push(actors[event.data.actor] || event.data.actor);
    if (event.data.reason) details.push(reasons[event.data.reason] || event.data.reason);
    if (event.data.evidence) details.push(event.data.evidence);
    return `<li><time datetime="${esc(event.created_at)}">${esc(time(event.created_at))}</time><div><strong>${esc(eventNames[event.kind] || event.kind)}</strong><p>${esc(details.join(" · "))}</p></div><span class="event-role">${esc(roleById[event.leg_id] || "Sesión")}</span></li>`;
  }).join("");
  const active = ctx.state.status.sessions.some(s=>s.id === id);
  const canChoose = ["playing","menu"].includes(result.status);
  const keypad = ctx.state.status.mode === "simulation" && active ? `<section class="detail-simulation"><h2>Probar esta llamada</h2><div class="report-actions"><button class="secondary" data-action="cdr-digit" data-value="1" ${canChoose ? "" : "disabled"}>1 · Repetir</button><button class="secondary" data-action="cdr-digit" data-value="2" ${canChoose ? "" : "disabled"}>2 · Agente</button><button class="danger-quiet" data-action="cdr-digit" data-value="hangup">Cliente cuelga</button>${result.agent_id ? '<button class="danger-quiet" data-action="cdr-digit" data-value="agent_hangup">Agente cuelga</button>' : ""}</div></section>` : "";
  ctx.setHTML($("#cdr-detail"), `<button class="text-link back-link" data-action="back-calls">Volver a las llamadas</button><div class="section-heading"><div><h2 class="detail-title">${esc(result.contact_name || result.phone)}</h2><p>${esc(result.phone)} · ${esc(result.campaign_name)}</p></div>${ctx.badge(result.status)}</div>${result.coverage === "legacy" ? '<p class="coverage-note">Registro histórico. Sólo se dispone de los estados operativos guardados antes de incorporar la telemetría.</p>' : ""}<div class="detail-kpis"><div><span>Respuesta del cliente</span><strong>${result.customer_answered_at ? esc(time(result.customer_answered_at)) : "Sin evidencia"}</strong><small>${esc(result.amd_label)}</small></div><div><span>Conectado</span><strong>${seconds(result.customer_connected_seconds)}</strong><small>Tramo del cliente</small></div><div><span>Con agente</span><strong>${seconds(result.bridge_seconds)}</strong><small>${result.transfer_requested_at ? "Solicitado por el cliente · opción 2" : "Sin solicitud observada"}</small></div><div><span>Finalizó la sesión</span><strong>${esc(actors[result.end_actor])}</strong><small>${esc(reasons[result.end_reason] || result.end_reason || "Sin evidencia")}</small></div></div>${keypad}${recordingMarkup(result)}<section class="chart-panel detail-legs"><h2>Tramos de la llamada</h2><div class="table-scroll">${legRows.length ? table(["Tramo","Número","Troncal","INVITE","Timbrado","Respuesta","Desconexión","Conectado","Finalizó","SIP"],legRows) : '<p class="no-measurements">No se guardaron tramos para este registro.</p>'}</div><p class="chart-footnote">${esc(time(result.started_at,true))} · ${esc(ctx.state.status.reporting_timezone)}. La identidad real o un desvío interno de la troncal pueden no ser observables.</p></section><div class="detail-bottom"><section class="chart-panel"><h2>Recorrido de la llamada</h2><ol class="call-timeline">${history || '<li>Sin eventos detallados disponibles.</li>'}</ol><details class="history-details"><summary>Ver estados operativos (${result.history.length})</summary><ol class="event-list">${result.history.map(e=>`<li><strong>${esc(ctx.labels[e.status] || e.status)}</strong> · ${esc(e.detail)}<time>${esc(time(e.created_at,true))}</time></li>`).join("")}</ol></details></section><aside class="evidence-panel"><h2>Evidencia y mediciones</h2><dl><dt>ID de llamada</dt><dd>${esc(result.id)}</dd><dt>Cobertura</dt><dd>${result.coverage === "legacy" ? "Histórica, sin telemetría" : "Telemetría de esta versión"}</dd><dt>Clasificación AMD</dt><dd>${esc(result.amd_label)}${result.amd_reason ? ` · ${esc(result.amd_reason)}` : ""}</dd><dt>Tiempo de análisis</dt><dd>${result.amd_elapsed_ms == null ? "—" : seconds(result.amd_elapsed_ms/1000)}</dd><dt>Generación TTS</dt><dd>${result.tts_ms == null ? "—" : seconds(result.tts_ms/1000)}</dd><dt>Repeticiones</dt><dd>${n(result.replays)}</dd><dt>Evidencia de finalización</dt><dd>${esc(result.end_evidence || "Desconocida")}</dd>${result.legs.map(leg=>`<dt>Call-ID ${leg.role.startsWith("customer") ? "cliente" : "agente"}</dt><dd>${esc(leg.call_id || "No disponible")}</dd>`).join("")}<dt>Resultado operativo</dt><dd>${esc(result.detail)}</dd></dl></aside></div>`);
  if (focus) { $("#cdr-detail").focus({preventScroll:true}); $("#cdr-detail").scrollIntoView({block:"start"}); }
}

async function download(format) {
  if (downloaded) return;
  downloaded = true;
  const buttons = [...document.querySelectorAll('[data-action="download-xlsx"], [data-action="download-csv"]')];
  buttons.forEach(b=>b.disabled=true);
  $("#report-progress").textContent = "Preparando el archivo… Las llamadas continúan en segundo plano.";
  try {
    const params = ctx.state.view === "calls" ? callQuery() : query;
    const response = await fetch(`/api/reports/${format}?${params}`);
    if (!response.ok) { const error = await response.json(); throw new Error(error.detail || "No fue posible generar el reporte."); }
    const url = URL.createObjectURL(await response.blob()), anchor = document.createElement("a");
    anchor.href = url; anchor.download = `blaster-${dayInZone()}.${format}`;
    anchor.click(); setTimeout(()=>URL.revokeObjectURL(url),10000);
    $("#report-progress").textContent = "Archivo generado. La descarga está lista.";
  } catch(error) { $("#report-progress").textContent = "No se pudo generar el archivo."; throw error; }
  finally { downloaded = false; buttons.forEach(b=>b.disabled=false); }
}

export async function analyticsAction(name, element) {
  if (name.startsWith("nav-")) {
    ++request; detailId = null; ctx.view(name.slice(4)); await analyticsRefresh(true); return true;
  }
  if (name === "outcome-filter") {
    $("#call-status-filter").value = element.dataset.status; $("#call-search").value = "";
    detailId = null; offset = 0; ctx.view("calls"); await fetchCalls(); return true;
  }
  if (name === "open-cdr") { ctx.view("calls"); await openDetail(element.dataset.id); return true; }
  if (name === "back-calls") { detailId = null; await fetchCalls(); $("#call-search").focus(); return true; }
  if (name === "cdr-previous" || name === "cdr-next") { offset = Math.max(0,offset+(name === "cdr-next" ? pageSize() : -pageSize())); await fetchCalls(); return true; }
  if (name === "cdr-digit") { await ctx.api(`/api/jobs/${detailId}/simulate`, {action:element.dataset.value}); await ctx.refresh(); await openDetail(detailId,false); return true; }
  if (name === "download-xlsx" || name === "download-csv") { await download(name.slice(9)); return true; }
  return false;
}
