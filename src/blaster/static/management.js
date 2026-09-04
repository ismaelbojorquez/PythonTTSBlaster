import { stopRecordings } from "./recording-player.js";

"use strict";
import { loadCountries, countryOptions, applyTemplateAgent } from "./countries.js";
import { strategyNames } from "./agent-pool.js";
let ctx, tab = "trunks", cache = {}, setup = false, auditOffset = 0;
const $ = s => document.querySelector(s);
const esc = value => ctx.escapeHTML(value);
const names = {trunks:"Troncales",templates:"Plantillas",schedules:"Historial de programación",automatic:"Reportes automáticos",alerts:"Alertas",config:"Configuración",users:"Usuarios",audit:"Auditoría"};
const descriptions = {trunks:"Prioridad, distribución y capacidad de cada ruta SIP.",templates:"Mensajes reutilizables con las variables de tus contactos.",schedules:"Consulta los horarios y cancela los pendientes. Las nuevas programaciones se definen al crear la campaña.",automatic:"Archivos locales diarios o semanales, disponibles para descargar.",alerts:"Incidencias y reportes que requieren tu atención.",config:"Capacidad global, puertos por troncal, tiempos y conservación.",users:"Define quién administra, opera o consulta la plataforma.",audit:"Acciones de usuarios y tareas automáticas con fecha e identidad."};
const stateNames = {pending:"Pendiente",started:"Iniciada",cancelled:"Cancelada",missed:"Horario vencido",skipped:"Omitida",failed:"Fallida",ready:"Disponible",running:"Generando",expired:"Vencido"};
const scheduleDetail = row => row.detail || (row.state === "pending" ? "Esperando horario y disponibilidad" : row.state === "cancelled" ? "No se ejecutará en este horario" : "Sin información adicional");
const zone = () => ctx.state.status?.reporting_timezone || "America/Mexico_City";
export const formatTimestamp = (value,timeZone) => value ? new Intl.DateTimeFormat("es-MX", {timeZone,dateStyle:"medium",timeStyle:"short"}).format(new Date(value)) : "—";
const stamp = (value,timeZone=zone()) => formatTimestamp(value,timeZone);
const zonedStamp = value => `${stamp(value)} · ${zone()}`;
const admin = () => ctx.state.user?.role === "admin";
const write = () => ctx.state.user?.role !== "analyst";
const action = (label, kind, id="", cls="text-link") => `<button type="button" class="${cls}" data-action="${kind}" data-id="${esc(id)}">${esc(label)}</button>`;
const empty = text => `<p class="ops-empty">${esc(text)}</p>`;
const field = (key,label,value="",type="text",extra="",help="") => `<div class="ops-field"><label for="m-${key}">${esc(label)}</label><input id="m-${key}" name="${key}" type="${type}" value="${esc(value)}" ${extra}>${help ? `<small>${esc(help)}</small>` : ""}</div>`;
const select = (key,label,value,options) => `<div class="ops-field"><label for="m-${key}">${esc(label)}</label><select id="m-${key}" name="${key}">${options.map(([id,text])=>`<option value="${esc(id)}" ${String(value)===String(id)?"selected":""}>${esc(text)}</option>`).join("")}</select></div>`;
const check = (key,label,value) => `<label class="ops-check"><input type="checkbox" name="${key}" ${value?"checked":""}>${esc(label)}</label>`;
const buttons = label => `<div class="ops-form-actions"><button type="submit" class="primary">${label}</button>${action("Cancelar edición","ops-refresh")}</div>`;
function form(kind,title,content,id="") { return `<form class="ops-form" data-manage-form="${kind}" data-id="${esc(id)}"><h2>${title}</h2>${content}</form>`; }
function templatePoolFields(edit) {
  const numbers = edit?.agent_numbers_national || (edit?.agent_number ? [edit.agent_national || edit.agent_number] : []);
  return `<div class="ops-grid">${select("agent_country","País del pool",edit?.agent_country||"MX",countryOptions())}${select("agent_strategy","Distribución",edit?.agent_strategy||"round_robin",Object.entries(strategyNames))}${field("agent_pool_wait","Espera si todos están ocupados (s)",edit?.agent_pool_wait??30,"number",'min="0" max="300" step="1" required')}</div><label for="m-agent_numbers_text">Teléfonos de transferencia (opcional)</label><textarea id="m-agent_numbers_text" name="agent_numbers_text" rows="3" maxlength="4000" spellcheck="false">${esc(numbers.join("\n"))}</textarea><p class="field-help">Un número nacional por línea. Hasta 50 números, con una llamada por teléfono. Usa 0 segundos para no esperar cuando todos estén ocupados.</p>`;
}
function cards(items,render,text) { return items.length ? `<div class="ops-records">${items.map(render).join("")}</div>` : empty(text); }
const record = (title,summary,body,controls="") => `<article class="ops-record"><div class="ops-record-head"><div><h2>${esc(title)}</h2><p>${esc(summary)}</p></div><div class="ops-row-actions">${controls}</div></div>${body}</article>`;
const values = entries => `<dl class="ops-values">${entries.map(([a,b])=>`<div><dt>${esc(a)}</dt><dd>${esc(b)}</dd></div>`).join("")}</dl>`;

