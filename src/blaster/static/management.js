import { stopRecordings } from "./recording-player.js";

"use strict";
import { loadCountries, countryOptions, applyTemplateAgent } from "./countries.js";
import { strategyNames } from "./agent-pool.js";
import { locale, t, translateHTML, translateText } from "./i18n.js";
let ctx, tab = "trunks", cache = {}, setup = false, auditOffset = 0;
let calibrationFilter = "pending", calibrationSelected = null, calibrationOffset = 0;
const voiceUrls = new Map();
const $ = s => document.querySelector(s);
const esc = value => ctx.escapeHTML(value);
const localizedMap = source => Object.fromEntries(Object.entries(source).map(([key,value])=>[key,t(value)]));
const names = localizedMap({trunks:"Proveedores",voices:"Voces",templates:"Plantillas",schedules:"Historial de programación",automatic:"Reportes automáticos",alerts:"Alertas",calibration:"Revisión de respuestas",config:"Configuración",users:"Usuarios",audit:"Actividad de usuarios"});
const descriptions = localizedMap({trunks:"Define el orden, la distribución y la capacidad de tus proveedores de llamadas.",voices:"Compara el tiempo de preparación y elige la voz más adecuada para tus campañas.",templates:"Mensajes reutilizables con los datos personalizados de tus contactos.",schedules:"Consulta los horarios y cancela los pendientes. Las nuevas programaciones se definen al crear la campaña.",automatic:"Reportes diarios o semanales listos para descargar.",alerts:"Situaciones y reportes que requieren tu atención.",calibration:"Escucha el saludo inicial y confirma si respondió una persona o un buzón.",config:"Capacidad, tiempos de atención, grabaciones y conservación.",users:"Define quién administra, opera o consulta la plataforma.",audit:"Consulta las acciones realizadas, con fecha y responsable."});
const stateNames = localizedMap({pending:"Pendiente",started:"Iniciada",cancelled:"Cancelada",missed:"Horario vencido",skipped:"Omitida",failed:"Fallida",ready:"Disponible",running:"Generando",expired:"Vencido"});
const amdVerdicts = localizedMap({human:"Persona",machine:"Buzón",unknown:"Incierto"});
const amdReasons = localizedMap({short_greeting:"Saludo breve seguido de una pausa",long_greeting:"Saludo prolongado",many_words:"Saludo con varias frases",beep:"Tono de buzón",initial_silence:"No se escuchó un saludo",analysis_timeout:"No fue posible identificar la respuesta a tiempo",no_audio:"No se recibió voz",audio_overflow:"La recepción de voz se interrumpió",invalid_audio:"No fue posible reconocer el audio"});
const scheduleDetail = row => translateText(row.detail || (row.state === "pending" ? "Esperando horario y disponibilidad" : row.state === "cancelled" ? "No se ejecutará en este horario" : "Sin información adicional"));
const zone = () => ctx.state.status?.reporting_timezone || "America/Mexico_City";
export const formatTimestamp = (value,timeZone) => value ? new Intl.DateTimeFormat(locale(), {timeZone,dateStyle:"medium",timeStyle:"short"}).format(new Date(value)) : "—";
const stamp = (value,timeZone=zone()) => formatTimestamp(value,timeZone);
const zonedStamp = value => `${stamp(value)} · ${zone()}`;
const admin = () => ctx.state.user?.role === "admin";
const write = () => ctx.state.user?.role !== "analyst";
const action = (label, kind, id="", cls="text-link") => `<button type="button" class="${cls}" data-action="${kind}" data-id="${esc(id)}">${esc(t(label))}</button>`;
const empty = text => `<p class="ops-empty">${esc(t(text))}</p>`;
const field = (key,label,value="",type="text",extra="",help="") => `<div class="ops-field"><label for="m-${key}">${esc(t(label))}</label><input id="m-${key}" name="${key}" type="${type}" value="${esc(value)}" ${extra}>${help ? `<small>${esc(t(help))}</small>` : ""}</div>`;
const select = (key,label,value,options) => `<div class="ops-field"><label for="m-${key}">${esc(t(label))}</label><select id="m-${key}" name="${key}">${options.map(([id,text])=>`<option value="${esc(id)}" ${String(value)===String(id)?"selected":""}>${esc(t(text))}</option>`).join("")}</select></div>`;
const check = (key,label,value) => `<label class="ops-check"><input type="checkbox" name="${key}" ${value?"checked":""}>${esc(t(label))}</label>`;
const buttons = label => `<div class="ops-form-actions"><button type="submit" class="primary">${t(label)}</button>${action("Cancelar edición","ops-refresh")}</div>`;
function form(kind,title,content,id="") { return `<form class="ops-form" data-manage-form="${kind}" data-id="${esc(id)}"><h2>${t(title)}</h2>${content}</form>`; }
function templatePoolFields(edit) {
  const numbers = edit?.agent_numbers_national || (edit?.agent_number ? [edit.agent_national || edit.agent_number] : []);
  return `<div class="ops-grid">${select("agent_country","País de los agentes",edit?.agent_country||"MX",countryOptions())}${select("agent_strategy","Forma de asignación",edit?.agent_strategy||"round_robin",Object.entries(strategyNames))}${field("agent_pool_wait","Espera cuando todos están ocupados (segundos)",edit?.agent_pool_wait??30,"number",'min="0" max="300" step="1" required')}</div><label for="m-agent_numbers_text">Teléfonos de transferencia (opcional)</label><textarea id="m-agent_numbers_text" name="agent_numbers_text" rows="3" maxlength="4000" spellcheck="false">${esc(numbers.join("\n"))}</textarea><p class="field-help">Agrega un número nacional por línea. Puedes incluir hasta 50 agentes, con una llamada activa por teléfono. Usa 0 segundos para finalizar la transferencia si todos están ocupados.</p>`;
}
function cards(items,render,text) { return items.length ? `<div class="ops-records">${items.map(render).join("")}</div>` : empty(text); }
const record = (title,summary,body,controls="") => `<article class="ops-record"><div class="ops-record-head"><div><h2>${esc(t(title))}</h2><p>${esc(translateText(summary))}</p></div><div class="ops-row-actions">${controls}</div></div>${body}</article>`;
const values = entries => `<dl class="ops-values">${entries.map(([a,b])=>`<div><dt>${esc(t(a))}</dt><dd>${esc(translateText(b))}</dd></div>`).join("")}</dl>`;
function clearVoiceAudio() { for(const url of voiceUrls.values()) URL.revokeObjectURL(url); voiceUrls.clear(); }
function rememberVoiceAudio(item) {
  if(!item.audio_base64) return;
  if(voiceUrls.has(item.id)) URL.revokeObjectURL(voiceUrls.get(item.id));
  const bytes=Uint8Array.from(atob(item.audio_base64),character=>character.charCodeAt(0));
  voiceUrls.set(item.id,URL.createObjectURL(new Blob([bytes],{type:"audio/wav"})));
  delete item.audio_base64;
}
function secondsFromMs(value) { return `${(value/1000).toLocaleString(locale(),{minimumFractionDigits:2,maximumFractionDigits:2})} s`; }
function voiceCard(item) {
  const benchmark=item.benchmark;
  const language=item.language && item.language !== item.language_code ? item.language : t("Idioma disponible");
  const heading=`${t(item.name)} · ${t(language||"Idioma sin especificar")}`;
  const model=t(item.quality_label||"Calidad sin especificar");
  const rating=benchmark?`<div class="voice-rating ${esc(benchmark.recommendation.code)}"><strong>${esc(translateText(benchmark.recommendation.label))}</strong><p>${esc(ctx.commercialText(benchmark.recommendation.detail))}</p></div>${values([["Tiempo de preparación",secondsFromMs(benchmark.generation_ms)],["Duración de la muestra",`${benchmark.audio_seconds.toLocaleString(locale())} s`],["Preparación inicial",secondsFromMs(benchmark.load_ms)]])}`:'<div class="voice-unmeasured"><strong>Velocidad pendiente</strong><p>Prueba esta voz para conocer cuánto tarda en preparar un mensaje.</p></div>';
  const audio=voiceUrls.has(item.id)?`<audio controls preload="metadata" src="${esc(voiceUrls.get(item.id))}" aria-label="Muestra de ${esc(item.name)}"></audio>`:"";
  const controls=`${action(benchmark?"Probar de nuevo":"Probar velocidad","voice-benchmark",item.id,"secondary")}${item.active?'<span class="badge live">Voz activa</span>':action("Usar esta voz","voice-select",item.id,"primary")}`;
  const license=item.commercial_use?`<span class="voice-license">${t("Uso comercial permitido")}</span>`:"";
  return `<article class="voice-card ${item.active?"active":""}"><div class="voice-card-head"><div><h2>${esc(heading)}</h2><p>${esc(model)}</p>${license}</div><div class="voice-actions">${controls}</div></div>${rating}${audio}</article>`;
}

