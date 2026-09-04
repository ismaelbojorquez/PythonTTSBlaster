const $ = selector => document.querySelector(selector);
let status = null, zoneReady = false;

export function executionChoice() {
  return $('#campaign-form input[name="execution"]:checked')?.value || "draft";
}

export function validCampaignForm(preview = false) {
  return [...$("#campaign-form").elements].every(field => {
    if (preview && field.closest("#campaign-schedule-fields")) return true;
    return !field.willValidate || field.reportValidity();
  });
}

export function updateExecutionStatus(value) {
  status = value;
  const zone = $("#campaign-timezone");
  if (!zoneReady && status) {
    const current = status.reporting_timezone || "America/Mexico_City";
    const available = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : ["America/Mexico_City", "America/Cancun", "America/Tijuana", "America/New_York", "Europe/Madrid"];
    zone.replaceChildren();
    for (const name of [...new Set([current, "UTC", ...available])]) {
      const option = document.createElement("option"); option.value = name; option.textContent = name;
      zone.append(option);
    }
    zone.value = current; zoneReady = true;
  }
  update();
}

function update() {
  const choice = executionChoice(), scheduled = choice === "scheduled";
  $("#campaign-schedule-fields").hidden = !scheduled;
  for (const id of ["#campaign-local-at", "#campaign-timezone"]) {
    $(id).disabled = !scheduled;
    $(id).required = scheduled;
  }
  const simulation = status?.mode !== "sip";
  $("#campaign-submit").textContent = choice === "draft" ? "Guardar borrador" : scheduled ? "Programar campaña" : simulation ? "Crear e iniciar simulación" : "Crear e iniciar llamadas";
  $("#execution-help").textContent = choice === "draft"
    ? "Se guardará sin llamar. Podrás iniciarla desde su panel cuando estés listo."
    : scheduled ? "La campaña se guardará y comenzará en la fecha y hora elegidas."
    : simulation ? "Al guardar comenzará la simulación con estos contactos."
    : "Al guardar comenzarán las llamadas a estos contactos por la troncal SIP.";
  $("#execution-warning").textContent = scheduled && status?.automation_enabled === false
    ? "Las tareas programadas están desactivadas. Actívalas en Configuración antes de programar."
    : choice === "now" && status?.active_campaign
    ? "Hay otra campaña en curso. Termínala o detenla antes de iniciar esta; también puedes guardarla como borrador o programarla."
    : choice === "now" && status && !status.ready
    ? "La troncal aún no está lista. Puedes guardar el borrador o programar la campaña."
    : "";
}

export function installCampaignExecution() {
  for (const radio of document.querySelectorAll('#campaign-form input[name="execution"]')) radio.addEventListener("change", update);
  $("#campaign-form").addEventListener("reset", () => queueMicrotask(() => {
    $("#campaign-save-error").textContent = "";
    zoneReady = false; updateExecutionStatus(status);
  }));
  update();
}

export function scheduleDescription(schedule) {
  if (!schedule) return "";
  const date = new Intl.DateTimeFormat("es-MX", {timeZone:schedule.timezone, dateStyle:"long", timeStyle:"short"}).format(new Date(schedule.due_at));
  return `Programada para el ${date} · ${schedule.timezone}. Mantén la aplicación abierta y el equipo encendido.`;
}
