"use strict";

import { formatTimestamp } from "./management.js";

let ctx, pending = null, historyOffset = 0, historyCampaign = null;
const $ = selector => document.querySelector(selector);
const esc = value => ctx.escapeHTML(value);
const stamp = value => value ? formatTimestamp(value, ctx.state.status.reporting_timezone) : "Sin iniciar";
const current = () => ctx.state.campaigns.find(c => c.id === ctx.state.current);

export function renderCampaignHistory(c) {
  if (historyCampaign !== c.id) {
    historyCampaign = c.id;
    historyOffset = 0;
    $("#execution-history").open = false;
    $("#execution-history-body").textContent = "Abre el historial para consultar las ejecuciones.";
    closeCopy();
  }
  const lineage = c.lineage || {root_id:c.id,execution_number:1};
  $("#campaign-lineage").textContent = `Ejecución ${lineage.execution_number} · Resultados de este envío`;
  const origin = $("#campaign-origin");
  origin.hidden = !lineage.source_id;
  origin.dataset.id = lineage.source_id || "";
  origin.textContent = lineage.kind === "duplicate" ? "Ver campaña de origen de esta copia" : "Ver ejecución de origen";
  const rerun = $("#rerun-button");
  rerun.hidden = !["completed", "stopped"].includes(c.status);
  const unfinished = ctx.state.campaigns.some(item => (item.lineage?.root_id || item.id) === lineage.root_id && !["completed", "stopped"].includes(item.status));
  rerun.disabled = ctx.state.busy || !ctx.state.status.ready || !!ctx.state.status.active_campaign || unfinished || c.mode !== ctx.state.status.mode;
  $("#duplicate-button").disabled = ctx.state.busy;
  $("#rerun-availability").textContent = rerun.hidden ? "" : unfinished ? "Ya hay una ejecución pendiente; consúltala en el historial." : ctx.state.status.active_campaign ? "Finaliza o detén la campaña activa para volver a ejecutar." : c.mode !== ctx.state.status.mode ? "Duplica esta campaña para trabajar en el modo actual." : !ctx.state.status.ready ? "La troncal debe estar lista para volver a ejecutar." : "";
}

function closeCopy() {
  pending = null;
  $("#campaign-copy-form").hidden = true;
}

export async function refreshCampaignHistory() {
  if (ctx.state.view !== "campaign" || !$("#execution-history").open) return;
  const cid = ctx.state.current, offset = historyOffset;
  const result = await ctx.api(`/api/campaigns/${cid}/history?offset=${offset}`);
  if (cid !== ctx.state.current || offset !== historyOffset) return;
  const rows = result.items.map(item => `<li><div class="execution-row-title"><button type="button" class="text-link" data-action="select-campaign" data-id="${esc(item.id)}" ${item.id === cid ? 'aria-current="true"' : ""}>Ejecución ${item.execution_number}${item.id === cid ? " · actual" : ""}</button>${ctx.badge(item.status)}</div><p>${esc(item.name)} · ${item.contacts} contactos · ${item.attempted} intentados · ${item.answered} contestados</p><p>Creada ${esc(stamp(item.created_at))} · ${esc(item.actor_name || "Autor no registrado")}</p><p>Inicio ${esc(stamp(item.requested_at || item.started_at))}${item.started_by ? ` · ${esc(item.started_by)}` : item.started_at ? " · Responsable no registrado" : ""}</p>${item.note ? `<p class="execution-note">Motivo: ${esc(item.note)}</p>` : ""}</li>`).join("");
  ctx.setHTML($("#execution-history-body"), `<p class="field-help">${result.total} ejecuciones · Horarios en ${esc(ctx.state.status.reporting_timezone)}. Cada envío conserva sus contactos, CDR y grabaciones.</p><ol class="execution-list">${rows}</ol><div class="pagination"><span>${offset + 1}–${Math.min(offset + 50, result.total)} de ${result.total}</span><div><button type="button" class="subtle" data-action="history-previous" ${offset === 0 ? "disabled" : ""}>Anteriores</button><button type="button" class="subtle" data-action="history-next" ${offset + 50 >= result.total ? "disabled" : ""}>Siguientes</button></div></div>`);
}