export function auditPresentation(row) {
  const named = {
    "POST /api/preview/audio":["Muestra de voz generada","Vista previa de audio","Audio disponible"],
    "POST /api/manage/voices/benchmark":["Velocidad de voz comprobada","Voz","Resultado disponible"],
    "POST /api/manage/voices/select":["Voz activa actualizada","Voz","Cambio aplicado"],
    "auth.setup":["Primer administrador creado","Usuario","Acceso administrador habilitado"],
    "auth.login":["Inicio de sesión","Usuario","Acceso concedido"],
    "auth.login_failed":["Intento de acceso rechazado","Acceso","No autorizado"],
    "report.generated":["Reporte automático generado","Reporte","Archivo disponible"],
    "report.download":["Reporte descargado","Reporte","Acceso al archivo"],
    "recording.listen":["Grabación consultada","Llamada","Acceso al audio"],
    "amd_calibration.listen":["Saludo inicial escuchado","Muestra de respuesta","Acceso al audio"],
    "amd_calibration.labeled":["Tipo de respuesta confirmado","Muestra de respuesta","Clasificación confirmada"],
    "amd_calibration.deleted":["Muestra de respuesta eliminada","Muestra de respuesta","Audio temporal eliminado"],
    "amd_calibration.deleted_all":["Muestras de respuesta eliminadas","Revisión de respuestas","Audios temporales eliminados"],
    "traceability.report_downloaded":["Reporte de seguimiento descargado","Cliente","Archivo Excel"],
    "traceability.bundle_downloaded":["Paquete de grabaciones descargado","Cliente","Descarga completa"],
    "schedule.started":["Campaña programada iniciada","Campaña","Iniciada"],
    "campaign.scheduled":["Campaña creada con horario","Campaña","Programada"],
    "campaign.scheduled_from_draft":["Borrador programado","Campaña","Programada"],
    "campaign.started_on_create":["Campaña creada e iniciada","Campaña","Iniciada"],
    "campaign.duplicated":["Campaña duplicada","Campaña","Borrador independiente creado"],
    "campaign.retries_updated":["Reintentos configurados","Campaña","Política actualizada"],
    "call.retry_scheduled":["Reintento programado","Llamada","Próximo intento en espera"],
    "call.retry_started":["Reintento iniciado","Llamada","Intento registrado"],
    "call.retry_cancelled":["Reintento cancelado","Llamada","Campaña detenida"],
    "call.retry_finished":["Fin de reintentos","Llamada","Decisión registrada"],
    "campaign.created":["Campaña creada","Campaña","Creación registrada"],
    "campaign.rerun_created":["Nuevo envío creado","Campaña","Historial anterior conservado"],
    "campaign.rerun_started":["Campaña ejecutada nuevamente","Campaña","Iniciada"],
    "campaign.start_requested":["Inicio de campaña solicitado","Campaña","Solicitud registrada"],
    "campaign.started":["Campaña iniciada","Campaña","Iniciada"],
    "campaign.capacity_paused":["Campaña pausada por disponibilidad","Campaña","Todos los agentes están ocupados"],
    "campaign.capacity_resumed":["Marcación reanudada por capacidad","Campaña","Teléfono de transferencia disponible"],
    "campaign.start_failed":["Inicio de campaña fallido","Campaña","Consulta el motivo"],
    "campaign.rerun_rejected":["Reejecución no permitida","Campaña","Consulta el motivo"],
    "campaign.duplicate_rejected":["Duplicación no permitida","Campaña","Consulta el motivo"],
    "schedule.missed":["Horario de campaña vencido","Campaña","Requiere reprogramación"],
    "schedule.skipped":["Programación omitida","Campaña","Sin contactos pendientes"],
    "schedule.failed":["Error al iniciar campaña programada","Campaña","No iniciada"],
  };
  const routes = [
    [/^POST \/api\/auth\/logout$/, "Sesión cerrada", "Usuario"],
    [/^POST \/api\/auth\/login$/, "Inicio de sesión", "Usuario"],
    [/^POST \/api\/manage\/users\//, "Acceso de usuario actualizado", "Usuario"],
    [/^POST \/api\/manage\/users$/, "Usuario creado", "Usuarios"],
    [/^POST \/api\/manage\/templates\/.+\/delete$/, "Plantilla eliminada", "Plantilla"],
    [/^POST \/api\/manage\/templates$/, "Plantilla guardada", "Plantillas"],
    [/^POST \/api\/manage\/schedules\/.+\/cancel$/, "Programación cancelada", "Programación"],
    [/^POST \/api\/manage\/schedules$/, "Campaña programada", "Programación"],
    [/^POST \/api\/manage\/report-schedules$/, "Reporte automático configurado", "Reportes automáticos"],
    [/^POST \/api\/manage\/alerts\//, "Alerta marcada como revisada", "Alerta"],
    [/^POST \/api\/manage\/trunks$/, "Proveedor actualizado", "Proveedores"],
    [/^POST \/api\/manage\/config$/, "Configuración actualizada", "Configuración general"],
    [/^POST \/api\/settings$/, "Capacidad actualizada", "Límites globales"],
    [/^POST \/api\/campaigns\/.+\/start$/, "Campaña iniciada", "Campaña"],
    [/^POST \/api\/campaigns\/.+\/stop$/, "Campaña detenida", "Campaña"],
    [/^POST \/api\/campaigns$/, "Campaña creada", "Campañas"],
    [/^POST \/api\/preview$/, "Campaña validada", "Vista previa"],
    [/^POST \/api\/jobs\/.+\/simulate$/, "Resultado de prueba aplicado", "Llamada de prueba"],
  ];
  let entry=named[row.action];
  if(!entry) {
    const route=routes.find(([pattern])=>pattern.test(row.action));
    if(route) entry=[route[1],route[2],"Completado"];
  }
  const [title,resource,result]=entry||["Actividad registrada","Registro","Consulta los detalles"];
  const id=String(row.target||"").match(/(?:^|\/)([a-f0-9]{32})(?:\/|$)/)?.[1];
  return {title:t(title),result:t(result),target:id?`${t(resource)} · ${id.slice(0,8)}`:t(resource)};
}

export function installManagement(context) {
  ctx=context;
  $("#auth-form").addEventListener("submit", async event => {
    event.preventDefault(); const button=$("#auth-submit"); button.disabled=true; $("#auth-error").textContent="";
    try {
      const payload={username:$("#auth-user").value,password:$("#auth-password").value};
      if(setup) payload.display_name=$("#auth-name").value;
      ctx.state.user=await ctx.api(`/api/auth/${setup?"setup":"login"}`,payload);
      $("#auth-form").reset(); showSession(); await ctx.refresh(); await loadTemplates();
    } catch(error) { $("#auth-error").textContent=error.message; }
    finally { button.disabled=false; }
  });
  $("#ops-content").addEventListener("submit",event=>{
    const form=event.target.closest("form[data-manage-form]"); if(!form) return;
    event.preventDefault(); ctx.run(()=>saveForm(form),form.querySelector('[type="submit"]'));
  });
  $("#ops-content").addEventListener("change",event=>{
    if(event.target.name!=="port_trunk_id") return;
    const trunk=cache.configTrunks.find(t=>t.id===event.target.value);
    for(const key of ["local_port","rtp_port","rtp_port_range"]) event.target.form.elements[key].value=trunk.sip[key];
  });
  $("#template-picker").addEventListener("change",()=>{
    const t=cache.templates?.find(t=>t.id===$("#template-picker").value);
    if(t) { $("#message").value=t.message; applyTemplateAgent(t); $("#message-preview").textContent=t.message; }
  });
}
export async function bootSession() {
  const result=await ctx.api("/api/auth/status"); setup=result.setup_required;
  ctx.state.user=result.user;
  if(result.user) { showSession(); await loadTemplates(); }
  else showLogin();
}
function showLogin() {
  $(".shell").hidden=true; $("#auth-view").hidden=false;
  $("#auth-title").textContent=t(setup?"Crea tu acceso administrador":"Inicia sesión");
  $("#auth-description").textContent=t(setup?"Este primer usuario administrará proveedores, permisos y configuración.":"Accede a tus campañas, reportes e historial.");
  $("#auth-name-field").hidden=!setup; $("#auth-name").required=setup;
  $("#auth-password").minLength=setup?12:1;
  $("#auth-password").autocomplete=setup?"new-password":"current-password";
  $("#auth-submit").textContent=t(setup?"Crear administrador":"Entrar");
  $("#auth-user").focus();
}
function showSession() {
  $("#auth-view").hidden=true; $(".shell").hidden=false;
  $("#session-user").textContent=ctx.state.user.display_name;
  ctx.state.current=null; ctx.state.selected=null; ctx.state.jobs=[];
  ctx.view("dashboard"); applyRole();
}
export function expireSession() { stopRecordings(); clearVoiceAudio(); ctx.clearAudioPreview(); ctx.state.user=null; cache={}; setup=false; showLogin(); }
export function applyRole() { document.body.dataset.role=ctx.state.user?.role || "guest"; }
export async function loadTemplates() {
  if(!ctx.state.user) return;
  await loadCountries(ctx.api);
  cache.templates=await ctx.api("/api/manage/templates");
  const picker=$("#template-picker"),old=picker.value;
  picker.innerHTML=`<option value="">${t("Escribir un mensaje nuevo")}</option>`+cache.templates.map(item=>`<option value="${esc(item.id)}">${esc(item.name)}</option>`).join("");
  picker.value=old;
}
async function openTab(next=tab) {
  if(tab==="voices"&&next!=="voices") clearVoiceAudio();
  stopRecordings($("#ops-content"));
  tab=next; ctx.view("operations");
  $("#ops-title").textContent=names[tab]; $("#ops-subtitle").textContent=descriptions[tab];
  $("#ops-feedback").textContent="";
  $("#ops-tabs").innerHTML=Object.entries(names).filter(([k])=>(admin()||!["users","audit","config","voices"].includes(k))&&(ctx.state.user?.role!=="analyst"||k!=="calibration")).map(([k,v])=>`<button data-action="ops-tab" data-id="${k}" ${k===tab?'aria-current="page"':""}>${v}</button>`).join("");
  $("#ops-content").setAttribute("aria-busy","true");
  $("#ops-content").innerHTML=`<p class="ops-empty" role="status">${t("Cargando información…")}</p>`;
  try {
    if(tab==="calibration") cache.calibration=await ctx.api(`/api/amd-calibration?label=${calibrationFilter}&offset=${calibrationOffset}`);
    else {
      const route={automatic:"report-schedules"}[tab]||tab;
      cache[tab]=await ctx.api(`/api/manage/${route}${tab==="audit"?`?offset=${auditOffset}`:""}`);
    }
    if(tab==="config") cache.configTrunks=(await ctx.api("/api/manage/trunks")).items;
    render();
  } finally { $("#ops-content").setAttribute("aria-busy","false"); }
}
function render(edit=null) {
  stopRecordings($("#ops-content"));
  let html="";
  if(tab==="trunks") {
    const data=cache.trunks;
    html=`<p class="ops-policy">${data.routing==="weighted"?"Distribución según participación":"Distribución equilibrada"} entre proveedores con el mismo orden de preferencia. El menor número se usa primero y los demás quedan disponibles como respaldo.</p>`;
    html+=cards(data.items,t=>record(ctx.commercialText(t.name),`${t.enabled?(t.cooldown_seconds?`En pausa temporal · ${t.cooldown_seconds} s`:ctx.commercialText(t.status)):"Desactivado"}`,values([["Orden de preferencia",t.priority],["Participación",t.weight],["Capacidad utilizada",`${t.reserved_channels} de ${t.channels}`],["Ritmo permitido",`${t.calls_per_second} llamadas por segundo`]]),`${action("Historial","trunk-history",t.id)}${admin()?action("Editar","trunk-edit",t.id):""}`),"Agrega un proveedor para habilitar las llamadas.");
    if(admin()) html+=trunkForm(edit);
  } else if(tab==="voices") {
    html=`<section class="voice-intro"><div><span class="amd-kicker">Compara antes de elegir</span><p>Todas las voces preparan el mismo mensaje de muestra. Así puedes valorar su calidad y el tiempo de espera antes de usarla en una campaña.</p></div><p><strong>${cache.voices.items.length}</strong> voces disponibles</p></section><div class="voice-grid">${cache.voices.items.map(voiceCard).join("")||empty("No hay voces disponibles en este momento.")}</div><p class="field-help">Las voces recomendadas preparan el mensaje con suficiente rapidez para iniciar la conversación sin demoras perceptibles.</p>`;
  } else if(tab==="templates") {
    html=cards(cache.templates,t=>record(t.name,t.agent_number?`${t.agent_numbers.length} teléfonos · ${strategyNames[t.agent_strategy]}`:"Sin equipo de transferencia predeterminado",`<p class="ops-message">${esc(t.message)}</p>`,write()?action("Usar en campaña","template-use",t.id)+action("Editar","template-edit",t.id)+action("Eliminar","template-delete",t.id):""),"Guarda tu primer mensaje para reutilizarlo en las campañas.");
    if(write()) html+=form("template",edit?"Editar plantilla":"Nueva plantilla",`<div class="ops-grid">${field("name","Nombre",edit?.name||"","text",'required maxlength="100"')}</div>${templatePoolFields(edit)}<label for="m-message">Mensaje</label><textarea id="m-message" name="message" rows="4" maxlength="4000" required>${esc(edit?.message||"")}</textarea><p class="field-help">Puedes incluir datos personalizados como {nombre} y {fecha}. Las opciones para repetir o hablar con un agente se agregan al llamar.</p>${buttons("Guardar plantilla")}`,edit?.id||"");
  } else if(tab==="schedules") {
    html=cards(cache.schedules,r=>record(r.campaign_name,`${stateNames[r.state]} · ${r.mode==="sip"?"En vivo":"Prueba"}`,values([["Fecha",stamp(r.due_at,r.timezone)],["Zona de programación",r.timezone],["Detalle",ctx.commercialText(scheduleDetail(r))]]),action("Abrir campaña","select-campaign",r.campaign_id)+(r.state==="pending"&&write()?action("Cancelar programación","schedule-cancel",r.id):"")),"Aún no hay programaciones. Elige Programar al crear una campaña.");
    if(write()) html+=action("Crear campaña","new");
  } else if(tab==="automatic") {
    html=cards(cache.automatic.schedules,r=>record(r.name,`${r.enabled?"Activa":"Pausada"} · ${r.cadence==="daily"?"Diaria":"Semanal"} · ${r.format==="xlsx"?"Excel completo":"Archivo de datos"}`,values([["Próxima preparación",stamp(r.next_run,r.timezone)],["Zona",r.timezone],["Período",`${r.period_days} días completos anteriores`]]),write()?action("Editar","report-edit",r.id):""),"Programa la generación de reportes sin repetir la descarga manual.");
    if(write()) html+=reportForm(edit);
    html+=`<h2 class="ops-list-heading">Reportes preparados</h2>`+cards(cache.automatic.runs,r=>record(r.name,`${stateNames[r.status]} · ${zonedStamp(r.created_at)}`,`<p>${esc(ctx.commercialText(r.detail||""))}</p>`,r.status==="ready"?`<a class="text-link" href="/api/manage/report-runs/${esc(r.id)}/download">Descargar</a>`:""),"Los reportes aparecerán aquí al cumplirse su horario.");
  } else if(tab==="alerts") {
    const rows=cache.alerts;
    $("#alert-count").hidden=!rows.some(r=>!r.resolved_at&&!r.acknowledged_at);
    $("#alert-count").textContent=rows.filter(r=>!r.resolved_at&&!r.acknowledged_at).length;
    html=cards(rows,r=>record(ctx.commercialText(r.title),`${r.resolved_at?"Resuelta":r.acknowledged_at?"Revisada":"Pendiente de revisión"} · ${zonedStamp(r.created_at)}`,`<p>${esc(ctx.commercialText(r.detail))}</p>`,write()&&!r.acknowledged_at?action("Marcar revisada","alert-ack",r.id):""),"Sin alertas. Aquí aparecerán problemas con proveedores, horarios vencidos y reportes disponibles.");
  } else if(tab==="calibration") {
    html=calibrationView(cache.calibration);
  } else if(tab==="config") html=portsForm(cache.configTrunks)+configForm(cache.config);
  else if(tab==="users") {
    html=cards(cache.users,r=>record(r.display_name,`${r.username} · ${{admin:"Administrador",operator:"Operador",analyst:"Analista"}[r.role]} · ${r.enabled?"Activo":"Desactivado"}`,"",action("Editar acceso","user-edit",r.id)),"Crea usuarios para compartir la operación.");
    html+=form("user",edit?"Editar acceso":"Nuevo usuario",`<div class="ops-grid">${edit?"":field("username","Usuario","","text",'required pattern="(?:[a-zA-Z0-9_.@]|-)+" maxlength="80"')}${field("display_name","Nombre",edit?.display_name||"","text",'required maxlength="100"')}${field("password",edit?"Nueva contraseña (opcional)":"Contraseña","","password",`${edit?"":"required"} minlength="12" maxlength="256" autocomplete="new-password"`,"Al menos 12 caracteres. La contraseña se protege y nunca se guarda como texto legible.")}${select("role","Rol",edit?.role||"operator",[["operator","Operador"],["analyst","Analista"],["admin","Administrador"]])}</div>${check("enabled","Acceso activo",edit?edit.enabled:true)}<p class="field-help">Administrador: configuración y accesos. Operador: campañas, programación y audio. Analista: consultas y reportes, sin grabaciones.</p>${buttons("Guardar usuario")}`,edit?.id||"");
  } else if(tab==="audit") {
    html=cards(cache.audit,r=>{ const a=auditPresentation(r); return record(a.title,`${zonedStamp(r.created_at)} · ${r.actor_name}`,values([["Resultado",a.result],["Elemento",a.target]])); },"Las acciones quedarán registradas con usuario y fecha.");
    html+=`<div class="pagination"><span>Desde el registro ${auditOffset+1}</span><div>${auditOffset?action("Anterior","audit-prev"):""}${cache.audit.length===100?action("Siguiente","audit-next"):""}</div></div>`;
  }
  $("#ops-content").innerHTML=translateHTML(html); applyRole();
}
function calibrationView(data) {
  const summary=data.summary;
  const filters=[["pending","Por revisar"],["disagreement","Diferencias"],["human","Personas"],["machine","Buzones"],["all","Todas"]];
  if(!data.items.some(item=>item.id===calibrationSelected)) calibrationSelected=data.items[0]?.id||null;
  const selected=data.items.find(item=>item.id===calibrationSelected);
  const agreement=summary.agreement_percent==null?"Sin datos":`${summary.agreement_percent}%`;
  const size=summary.size_bytes<1024?`${summary.size_bytes} B`:summary.size_bytes<1048576?`${(summary.size_bytes/1024).toFixed(0)} KB`:`${(summary.size_bytes/1048576).toFixed(1)} MB`;
  let html=`<section class="amd-calibration-intro"><div><span class="badge ${summary.capture_enabled?"live":""}">${summary.capture_enabled?"Recolección activa":"Recolección pausada"}</span><p>Se conserva únicamente el saludo inicial, hasta ${esc(summary.capture_seconds)} segundos. No incluye el mensaje ni la conversación posterior.</p></div>${summary.total&&write()?action("Eliminar todas las muestras","calibration-delete-all","","danger-quiet"):""}</section>`;
  html+=`<dl class="amd-calibration-summary"><div><dt>Por revisar</dt><dd>${summary.pending}</dd></div><div><dt>Personas</dt><dd>${summary.human}</dd></div><div><dt>Buzones</dt><dd>${summary.machine}</dd></div><div><dt>Precisión estimada</dt><dd>${agreement}</dd></div><div><dt>Espacio utilizado</dt><dd>${size}</dd></div></dl>`;
  html+=`<div class="amd-calibration-toolbar" role="group" aria-label="Filtrar muestras">${filters.map(([id,label])=>`<button type="button" data-action="calibration-filter" data-id="${id}" aria-pressed="${calibrationFilter===id}">${label}</button>`).join("")}</div>`;
  if(!data.items.length) {
    html+=`<div class="amd-calibration-empty"><h2>${calibrationFilter==="pending"?"No hay saludos pendientes":"No hay muestras en este filtro"}</h2><p>${summary.capture_enabled?"Las siguientes llamadas con respuesta aparecerán aquí después de identificar el tipo de saludo.":"Activa la recolección temporal desde Configuración para obtener nuevas muestras."}</p></div>`;
    return html;
  }
  const rows=data.items.map(item=>`<tr class="${item.id===calibrationSelected?"selected":""}"><td><button type="button" class="calibration-select" data-action="calibration-select" data-id="${item.id}" aria-current="${item.id===calibrationSelected}"><strong>${esc(item.phone)}</strong><span>${esc(item.credit_id)} · ${esc(item.campaign_name)}</span></button></td><td><span class="amd-label ${item.predicted_verdict}">${esc(amdVerdicts[item.predicted_verdict])}</span></td><td>${item.label?`<span class="amd-label ${item.label}">${esc(amdVerdicts[item.label])}</span>`:"<span class=\"muted\">Pendiente</span>"}</td><td>${esc(stamp(item.created_at))}</td></tr>`).join("");
  html+=`<div class="amd-calibration-layout"><section class="amd-calibration-ledger" aria-label="Muestras de respuesta"><div class="table-scroll"><table><thead><tr><th>Contacto</th><th>Resultado automático</th><th>Tu evaluación</th><th>Fecha</th></tr></thead><tbody>${rows}</tbody></table></div><div class="pagination"><span>${data.total} muestra${data.total===1?"":"s"}</span><div>${calibrationOffset?action("Anterior","calibration-prev"):""}${calibrationOffset+data.limit<data.total?action("Siguiente","calibration-next"):""}</div></div></section>${calibrationReview(selected)}</div>`;
  return html;
}
function calibrationReview(item) {
  if(!item) return "";
  const predicted=amdVerdicts[item.predicted_verdict]||"Sin clasificación";
  const reason=amdReasons[item.predicted_reason]||"Motivo registrado";
  const seconds=(item.duration_ms/1000).toFixed(1);
  const selectedLabel=item.label?`Etiquetado como ${amdVerdicts[item.label]}`:"Pendiente de tu revisión";
  return `<aside class="amd-calibration-review recording-panel"><div class="amd-calibration-review-head"><div><span class="amd-kicker">Revisión de saludo</span><h2>${esc(item.phone)}</h2><p>${esc(item.credit_id)} · ${esc(item.campaign_name)}</p></div><span class="amd-label ${item.predicted_verdict}">Resultado: ${esc(predicted)}</span></div><audio controls preload="none" src="/api/amd-calibration/${encodeURIComponent(item.id)}/audio" aria-label="Saludo inicial de ${esc(item.phone)}"></audio><p class="recording-error" role="status" hidden>No se pudo reproducir la muestra. Recarga la bandeja e inténtalo de nuevo.</p><p class="amd-capture-note">Sólo contiene los primeros ${seconds} s recibidos antes del mensaje.</p><dl class="amd-evidence"><div><dt>Evaluación automática</dt><dd>${esc(predicted)}</dd></div><div><dt>Motivo</dt><dd>${esc(reason)}</dd></div><div><dt>Tiempo con voz</dt><dd>${secondsFromMs(item.voiced_ms)}</dd></div><div><dt>Partes del saludo</dt><dd>${item.words}</dd></div><div><dt>Tiempo de evaluación</dt><dd>${secondsFromMs(item.elapsed_ms)}</dd></div><div><dt>Tipo de operación</dt><dd>${item.mode==="sip"?"En vivo":"Prueba"}</dd></div></dl><div class="amd-label-state">${esc(selectedLabel)}</div>${write()?`<div class="amd-label-actions"><button type="button" class="primary" data-action="calibration-label" data-id="${item.id}" data-label="human">Es persona</button><button type="button" class="secondary" data-action="calibration-label" data-id="${item.id}" data-label="machine">Es buzón</button></div>${action("Eliminar esta muestra","calibration-delete",item.id,"danger-quiet")}`:""}</aside>`;
}
function trunkForm(t) {
  const sip=t?.sip||{domain:"",username:"",auth_username:"",caller_id:"",registrar:"",proxy:"",registration_enabled:true,dial_format:"as_entered",transport:"udp",bind_address:"0.0.0.0",public_address:"",local_port:5060,rtp_port:10000+cache.trunks.items.length*200,rtp_port_range:200};
  return form("trunk",t?`Editar ${esc(ctx.commercialText(t.name))}`:"Agregar proveedor",`<div class="ops-grid">${field("id","Referencia interna",t?.id||"","text",`required pattern="(?:[a-zA-Z0-9_]|-){1,40}" ${t?"readonly":""}`)}${field("name","Nombre comercial",t?.name||"","text",'required maxlength="100"')}${field("domain","Dirección del proveedor",sip.domain,"text","required","Utiliza la dirección entregada por tu proveedor")}${field("username","Usuario del proveedor",sip.username,"text","required")}${field("password",t?.has_password?"Contraseña (vacío conserva la actual)":"Contraseña","","password",'autocomplete="new-password"')}${field("caller_id","Número mostrado al cliente",sip.caller_id,"text","","Déjalo vacío si el proveedor asigna el número")}${field("priority","Orden de preferencia",t?.priority??10,"number",'min="0" max="1000" required')}${field("weight","Participación en la distribución",t?.weight??1,"number",'min="1" max="100" required')}${field("channels","Capacidad total",t?.channels??40,"number",'min="2" max="60" required',"Cada llamada con opción de transferencia requiere dos espacios de capacidad")}${field("calls_per_second","Ritmo de llamadas",t?.calls_per_second??1,"number",'min="0.01" max="20" step="0.01" required',"Cantidad máxima de llamadas nuevas por segundo")}${select("transport","Tipo de conexión",sip.transport,[["udp","Conexión estándar"],["tcp","Conexión alternativa"]])}${field("local_port","Punto de conexión local",sip.local_port,"number",'min="1024" max="65535" required')}${field("rtp_port","Inicio del rango de audio",sip.rtp_port,"number",'min="1024" max="65000" step="2" required')}${field("rtp_port_range","Tamaño del rango de audio",sip.rtp_port_range,"number",'min="4" max="4000" required')}${select("dial_format","Cobertura de llamadas",sip.dial_format,[["as_entered","Varios países · usa el país de la campaña"],["mexico_52","Sólo México"]])}</div>${check("enabled","Proveedor habilitado",t?t.enabled:true)}${check("registration_enabled","El proveedor solicita identificación",sip.registration_enabled)}<details class="ops-advanced"><summary>Datos adicionales entregados por el proveedor</summary><div class="ops-grid">${field("auth_username","Usuario alternativo",sip.auth_username)}${field("registrar","Dirección de registro",sip.registrar)}${field("proxy","Dirección intermediaria",sip.proxy)}${field("bind_address","Dirección local",sip.bind_address,"text","required")}${field("public_address","Dirección pública",sip.public_address)}</div></details><p class="field-help">Los cambios se aplican cuando no hay campañas activas. Conservamos un historial de cada actualización.</p>${buttons("Guardar proveedor")}`,t?.id||"");
}
function portsForm(trunks) {
  if(!trunks.length) return "";
  const t=trunks[0];
  return form("ports","Rango de conexión y audio",`<div class="ops-grid">${select("port_trunk_id","Proveedor",t.id,trunks.map(t=>[t.id,ctx.commercialText(t.name)]))}${field("local_port","Punto de conexión local",t.sip.local_port,"number",'min="1024" max="65535" required')}${field("rtp_port","Inicio del rango de audio",t.sip.rtp_port,"number",'min="1024" max="65000" step="2" required')}${field("rtp_port_range","Tamaño del rango de audio",t.sip.rtp_port_range,"number",'min="4" max="4000" required')}</div><p class="field-help">Usa los valores entregados por tu proveedor. Los cambios se aplican cuando no hay campañas activas.</p>${buttons("Guardar rango")}`);
}
function reportForm(r) {
  return form("report",r?"Editar programación de reporte":"Programar reporte",`<div class="ops-grid">${field("name","Nombre del reporte",r?.name||"","text",'required maxlength="100"')}${select("cadence","Frecuencia",r?.cadence||"daily",[["daily","Diaria"],["weekly","Semanal"]])}${field("local_time","Hora",r?.local_time||"08:00","time","required")}${select("weekday","Día (sólo semanal)",r?.weekday??0,[[0,"Lunes"],[1,"Martes"],[2,"Miércoles"],[3,"Jueves"],[4,"Viernes"],[5,"Sábado"],[6,"Domingo"]])}${field("timezone","Zona horaria",r?.timezone||zone(),"text","required")}${select("format","Contenido",r?.format||"xlsx",[["xlsx","Excel completo"],["csv","Historial de llamadas"]])}${field("period_days","Días completos a incluir",r?.period_days||1,"number",'min="1" max="365" required')}${select("mode","Tipo de operación",r?.mode||ctx.state.status.mode,[["sip","En vivo"],["simulation","Prueba"],["all","Todas"]])}</div>${check("enabled","Preparación automática activa",r?r.enabled:true)}<p class="field-help">El reporte quedará disponible dentro de la plataforma. La aplicación debe permanecer activa.</p>${buttons("Guardar programación")}`,r?.id||"");
}
function configForm(c) {
  const num=(key,label,min,max,step="1")=>field(key,label,c[key],"number",`min="${min}" max="${max}" step="${step}" required`);
  return form("config","Límites y comportamiento",`<fieldset><legend>Capacidad de llamadas</legend><div class="ops-grid">${num("concurrency","Llamadas simultáneas",1,30)}${num("trunk_channels","Capacidad total disponible",2,60)}${num("calls_per_second","Nuevas llamadas por segundo",.01,20,"0.01")}${select("routing","Distribución entre proveedores",c.routing,[["priority","Equilibrada"],["weighted","Según participación"]])}</div><p class="field-help">Cada llamada con opción de transferencia requiere dos espacios de capacidad. Siempre se respetan el límite general y el de cada proveedor.</p></fieldset><fieldset><legend>Tiempos de atención</legend><div class="ops-grid">${num("ring_timeout","Tiempo para que conteste el cliente (segundos)",1,180)}${num("agent_timeout","Tiempo para que conteste el agente (segundos)",1,180)}${num("choice_timeout","Tiempo para elegir una opción (segundos)",1,120)}${num("max_call_seconds","Duración máxima de la llamada (segundos)",1,14400)}</div></fieldset><fieldset><legend>Detección de buzón</legend>${check("amd_enabled","Identificar si responde una persona antes de reproducir el mensaje",c.amd.enabled)}${check("calibration_capture_enabled","Guardar temporalmente el saludo para revisar la precisión",c.amd.calibration_capture_enabled)}<div class="ops-grid">${field("total_analysis_ms","Tiempo máximo para identificar la respuesta (segundos)",c.amd.total_analysis_ms/1000,"number",'min="1" max="15" step="0.1" required')}${field("initial_silence_ms","Espera máxima del saludo (segundos)",c.amd.initial_silence_ms/1000,"number",'min="0.5" max="10" step="0.1" required')}${select("unknown_action","Si no se identifica la respuesta",c.amd.unknown_action,[["continue","Reproducir el mensaje"],["hangup","Finalizar la llamada"]])}${field("calibration_retention_days","Conservar muestras (días)",c.amd.calibration_retention_days,"number",'min="1" max="365" required')}${field("calibration_max_samples","Máximo de muestras",c.amd.calibration_max_samples,"number",'min="10" max="5000" required')}</div><p class="field-help">Las muestras contienen únicamente el saludo inicial y pueden eliminarse desde Revisión de respuestas. Los cambios se aplican a las llamadas nuevas.</p></fieldset><fieldset><legend>Grabaciones de conversaciones</legend>${check("rec_enabled","Grabar cuando se identifica una persona o el cliente selecciona una opción",c.recordings.enabled)}<div class="ops-grid">${field("retention_days","Conservar grabaciones (días)",c.recordings.retention_days,"number",'min="1" max="3650" required')}${field("max_storage_mb","Límite de almacenamiento (MB)",c.recordings.max_storage_mb,"number",'min="100" max="1000000" required')}${field("min_free_mb","Espacio mínimo disponible (MB)",c.recordings.min_free_mb,"number",'min="50" max="100000" required')}</div><p class="field-help">Las grabaciones comienzan después de identificar la respuesta y se eliminan al terminar el período de conservación. El historial de la llamada permanece disponible.</p></fieldset><fieldset><legend>Programación y alertas</legend>${check("auto_enabled","Mantener activas las campañas programadas y las alertas",c.automation.enabled)}<div class="ops-grid">${field("late_schedule_minutes","Margen para iniciar campañas retrasadas (minutos)",c.automation.late_schedule_minutes,"number",'min="1" max="1440" required')}${field("trunk_alert_seconds","Avisar si un proveedor deja de responder (segundos)",c.automation.trunk_alert_seconds,"number",'min="5" max="3600" required')}${field("failure_alert_percent","Avisar cuando las llamadas no completadas superen (%)",c.automation.failure_alert_percent,"number",'min="1" max="100" required')}${field("failure_alert_min_calls","Mínimo de llamadas para evaluar",c.automation.failure_alert_min_calls,"number",'min="1" max="1000" required')}${field("report_retention_days","Conservar reportes (días)",c.automation.report_retention_days,"number",'min="1" max="3650" required')}${field("reporting_timezone","Zona horaria de reportes",c.reporting_timezone,"text","required")}${num("report_max_rows","Máximo de registros por reporte",100,100000)}</div><p class="field-help">La proporción de llamadas no completadas se revisa sobre los últimos 15 minutos.</p></fieldset>${buttons("Guardar configuración")}`);
}
async function saveForm(formEl) {
  const kind=formEl.dataset.manageForm, id=formEl.dataset.id;
  const data=Object.fromEntries(new FormData(formEl));
  const checked=key=>formEl.elements[key].checked;
  let path,payload;
  if(kind==="trunk") {
    const sip={}; for(const key of ["domain","username","password","caller_id","auth_username","registrar","proxy","transport","dial_format","bind_address","public_address"]) sip[key]=key==="password"?data[key]:data[key].trim();
    for(const key of ["local_port","rtp_port","rtp_port_range"]) sip[key]=Number(data[key]);
    sip.registration_enabled=checked("registration_enabled");
    payload={id:data.id,name:data.name,enabled:checked("enabled"),priority:+data.priority,weight:+data.weight,channels:+data.channels,calls_per_second:+data.calls_per_second,sip};path="trunks";
  } else if(kind==="ports") {
    const trunk=cache.configTrunks.find(t=>t.id===data.port_trunk_id);
    payload={}; for(const key of ["id","name","enabled","priority","weight","channels","calls_per_second"]) payload[key]=trunk[key];
    payload.sip={...trunk.sip,password:""};
    for(const key of ["local_port","rtp_port","rtp_port_range"]) payload.sip[key]=Number(data[key]);
    path="trunks";
  } else if(kind==="template") { payload={name:data.name,message:data.message,agent_numbers_text:data.agent_numbers_text,agent_country:data.agent_country,agent_strategy:data.agent_strategy,agent_pool_wait:Number(data.agent_pool_wait)}; if(id) payload.id=id; path="templates"; }
  else if(kind==="report") { payload={...data,weekday:+data.weekday,period_days:+data.period_days,enabled:checked("enabled")}; if(id) payload.id=id; path="report-schedules"; }
  else if(kind==="user") { payload={...data,enabled:checked("enabled")}; path=`users${id?"/"+id:""}`; }
  else if(kind==="config") {
    payload={...cache.config,amd:{...cache.config.amd},recordings:{...cache.config.recordings},automation:{...cache.config.automation}};
    for(const key of ["concurrency","trunk_channels","calls_per_second","ring_timeout","agent_timeout","choice_timeout","max_call_seconds","report_max_rows"]) payload[key]=+data[key];
    payload.routing=data.routing; payload.reporting_timezone=data.reporting_timezone;
    payload.amd.enabled=checked("amd_enabled"); payload.amd.calibration_capture_enabled=checked("calibration_capture_enabled"); payload.amd.unknown_action=data.unknown_action;
    payload.amd.total_analysis_ms=Math.round(+data.total_analysis_ms*1000);
    payload.amd.initial_silence_ms=Math.round(+data.initial_silence_ms*1000);
    for(const key of ["calibration_retention_days","calibration_max_samples"]) payload.amd[key]=+data[key];
    for(const key of ["retention_days","max_storage_mb","min_free_mb"]) payload.recordings[key]=+data[key];
    payload.recordings.enabled=checked("rec_enabled"); payload.automation.enabled=checked("auto_enabled");
    for(const key of ["late_schedule_minutes","trunk_alert_seconds","failure_alert_percent","failure_alert_min_calls","report_retention_days"]) payload.automation[key]=+data[key];
    path="config";
  }
  await ctx.api(`/api/manage/${path}`,payload);
  await openTab(); if(kind==="template") await loadTemplates();
  $("#ops-feedback").textContent=t("Cambios guardados.");
  if(kind==="trunk"||kind==="config"||kind==="ports") await ctx.refresh();
}
export async function managementAction(name,el) {
  if(name==="logout") { await ctx.api("/api/auth/logout",{}); expireSession(); return true; }
  if(name==="nav-operations"||name==="ops-refresh") { await openTab(); return true; }
  if(name==="open-voices") { await openTab("voices"); return true; }
  if(name==="ops-tab") { await openTab(el.dataset.id); return true; }
  if(name==="voice-benchmark"||name==="voice-select") {
    $("#ops-feedback").textContent=t(name==="voice-select"?"Preparando y comprobando la voz antes de activarla…":"Comprobando cuánto tarda en preparar el mensaje…");
    try {
      const result=await ctx.api(`/api/manage/voices/${name==="voice-select"?"select":"benchmark"}`,{model:el.dataset.id});
      rememberVoiceAudio(result);
      cache.voices.items=cache.voices.items.map(item=>item.id===result.id?{...result,active:name==="voice-select"?true:result.active}:name==="voice-select"?{...item,active:false}:item);
      ctx.clearAudioPreview(); render();
      $("#ops-feedback").textContent=translateText(name==="voice-select"?`${result.name} quedó activa y lista para las siguientes llamadas.`:`Medición terminada: ${secondsFromMs(result.benchmark.generation_ms)} para generar ${result.benchmark.audio_seconds.toLocaleString(locale())} s de audio.`);
      if(name==="voice-select") await ctx.refresh();
    } catch(error) {
      $("#ops-feedback").textContent=error.message;
      throw error;
    }
    return true;
  }
  if(name==="trunk-edit") { render(cache.trunks.items.find(x=>x.id===el.dataset.id)); $("#m-name").focus(); $(".ops-form").scrollIntoView({block:"start"}); return true; }
  if(name==="trunk-history") {
    const rows=await ctx.api(`/api/manage/trunks/${el.dataset.id}/history`);
    const provider=ctx.commercialText(cache.trunks.items.find(item=>item.id===el.dataset.id)?.name||"Proveedor");
    $("#ops-content").innerHTML=translateHTML(`${action("Volver a proveedores","ops-refresh")}<h2 class="ops-list-heading">${t("Historial")} · ${esc(provider)}</h2>`+cards(rows,r=>record(({configuration:"Configuración del proveedor actualizada",status:"Disponibilidad del proveedor actualizada",cooldown:"Proveedor en pausa temporal"})[r.kind]||"Actividad del proveedor",zonedStamp(r.created_at),`<p>${esc(ctx.commercialText(r.detail))}</p>`),"No hay actividad registrada para este proveedor.")); return true;
  }
  if(name==="template-edit"||name==="user-edit"||name==="report-edit") {
    const rows=name==="template-edit"?cache.templates:name==="user-edit"?cache.users:cache.automatic.schedules;
    render(rows.find(r=>r.id===el.dataset.id)); $(".ops-form").scrollIntoView({block:"start"}); $(".ops-form input").focus({preventScroll:true}); return true;
  }
  if(name==="template-use") {
    ctx.clearAudioPreview();
    const t=cache.templates.find(r=>r.id===el.dataset.id); ctx.view("editor"); await loadTemplates();
    $("#template-picker").value=t.id; $("#message").value=t.message; applyTemplateAgent(t); $("#campaign-name").focus(); return true;
  }
  if(name==="template-delete") { if(!confirm(t("¿Eliminar esta plantilla? Las campañas creadas conservan su mensaje."))) return true; await ctx.api(`/api/manage/templates/${el.dataset.id}/delete`,{}); await openTab(); await loadTemplates(); return true; }
  if(name==="schedule-cancel"||name==="alert-ack") { await ctx.api(`/api/manage/${name==="schedule-cancel"?"schedules":"alerts"}/${el.dataset.id}/${name==="schedule-cancel"?"cancel":"acknowledge"}`,{}); await openTab(); return true; }
  if(name==="calibration-filter") { calibrationFilter=el.dataset.id; calibrationOffset=0; calibrationSelected=null; await openTab("calibration"); return true; }
  if(name==="calibration-select") { calibrationSelected=el.dataset.id; render(); document.querySelector(".amd-calibration-review")?.scrollIntoView({block:"nearest"}); return true; }
  if(name==="calibration-label") { await ctx.api(`/api/amd-calibration/${el.dataset.id}/label`,{label:el.dataset.label}); calibrationSelected=null; await openTab("calibration"); $("#ops-feedback").textContent=t(el.dataset.label==="human"?"Muestra etiquetada como persona.":"Muestra etiquetada como buzón."); return true; }
  if(name==="calibration-delete") { if(!confirm(t("¿Eliminar esta muestra de calibración? Esta acción borra el audio temporal."))) return true; await ctx.api(`/api/amd-calibration/${el.dataset.id}/delete`,{}); calibrationSelected=null; await openTab("calibration"); $("#ops-feedback").textContent=t("Muestra eliminada."); return true; }
  if(name==="calibration-delete-all") { if(!confirm(t("¿Eliminar todas las muestras de respuesta? El historial y los resultados de cada llamada permanecerán disponibles."))) return true; await ctx.api("/api/amd-calibration/delete-all",{}); calibrationOffset=0; calibrationSelected=null; await openTab("calibration"); $("#ops-feedback").textContent=t("Todas las muestras temporales fueron eliminadas."); return true; }
  if(name==="calibration-next"||name==="calibration-prev") { calibrationOffset=Math.max(0,calibrationOffset+(name==="calibration-next"?100:-100)); calibrationSelected=null; await openTab("calibration"); return true; }
  if(name==="audit-next"||name==="audit-prev") { auditOffset=Math.max(0,auditOffset+(name==="audit-next"?100:-100)); await openTab(); return true; }
  return false;
}
