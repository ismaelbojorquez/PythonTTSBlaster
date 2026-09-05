import { t, translateText } from "./i18n.js";

export const strategyNames = {round_robin:t("Rotación en orden"),random:t("Aleatoria"),priority:t("Prioridad de lista")};
export const strategyHelp = {
  round_robin:t("Continúa desde el siguiente número y omite los ocupados."),
  random:t("Elige al azar entre los teléfonos libres; un número puede repetirse después de quedar disponible."),
  priority:t("Elige el primer teléfono libre según el orden de la lista.")
};

export function installAgentPool() {
  const select = document.querySelector("#agent-strategy");
  const update = () => { document.querySelector("#agent-strategy-help").textContent = strategyHelp[select.value]; };
  select.addEventListener("change", update);
  document.querySelector("#campaign-form").addEventListener("reset", () => queueMicrotask(update));
}

export function renderAgentPool(campaign, status, escape, setHTML) {
  const numbers = campaign.agent_numbers || [campaign.agent_number];
  const busy = new Map((status.agent_pool?.reservations || []).flatMap(r => [[r.number,r], [r.configured_number || r.number,r]]));
  const selectedIsActive = status.active_campaign === campaign.id;
  const free = selectedIsActive && Number.isInteger(status.agent_pool?.free)
    ? status.agent_pool.free
    : numbers.filter(n => !busy.has(n)).length;
  const waiting = campaign.counts.agent_waiting || 0;
  document.querySelector("#transfer-summary").textContent = translateText(`Disponibilidad de agentes · ${free} de ${numbers.length} libres${waiting ? ` · ${waiting} en espera` : ""}`);
  document.querySelector("#transfer-policy").textContent = selectedIsActive && status.origination_paused
    ? t("La campaña se pausó automáticamente hasta que un agente quede disponible.")
    : translateText(`${strategyNames[campaign.agent_strategy] || strategyNames.round_robin} · Espera máxima ${campaign.agent_pool_wait ?? 30} s cuando todos están ocupados.`);
  const labels = {bridged:t("En conversación"),closing:t("Esperando confirmación de cierre")};
  setHTML(document.querySelector("#transfer-numbers"), numbers.map(number => {
    const reservation = busy.get(number);
    return `<li><span>${escape(number)}</span><span class="badge ${reservation ? "agent_dialing" : "live"}">${reservation ? labels[reservation.state] || t("Reservado") : t("Libre")}</span></li>`;
  }).join(""));
}
