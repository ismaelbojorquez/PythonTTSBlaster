import { getLanguage, locale, t, translateText } from "./i18n.js";

const $ = selector => document.querySelector(selector);
let regions = [{code:"MX", calling_code:"52", example:"55 1234 5678"}];
let loaded = false;
const displayNames = () => typeof Intl.DisplayNames === "function" ? new Intl.DisplayNames([locale()], {type:"region"}) : null;
export const countryLabel = code => displayNames()?.of(code) || code;
export const countryOptions = () => regions.map(r => [r.code, `${countryLabel(r.code)} (+${r.calling_code})`]);
export const countryExample = code => regions.find(region => region.code === code)?.example || "";

function updateHints() {
  const region = regions.find(r => r.code === $("#country").value);
  const agent = regions.find(r => r.code === ($("#agent-country").value || region.code));
  const example = region.example.replace(/\D/g, "");
  $("#country-help").textContent = translateText(`Escribe los contactos sin el código +${region.calling_code}. Se agregará automáticamente al marcar.`);
  $("#contacts").placeholder = getLanguage() === "en"
    ? `Account,Phone,name,date\nACC-001,${example},Ana,Friday September 12`
    : `Credito,Telefono,nombre,fecha\nCRED-001,${example},Ana,viernes 12 de septiembre`;
  $("#agent-number").placeholder = agent.example;
  $("#agent-help").textContent = translateText(`Un número nacional por línea, sin +${agent.calling_code}. Puedes usar un solo teléfono o hasta 50.`);
}

export async function loadCountries(api) {
  if(loaded) return;
  const data = await api("/api/countries");
  regions = data.sort((a,b) => countryLabel(a.code).localeCompare(countryLabel(b.code), locale()));
  for(const id of ["#country", "#agent-country", "#traceability-country"]) {
    const select = $(id);
    if(!select) continue;
    const value = select.value;
    select.replaceChildren();
    if(id === "#agent-country") select.add(new Option(t("Mismo país que los contactos"), ""));
    for(const [code,label] of countryOptions()) select.add(new Option(label, code, id !== "#agent-country" && code === "MX"));
    select.value = value || (id === "#agent-country" ? "" : "MX");
  }
  loaded = true;
  updateHints();
  document.dispatchEvent(new CustomEvent("countries:loaded"));
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
    $("#message-preview").textContent = t("Revisa o escucha el mensaje con el país seleccionado.");
    $("#preview-result").textContent = "";
  };
  $("#country").addEventListener("change", invalidate);
  $("#agent-country").addEventListener("change", invalidate);
  $("#campaign-form").addEventListener("reset", () => queueMicrotask(updateHints));
  updateHints();
}