export function auditPresentation(row) {
  const named = {
    "POST /api/preview/audio":["Muestra de voz generada","Vista previa de audio","Audio disponible"],
    "auth.setup":["Primer administrador creado","Usuario","Acceso administrador habilitado"],
    "auth.login":["Inicio de sesión","Usuario","Acceso concedido"],
    "auth.login_failed":["Intento de acceso rechazado","Acceso","No autorizado"],
    "report.generated":["Reporte automático generado","Reporte","Archivo disponible"],
    "report.download":["Reporte descargado","Reporte","Acceso al archivo"],
    "recording.listen":["Grabación consultada","Llamada","Acceso al audio"],
    "traceability.report_downloaded":["Reporte de trazabilidad descargado","Identificador","Exportación XLSX"],
    "traceability.bundle_downloaded":["Paquete de grabaciones descargado","Identificador","Exportación masiva"],
    "schedule.started":["Campaña programada iniciada","Campaña","Iniciada"],
    "campaign.scheduled":["Campaña creada con horario","Campaña","Programada"],
    "campaign.started_on_create":["Campaña creada e iniciada","Campaña","Iniciada"],
    "campaign.duplicated":["Campaña duplicada","Campaña","Borrador independiente creado"],
    "campaign.retries_updated":["Reintentos configurados","Campaña","Política actualizada"],
    "call.retry_scheduled":["Reintento programado","Llamada","Próximo intento en espera"],
    "call.retry_started":["Reintento iniciado","Llamada","Intento registrado"],
    "call.retry_cancelled":["Reintento cancelado","Llamada","Campaña detenida"],
    "call.retry_finished":["Fin de reintentos","Llamada","Decisión registrada"],
    "campaign.created":["Campaña creada","Campaña","Creación registrada"],
    "campaign.rerun_created":["Nueva ejecución creada","Campaña","Historial anterior conservado"],
    "campaign.rerun_started":["Campaña ejecutada nuevamente","Campaña","Iniciada"],
    "campaign.start_requested":["Inicio de campaña solicitado","Campaña","Solicitud registrada"],
    "campaign.started":["Campaña iniciada","Campaña","Iniciada"],
    "campaign.capacity_paused":["Marcación pausada por capacidad","Campaña","Pool de transferencia ocupado"],
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
    [/^POST \/api\/manage\/trunks$/, "Troncal actualizada", "Troncales"],
    [/^POST \/api\/manage\/config$/, "Configuración actualizada", "Configuración general"],
    [/^POST \/api\/settings$/, "Capacidad actualizada", "Límites globales"],
    [/^POST \/api\/campaigns\/.+\/start$/, "Campaña iniciada", "Campaña"],
    [/^POST \/api\/campaigns\/.+\/stop$/, "Campaña detenida", "Campaña"],
    [/^POST \/api\/campaigns$/, "Campaña creada", "Campañas"],
    [/^POST \/api\/preview$/, "Campaña validada", "Vista previa"],
    [/^POST \/api\/jobs\/.+\/simulate$/, "Acción de simulación aplicada", "Llamada de prueba"],
  ];
  let entry=named[row.action];
  if(!entry) {
    const route=routes.find(([pattern])=>pattern.test(row.action));
    if(route) entry=[route[1],route[2],"Completado"];
  }
  const [title,resource,result]=entry||["Actividad registrada","Registro","Consulta los detalles"];
  const id=String(row.target||"").match(/(?:^|\/)([a-f0-9]{32})(?:\/|$)/)?.[1];
  return {title,result,target:id?`${resource} · ${id.slice(0,8)}`:resource};
}
const technical = (code,target,detail) => `<details class="ops-advanced"><summary>Detalles técnicos</summary><p><code>${esc(code)}</code></p>${target?`<p class="ops-id">${esc(target)}</p>`:""}<pre class="ops-technical">${esc(detail)}</pre></details>`;

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
  $("#auth-title").textContent=setup?"Crea tu acceso administrador":"Inicia sesión";
  $("#auth-description").textContent=setup?"Este primer usuario administrará troncales, permisos y configuración.":"Accede a tus campañas, reportes y registros.";
  $("#auth-name-field").hidden=!setup; $("#auth-name").required=setup;
  $("#auth-password").minLength=setup?12:1;
  $("#auth-password").autocomplete=setup?"new-password":"current-password";
  $("#auth-submit").textContent=setup?"Crear administrador":"Entrar";
  $("#auth-user").focus();
}
function showSession() {
  $("#auth-view").hidden=true; $(".shell").hidden=false;
  $("#session-user").textContent=ctx.state.user.display_name;
  ctx.state.current=null; ctx.state.selected=null; ctx.state.jobs=[];
  ctx.view("dashboard"); applyRole();
}
export function expireSession() { stopRecordings(); ctx.clearAudioPreview(); ctx.state.user=null; cache={}; setup=false; showLogin(); }
export function applyRole() { document.body.dataset.role=ctx.state.user?.role || "guest"; }
export async function loadTemplates() {
  if(!ctx.state.user) return;
  await loadCountries(ctx.api);
  cache.templates=await ctx.api("/api/manage/templates");
  const picker=$("#template-picker"),old=picker.value;
  picker.innerHTML='<option value="">Escribir un mensaje nuevo</option>'+cache.templates.map(t=>`<option value="${esc(t.id)}">${esc(t.name)}</option>`).join("");
  picker.value=old;
}
async function openTab(next=tab) {
  tab=next; ctx.view("operations");
  $("#ops-title").textContent=names[tab]; $("#ops-subtitle").textContent=descriptions[tab];
  $("#ops-feedback").textContent="";
  $("#ops-tabs").innerHTML=Object.entries(names).filter(([k])=>admin()||!["users","audit","config"].includes(k)).map(([k,v])=>`<button data-action="ops-tab" data-id="${k}" ${k===tab?'aria-current="page"':""}>${v}</button>`).join("");
  $("#ops-content").setAttribute("aria-busy","true");
  $("#ops-content").innerHTML='<p class="ops-empty" role="status">Cargando información…</p>';
  try {
    const route={automatic:"report-schedules"}[tab]||tab;
    cache[tab]=await ctx.api(`/api/manage/${route}${tab==="audit"?`?offset=${auditOffset}`:""}`);
    if(tab==="config") cache.configTrunks=(await ctx.api("/api/manage/trunks")).items;
    render();
  } finally { $("#ops-content").setAttribute("aria-busy","false"); }
}
function render(edit=null) {
  let html="";
  if(tab==="trunks") {
    const data=cache.trunks;
    html=`<p class="ops-policy">${data.routing==="weighted"?"Distribución por peso":"Distribución equilibrada"} entre rutas con la misma prioridad. El menor número es principal; los demás sirven como respaldo. Se reservan dos canales por sesión.</p>`;
    html+=cards(data.items,t=>record(t.name,`${t.sip.domain||"Destino de simulación"} · ${t.enabled?(t.cooldown_seconds?`En pausa de respaldo · ${t.cooldown_seconds} s`:t.status):"Desactivada"}`,values([["Prioridad",t.priority],["Peso",t.weight],["Canales reservados",`${t.reserved_channels} / ${t.channels}`],["Llamadas / segundo",t.calls_per_second],["Puerto SIP local",t.sip.local_port],["RTP",`${t.sip.rtp_port}–${t.sip.rtp_port+t.sip.rtp_port_range-1}`]]),`${action("Historial","trunk-history",t.id)}${admin()?action("Editar","trunk-edit",t.id):""}`),"Agrega una troncal para habilitar rutas.");
    if(admin()) html+=trunkForm(edit);
  } else if(tab==="templates") {
    html=cards(cache.templates,t=>record(t.name,t.agent_number?`${t.agent_numbers.length} teléfonos · ${strategyNames[t.agent_strategy]}`:"Sin pool predeterminado",`<p class="ops-message">${esc(t.message)}</p>`,write()?action("Usar en campaña","template-use",t.id)+action("Editar","template-edit",t.id)+action("Eliminar","template-delete",t.id):""),"Guarda tu primer mensaje para reutilizarlo en las campañas.");
    if(write()) html+=form("template",edit?"Editar plantilla":"Nueva plantilla",`<div class="ops-grid">${field("name","Nombre",edit?.name||"","text",'required maxlength="100"')}</div>${templatePoolFields(edit)}<label for="m-message">Mensaje</label><textarea id="m-message" name="message" rows="4" maxlength="4000" required>${esc(edit?.message||"")}</textarea><p class="field-help">Variables como {nombre} y {fecha}. El menú de opciones se agrega al llamar.</p>${buttons("Guardar plantilla")}`,edit?.id||"");
  } else if(tab==="schedules") {
    html=cards(cache.schedules,r=>record(r.campaign_name,`${stateNames[r.state]} · ${r.mode==="sip"?"SIP real":"Simulación"}`,values([["Fecha",stamp(r.due_at,r.timezone)],["Zona de programación",r.timezone],["Detalle",scheduleDetail(r)]]),action("Abrir campaña","select-campaign",r.campaign_id)+(r.state==="pending"&&write()?action("Cancelar programación","schedule-cancel",r.id):"")),"Aún no hay programaciones. Elige Programar al crear una campaña.");
    if(write()) html+=action("Crear campaña","new");
  } else if(tab==="automatic") {
    html=cards(cache.automatic.schedules,r=>record(r.name,`${r.enabled?"Activa":"Pausada"} · ${r.cadence==="daily"?"Diaria":"Semanal"} · ${r.format.toUpperCase()}`,values([["Próxima ejecución",stamp(r.next_run,r.timezone)],["Zona",r.timezone],["Período",`${r.period_days} días completos anteriores`]]),write()?action("Editar","report-edit",r.id):""),"Programa la generación de archivos Excel o CSV sin repetir la descarga manual.");
    if(write()) html+=reportForm(edit);
    html+=`<h2 class="ops-list-heading">Archivos generados</h2>`+cards(cache.automatic.runs,r=>record(r.name,`${stateNames[r.status]} · ${zonedStamp(r.created_at)}`,`<p>${esc(r.detail|| (r.size_bytes?`${(r.size_bytes/1024).toFixed(0)} KB`:""))}</p>`,r.status==="ready"?`<a class="text-link" href="/api/manage/report-runs/${esc(r.id)}/download">Descargar</a>`:""),"Los reportes aparecerán aquí al cumplirse su horario.");
  } else if(tab==="alerts") {
    const rows=cache.alerts;
    $("#alert-count").hidden=!rows.some(r=>!r.resolved_at&&!r.acknowledged_at);
    $("#alert-count").textContent=rows.filter(r=>!r.resolved_at&&!r.acknowledged_at).length;
    html=cards(rows,r=>record(r.title,`${r.resolved_at?"Resuelta":r.acknowledged_at?"Revisada":"Pendiente de revisión"} · ${zonedStamp(r.created_at)}`,`<p>${esc(r.detail)}</p>`,write()&&!r.acknowledged_at?action("Marcar revisada","alert-ack",r.id):""),"Sin alertas. Aquí aparecerán fallos de troncal, horarios vencidos y reportes disponibles.");
  } else if(tab==="config") html=portsForm(cache.configTrunks)+configForm(cache.config);
  else if(tab==="users") {
    html=cards(cache.users,r=>record(r.display_name,`${r.username} · ${{admin:"Administrador",operator:"Operador",analyst:"Analista"}[r.role]} · ${r.enabled?"Activo":"Desactivado"}`,"",action("Editar acceso","user-edit",r.id)),"Crea usuarios para compartir la operación.");
    html+=form("user",edit?"Editar acceso":"Nuevo usuario",`<div class="ops-grid">${edit?"":field("username","Usuario","","text",'required pattern="(?:[a-zA-Z0-9_.@]|-)+" maxlength="80"')}${field("display_name","Nombre",edit?.display_name||"","text",'required maxlength="100"')}${field("password",edit?"Nueva contraseña (opcional)":"Contraseña","","password",`${edit?"":"required"} minlength="12" maxlength="256" autocomplete="new-password"`,"Al menos 12 caracteres. Se almacena una huella, nunca texto legible.")}${select("role","Rol",edit?.role||"operator",[["operator","Operador"],["analyst","Analista"],["admin","Administrador"]])}</div>${check("enabled","Acceso activo",edit?edit.enabled:true)}<p class="field-help">Administrador: configuración y accesos. Operador: campañas, programación y audio. Analista: consultas y reportes, sin grabaciones.</p>${buttons("Guardar usuario")}`,edit?.id||"");
  } else if(tab==="audit") {
    html=cards(cache.audit,r=>{ const a=auditPresentation(r); return record(a.title,`${zonedStamp(r.created_at)} · ${r.actor_name}`,values([["Resultado",a.result],["Registro",a.target]])+technical(r.action,r.target,r.detail)); },"Las acciones quedarán registradas con usuario y fecha.");
    html+=`<div class="pagination"><span>Desde el registro ${auditOffset+1}</span><div>${auditOffset?action("Anterior","audit-prev"):""}${cache.audit.length===100?action("Siguiente","audit-next"):""}</div></div>`;
  }
  $("#ops-content").innerHTML=html; applyRole();
}
function trunkForm(t) {
  const sip=t?.sip||{domain:"",username:"",auth_username:"",caller_id:"",registrar:"",proxy:"",registration_enabled:true,dial_format:"as_entered",transport:"udp",bind_address:"0.0.0.0",public_address:"",local_port:5060,rtp_port:10000+cache.trunks.items.length*200,rtp_port_range:200};
  return form("trunk",t?`Editar ${esc(t.name)}`:"Agregar troncal",`<div class="ops-grid">${field("id","Identificador",t?.id||"","text",`required pattern="(?:[a-zA-Z0-9_]|-){1,40}" ${t?"readonly":""}`)}${field("name","Nombre",t?.name||"","text",'required maxlength="100"')}${field("domain","Servidor SIP",sip.domain,"text","required","Host o host:puerto, por ejemplo servidor.example:5060")}${field("username","Usuario SIP",sip.username,"text","required")}${field("password",t?.has_password?"Contraseña (vacío conserva la actual)":"Contraseña","","password",'autocomplete="new-password"')}${field("caller_id","Caller ID",sip.caller_id)}${field("priority","Prioridad",t?.priority??10,"number",'min="0" max="1000" required')}${field("weight","Peso de distribución",t?.weight??1,"number",'min="1" max="100" required')}${field("channels","Canales de esta troncal",t?.channels??10,"number",'min="2" max="60" required')}${field("calls_per_second","Llamadas por segundo",t?.calls_per_second??1,"number",'min="0.01" max="20" step="0.01" required')}${select("transport","Transporte",sip.transport,[["udp","UDP"],["tcp","TCP"]])}${field("local_port","Puerto SIP local",sip.local_port,"number",'min="1024" max="65535" required')}${field("rtp_port","Puerto RTP inicial (par)",sip.rtp_port,"number",'min="1024" max="65000" step="2" required')}${field("rtp_port_range","Cantidad de puertos RTP",sip.rtp_port_range,"number",'min="4" max="4000" required')}${select("dial_format","Formato de marcación",sip.dial_format,[["as_entered","Internacional · país de la campaña"],["mexico_52","Solo México · 52 + 10 dígitos"]])}</div>${check("enabled","Troncal habilitada",t?t.enabled:true)}${check("registration_enabled","Requiere registro SIP",sip.registration_enabled)}<details class="ops-advanced"><summary>Autenticación, proxy y direcciones de red</summary><div class="ops-grid">${field("auth_username","Usuario de autenticación",sip.auth_username)}${field("registrar","URI de registro",sip.registrar)}${field("proxy","Proxy SIP",sip.proxy)}${field("bind_address","Dirección local",sip.bind_address,"text","required")}${field("public_address","Dirección pública",sip.public_address)}</div></details><p class="field-help">Se guarda en config.toml. Los parámetros no secretos y su historial también se guardan en la base. Aplica cuando no haya campañas activas.</p>${buttons("Guardar y aplicar troncal")}`,t?.id||"");
}
function portsForm(trunks) {
  if(!trunks.length) return "";
  const t=trunks[0];
  return form("ports","Puertos SIP y RTP",`<div class="ops-grid">${select("port_trunk_id","Troncal",t.id,trunks.map(t=>[t.id,t.name]))}${field("local_port","Puerto SIP local",t.sip.local_port,"number",'min="1024" max="65535" required')}${field("rtp_port","Puerto RTP inicial (par)",t.sip.rtp_port,"number",'min="1024" max="65000" step="2" required')}${field("rtp_port_range","Cantidad de puertos RTP",t.sip.rtp_port_range,"number",'min="4" max="4000" required')}</div><p class="field-help">Los cambios se aplican a la troncal seleccionada, sin campañas activas. Se guardan en config.toml. El servidor y puerto remoto se editan en Troncales.</p>${buttons("Guardar y aplicar puertos")}`);
}
function reportForm(r) {
  return form("report",r?"Editar programación de reporte":"Programar reporte",`<div class="ops-grid">${field("name","Nombre del reporte",r?.name||"","text",'required maxlength="100"')}${select("cadence","Frecuencia",r?.cadence||"daily",[["daily","Diaria"],["weekly","Semanal"]])}${field("local_time","Hora",r?.local_time||"08:00","time","required")}${select("weekday","Día (sólo semanal)",r?.weekday??0,[[0,"Lunes"],[1,"Martes"],[2,"Miércoles"],[3,"Jueves"],[4,"Viernes"],[5,"Sábado"],[6,"Domingo"]])}${field("timezone","Zona horaria",r?.timezone||zone(),"text","required")}${select("format","Formato",r?.format||"xlsx",[["xlsx","Excel · 8 hojas"],["csv","CSV · CDRs"]])}${field("period_days","Días completos a incluir",r?.period_days||1,"number",'min="1" max="365" required')}${select("mode","Origen",r?.mode||ctx.state.status.mode,[["sip","SIP real"],["simulation","Simulación"],["all","Ambos"]])}</div>${check("enabled","Generación automática activa",r?r.enabled:true)}<p class="field-help">El archivo se genera dentro de la plataforma. No se envía a correos ni servicios externos. El sistema debe permanecer abierto.</p>${buttons("Guardar programación")}`,r?.id||"");
}
function configForm(c) {
  const num=(key,label,min,max,step="1")=>field(key,label,c[key],"number",`min="${min}" max="${max}" step="${step}" required`);
  return form("config","Límites y comportamiento",`<fieldset><legend>Capacidad global</legend><div class="ops-grid">${num("concurrency","Sesiones simultáneas",1,30)}${num("trunk_channels","Máximo global de canales",2,60)}${num("calls_per_second","Llamadas por segundo (global)",.01,20,"0.01")}${select("routing","Distribución entre rutas de igual prioridad",c.routing,[["priority","Equilibrada"],["weighted","Según peso"]])}</div><p class="field-help">Una sesión reserva dos canales. Se respetan simultáneamente el límite global y los límites de cada troncal. Los puertos SIP/RTP se editan en el bloque superior.</p></fieldset><fieldset><legend>Tiempos de llamada</legend><div class="ops-grid">${num("ring_timeout","Timbrado del cliente (segundos)",1,180)}${num("agent_timeout","Timbrado del agente (segundos)",1,180)}${num("choice_timeout","Espera de opción (segundos)",1,120)}${num("max_call_seconds","Duración máxima (segundos)",1,14400)}</div></fieldset><fieldset><legend>Grabaciones de voz humana</legend>${check("rec_enabled","Grabar desde AMD humano probable o interacción del teclado",c.recordings.enabled)}<div class="ops-grid">${field("retention_days","Conservar audio (días)",c.recordings.retention_days,"number",'min="1" max="3650" required')}${field("max_storage_mb","Límite de audio (MB)",c.recordings.max_storage_mb,"number",'min="100" max="1000000" required')}${field("min_free_mb","Espacio libre mínimo (MB)",c.recordings.min_free_mb,"number",'min="50" max="100000" required')}</div><p class="field-help">Formato Ogg Opus mono. La captura comienza después de la detección; no incluye el saludo analizado. Los audios vencidos se eliminan conservando el CDR.</p></fieldset><fieldset><legend>Programación y alertas</legend>${check("auto_enabled","Ejecutar tareas programadas y monitoreo",c.automation.enabled)}<div class="ops-grid">${field("late_schedule_minutes","Margen para iniciar campañas (minutos)",c.automation.late_schedule_minutes,"number",'min="1" max="1440" required')}${field("trunk_alert_seconds","Avisar troncal caída tras (segundos)",c.automation.trunk_alert_seconds,"number",'min="5" max="3600" required')}${field("failure_alert_percent","Alerta por llamadas fallidas (%)",c.automation.failure_alert_percent,"number",'min="1" max="100" required')}${field("failure_alert_min_calls","Mínimo de llamadas para evaluar",c.automation.failure_alert_min_calls,"number",'min="1" max="1000" required')}${field("report_retention_days","Conservar reportes (días)",c.automation.report_retention_days,"number",'min="1" max="3650" required')}${field("reporting_timezone","Zona horaria de reportes",c.reporting_timezone,"text","required")}${num("report_max_rows","Máximo de filas por reporte",100,100000)}</div><p class="field-help">El porcentaje de fallos se evalúa sobre los últimos 15 minutos.</p></fieldset>${buttons("Guardar y aplicar configuración")}`);
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
    payload={...cache.config,recordings:{...cache.config.recordings},automation:{...cache.config.automation}};
    for(const key of ["concurrency","trunk_channels","calls_per_second","ring_timeout","agent_timeout","choice_timeout","max_call_seconds","report_max_rows"]) payload[key]=+data[key];
    payload.routing=data.routing; payload.reporting_timezone=data.reporting_timezone;
    for(const key of ["retention_days","max_storage_mb","min_free_mb"]) payload.recordings[key]=+data[key];
    payload.recordings.enabled=checked("rec_enabled"); payload.automation.enabled=checked("auto_enabled");
    for(const key of ["late_schedule_minutes","trunk_alert_seconds","failure_alert_percent","failure_alert_min_calls","report_retention_days"]) payload.automation[key]=+data[key];
    path="config";
  }
  await ctx.api(`/api/manage/${path}`,payload);
  await openTab(); if(kind==="template") await loadTemplates();
  $("#ops-feedback").textContent="Cambios guardados.";
  if(kind==="trunk"||kind==="config"||kind==="ports") await ctx.refresh();
}
export async function managementAction(name,el) {
  if(name==="logout") { await ctx.api("/api/auth/logout",{}); expireSession(); return true; }
  if(name==="nav-operations"||name==="ops-refresh") { await openTab(); return true; }
  if(name==="ops-tab") { await openTab(el.dataset.id); return true; }
  if(name==="trunk-edit") { render(cache.trunks.items.find(x=>x.id===el.dataset.id)); $("#m-name").focus(); $(".ops-form").scrollIntoView({block:"start"}); return true; }
  if(name==="trunk-history") {
    const rows=await ctx.api(`/api/manage/trunks/${el.dataset.id}/history`);
    $("#ops-content").innerHTML=`${action("Volver a troncales","ops-refresh")}<h2 class="ops-list-heading">Historial · ${esc(el.dataset.id)}</h2>`+cards(rows,r=>record(({configuration:"Configuración de troncal actualizada",status:"Estado de troncal actualizado",cooldown:"Ruta en pausa de respaldo"})[r.kind]||"Evento de troncal",zonedStamp(r.created_at),`<p>${esc(r.detail)}</p>`+technical(r.kind,r.trunk_id,r.detail)),"No hay eventos para esta troncal."); return true;
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
  if(name==="template-delete") { if(!confirm("¿Eliminar esta plantilla? Las campañas creadas conservan su mensaje.")) return true; await ctx.api(`/api/manage/templates/${el.dataset.id}/delete`,{}); await openTab(); await loadTemplates(); return true; }
  if(name==="schedule-cancel"||name==="alert-ack") { await ctx.api(`/api/manage/${name==="schedule-cancel"?"schedules":"alerts"}/${el.dataset.id}/${name==="schedule-cancel"?"cancel":"acknowledge"}`,{}); await openTab(); return true; }
  if(name==="audit-next"||name==="audit-prev") { auditOffset=Math.max(0,auditOffset+(name==="audit-next"?100:-100)); await openTab(); return true; }
  return false;
}