export async function campaignHistoryAction(name, element) {
  if (name === "open-execution-history") {
    $("#execution-history").open = true;
    await refreshCampaignHistory();
    const summary = $("#execution-history summary");
    summary.focus({preventScroll:true});
    summary.scrollIntoView({block:"start"});
    return true;
  }
  if (name === "cancel-copy") {
    const kind = pending?.kind;
    closeCopy();
    $(kind === "rerun" ? "#rerun-button" : "#duplicate-button").focus();
    return true;
  }
  if (name === "history-previous" || name === "history-next") {
    historyOffset = Math.max(0, historyOffset + (name === "history-next" ? 50 : -50));
    await refreshCampaignHistory();
    return true;
  }
  if (name !== "rerun-campaign" && name !== "duplicate-campaign") return false;
  const c = current(), rerun = name === "rerun-campaign";
  pending = {cid: c.id, kind: rerun ? "rerun" : "duplicate", request_id: crypto.randomUUID()};
  $("#campaign-copy-form").reset();
  $("#campaign-copy-title").textContent = rerun ? "Volver a ejecutar la campaña" : "Duplicar como borrador";
  $("#campaign-copy-description").textContent = rerun
    ? `Se volverá a llamar a los ${c.total} contactos, incluidos quienes ya contestaron. Se conservarán el mensaje, las variables y el pool de transferencia. Los resultados anteriores seguirán disponibles en el historial.`
    : `Se copiarán los ${c.total} contactos, el mensaje, las variables y el pool de transferencia. La nueva campaña quedará como borrador en ${ctx.state.status.mode === "simulation" ? "simulación" : "SIP real"}, sin llamadas ni horarios heredados.`;
  $("#campaign-copy-name").value = rerun ? c.name : `${c.name.slice(0,92)} (copia)`;
  $("#campaign-copy-error").textContent = "";
  $("#campaign-copy-submit").textContent = rerun ? (ctx.state.status.mode === "simulation" ? "Crear e iniciar nueva simulación" : `Volver a llamar a ${c.total} contactos`) : "Crear borrador duplicado";
  $("#campaign-copy-form").hidden = false;
  $("#campaign-copy-name").focus({preventScroll:true});
  $("#campaign-copy-form").scrollIntoView({block:"nearest"});
  return true;
}

export function installCampaignHistory(context) {
  ctx = context;
  $("#execution-history").addEventListener("toggle", () => {
    if ($("#execution-history").open) refreshCampaignHistory().catch(error => { $("#execution-history-body").textContent = error.message; });
  });
  $("#campaign-copy-form").addEventListener("submit", event => {
    event.preventDefault();
    if (!pending || ctx.state.busy || !event.target.reportValidity()) return;
    const action = {...pending};
    const payload = {request_id: action.request_id, name: $("#campaign-copy-name").value, note: $("#campaign-copy-note").value};
    ctx.run(async () => {
      $("#campaign-copy-error").textContent = "";
      let result;
      try { result = await ctx.api(`/api/campaigns/${action.cid}/${action.kind}`, payload); }
      catch (error) { $("#campaign-copy-error").textContent = error.message; throw error; }
      closeCopy();
      ctx.state.current = result.id;
      ctx.state.selected = null;
      ctx.state.offset = 0;
      ctx.view("campaign");
      await ctx.refresh();
      ctx.notice(result.start_error ? `La nueva ejecución quedó como borrador: ${result.start_error}` : result.replayed ? "Esta solicitud ya se había guardado. Se abrió su resultado." : action.kind === "rerun" ? "Nueva ejecución iniciada. El historial anterior se conserva." : "Campaña duplicada como borrador. Puedes iniciarla desde este detalle.");
      $("#campaign-title").focus({preventScroll:true});
      $("#campaign-title").scrollIntoView({block:"start"});
    }, event.submitter);
  });
}
