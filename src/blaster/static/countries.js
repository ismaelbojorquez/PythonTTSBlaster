const $ = selector => document.querySelector(selector);
let regions = [{code:"MX", calling_code:"52", example:"55 1234 5678"}];
let loaded = false;
const names = typeof Intl.DisplayNames === "function" ? new Intl.DisplayNames(["es"], {type:"region"}) : null;
export const countryLabel = code => names?.of(code) || code;
export const countryOptions = () => regions.map(r => [r.code, `${countryLabel(r.code)} (+${r.calling_code})`]);

function updateHints() {
  const region = regions.find(r => r.code === $("#country").value);
  const agent = regions.find(r => r.code === ($("#agent-country").value || region.code));
  const example = region.example.replace(/\D/g, "");
  $("#country-help").textContent = `Escribe los contactos sin el prefijo +${region.calling_code}. Se agregará automáticamente al marcar.`;
  $("#contacts").placeholder = `Credito,Telefono,nombre,fecha\nCRED-001,${example},Ana,viernes 12 de septiembre`;
  $("#agent-number").placeholder = agent.example;
  $("#agent-help").textContent = `Un número nacional por línea, sin +${agent.calling_code}. Puedes usar un solo teléfono o hasta 50.`;
}

export async function loadCountries(api) {
  if(loaded) return;
  const data = await api("/api/countries");
  regions = data.sort((a,b) => countryLabel(a.code).localeCompare(countryLabel(b.code), "es"));
  for(const id of ["#country", "#agent-country"]) {
    const select = $(id), value = select.value;
    select.replaceChildren();
    if(id === "#agent-country") select.add(new Option("Mismo país que los contactos", ""));
    for(const [code,label] of countryOptions()) select.add(new Option(label, code, id === "#country" && code === "MX"));
    select.value = value;
  }
  loaded = true;
  updateHints();
}

export function applyTemplateAgent(template) {
  if(!template.agent_number) return;
  $("#agent-country").value = template.agent_country || "";
  $("#agent-number").value = (template.agent_numbers_national || [template.agent_national || template.agent_number]).join("\n");
  $("#agent-strategy").value = template.agent_strategy || "round_robin";
  $("#agent-pool-wait").value = template.agent_pool_wait ?? 30;
  $("#agent-strategy").dispatchEvent(new Event("change", {bubbles:true}));
  $("#agent-country").dispatchEvent(new Event("change", {bubbles:true}));
}

export function installCountryFields() {
  const invalidate = () => {
    updateHints();
    $("#message-preview").textContent = "Revisa o escucha el mensaje con el país seleccionado.";
    $("#preview-result").textContent = "";
  };
  $("#country").addEventListener("change", invalidate);
  $("#agent-country").addEventListener("change", invalidate);
  $("#campaign-form").addEventListener("reset", () => queueMicrotask(updateHints));
  updateHints();
}
