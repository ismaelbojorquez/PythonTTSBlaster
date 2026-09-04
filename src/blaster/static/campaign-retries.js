const $ = selector => document.querySelector(selector);
const outcomes = {no_answer:"Sin respuesta", busy:"Ocupado", machine:"Buzón probable", amd_unknown:"AMD incierto", temporary_error:"Fallo temporal de la troncal"};
const defaults = {max_attempts:1, delay_seconds:300, outcomes:["no_answer", "busy", "machine", "amd_unknown"]};
let context;

export function retryDescription(policy = defaults) {
  if (policy.max_attempts === 1) return "Un intento por contacto · sin reintentos automáticos";
  const seconds = policy.delay_seconds;
  const wait = seconds % 3600 === 0 ? `${seconds / 3600} h` : seconds % 60 === 0 ? `${seconds / 60} min` : `${seconds} s`;
  return `Hasta ${policy.max_attempts} llamadas por contacto · ${wait} entre intentos`;
}

export function retryDate(value) {
  return value ? new Date(value).toLocaleString("es-MX", {dateStyle:"short", timeStyle:"medium"}) : "";
}

function fields(prefix) {
  return `<fieldset class="retry-fields"><legend>Reintentos sin contacto humano</legend>
    <p class="field-help">El límite incluye la primera llamada. Cada intento conserva su resultado y su grabación, cuando exista.</p>
    <div class="retry-controls"><div><label for="${prefix}-attempts">Máximo de intentos por contacto</label><input id="${prefix}-attempts" data-retry="attempts" type="number" min="1" max="10" step="1" value="1" required><p class="field-help">De 1 a 10. Usa 1 para no reintentar.</p></div>
    <div><label for="${prefix}-delay">Espera después de finalizar cada llamada</label><div class="retry-delay"><input id="${prefix}-delay" data-retry="delay" type="number" min="1" max="604800" step="1" value="5" required><select id="${prefix}-unit" data-retry="unit" aria-label="Unidad de espera"><option value="1">Segundos</option><option value="60" selected>Minutos</option><option value="3600">Horas</option></select></div><p class="field-help">Desde 1 segundo hasta 7 días.</p></div></div>
    <div class="retry-outcomes" role="group" aria-label="Resultados que permiten reintentar">${Object.entries(outcomes).map(([value,label]) => `<label><input type="checkbox" data-retry="outcome" value="${value}" ${defaults.outcomes.includes(value) ? "checked" : ""}><span>${label}</span></label>`).join("")}</div>
    <p class="retry-description field-help" aria-live="polite"></p>
    <p class="field-help">Se detienen los reintentos ante un humano probable, una interacción o el inicio del mensaje. La espera puede alargarse por una pausa o por capacidad disponible. Mantén la aplicación abierta y el equipo encendido.</p>
  </fieldset>`;
}

export function readRetryPolicy(root) {
  const attempts = Number(root.querySelector('[data-retry="attempts"]').value);
  return {
    max_attempts:attempts,
    // Inactive controls must not block saving a campaign with retries disabled.
    delay_seconds:attempts === 1 ? defaults.delay_seconds : Number(root.querySelector('[data-retry="delay"]').value) * Number(root.querySelector('[data-retry="unit"]').value),
    outcomes:[...root.querySelectorAll('[data-retry="outcome"]:checked')].map(field => field.value),
  };
}

function update(root) {
  const policy = readRetryPolicy(root), enabled = policy.max_attempts > 1;
  for (const field of root.querySelectorAll('[data-retry]:not([data-retry="attempts"])')) field.disabled = !enabled;
  const delay = root.querySelector('[data-retry="delay"]');
  delay.setCustomValidity(enabled && policy.delay_seconds > 604800 ? "La espera máxima es de 7 días." : "");
  root.querySelector('[data-retry="outcome"]').setCustomValidity(enabled && !policy.outcomes.length ? "Selecciona al menos un resultado para reintentar." : "");
  root.querySelector(".retry-description").textContent = retryDescription(policy);
}

function setPolicy(root, policy) {
  root.querySelector('[data-retry="attempts"]').value = policy.max_attempts;
  const unit = policy.delay_seconds % 3600 === 0 ? 3600 : policy.delay_seconds % 60 === 0 ? 60 : 1;
  root.querySelector('[data-retry="delay"]').value = policy.delay_seconds / unit;
  root.querySelector('[data-retry="unit"]').value = unit;
  for (const field of root.querySelectorAll('[data-retry="outcome"]')) field.checked = policy.outcomes.includes(field.value);
  update(root);
}

export function renderCampaignRetries(campaign) {
  const policy = campaign.retry_policy || defaults;
  $("#retry-policy-summary").textContent = retryDescription(policy);
  $("#retry-policy-outcomes").textContent = policy.max_attempts > 1 ? `Reintentar: ${policy.outcomes.map(value => outcomes[value]).join(", ")}.` : "Puedes configurar los reintentos mientras la campaña sea un borrador.";
  const summary = campaign.retry_summary;
  $("#retry-pending").textContent = summary?.pending ? `${summary.pending} reintentos pendientes. Próximo disponible: ${retryDate(summary.next_at)} (hora de este equipo).${campaign.status === "paused" ? " Reanuda la campaña para continuar." : ""}` : "";
  const form = $("#retry-policy-form"), editable = campaign.status === "draft" && context.state.user?.role !== "analyst";
  form.hidden = !editable;
  $("#retry-policy-locked").hidden = editable;
  const key = campaign.id + JSON.stringify(policy);
  if (form.dataset.key !== key) {
    form.dataset.key = key;
    setPolicy(form, policy);
    $("#retry-policy-result").textContent = "";
  }
}

export function installCampaignRetries(value) {
  context = value;
  for (const [selector,prefix] of [["#creator-retries","create-retry"],["#detail-retry-fields","edit-retry"]]) {
    const root = $(selector); root.innerHTML = fields(prefix);
    root.addEventListener("input", () => update(root));
    root.addEventListener("change", () => update(root));
    update(root);
  }
  $("#campaign-form").addEventListener("reset", () => queueMicrotask(() => setPolicy($("#creator-retries"), defaults)));
  $("#retry-policy-form").addEventListener("submit", event => {
    event.preventDefault();
    const cid = context.state.current, form = event.currentTarget, policy = readRetryPolicy(form);
    context.run(async () => {
      try {
        await context.api(`/api/campaigns/${cid}/retries`, policy);
        await context.refresh();
        $("#retry-policy-result").textContent = "Configuración de reintentos guardada.";
      } catch (error) { $("#retry-policy-result").textContent = error.message; }
    }, event.submitter);
  });
}
