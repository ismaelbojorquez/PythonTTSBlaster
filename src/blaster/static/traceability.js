"use strict";

import { getLanguage, locale, t, translateText } from "./i18n.js";
import { countryExample } from "./countries.js";

const $ = selector => document.querySelector(selector);
let ctx, current = null, offset = 0;
const pageSize = 100;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[character]);
}
function number(value) { return new Intl.NumberFormat(locale()).format(value || 0); }
function date(value) {
  return value ? new Date(value).toLocaleString(locale(), {dateStyle:"medium",timeStyle:"short"}) : "—";
}
function bytes(value) {
  if (!value) return "0 MB";
  return `${(value / 1048576).toLocaleString(locale(), {maximumFractionDigits:1})} MB`;
}
export function traceIdentifier(by, value, country = "MX") {
  let query = String(value || "").trim();
  if (by === "phone") {
    query = query.replace(/[ ()-]/g, "");
    return {by, query, country};
  }
  return {by, query};
}
function normalized() {
  const by = $("#traceability-by").value;
  return traceIdentifier(by, $("#traceability-query").value, $("#traceability-country").value || "MX");
}
function params(withOffset = false) {
  const value = new URLSearchParams(current);
  if (withOffset) { value.set("limit", pageSize); value.set("offset", offset); }
  return value.toString();
}
function recording(row) {
  const labels = {ready:"Disponible",recording:"Grabando",encoding:"Procesando",expired:"Vencida",failed:"Fallida"};
  return t(labels[row.recording_status] || "Sin grabación");
}
function trunk(row) {
  const id = row.customer_trunk_id;
  if (!id) return t("Sin asignar");
  const name = row.customer_trunk_name
    || ctx.state.status?.trunks?.find(item => item.id === id)?.name;
  return ctx.commercialText(name || id);
}
function render(data) {
  const {metrics} = data;
  $("#traceability-result").hidden = false;
  $("#traceability-empty").hidden = true;
  $("#traceability-feedback").textContent = translateText(data.total
    ? `${number(data.total)} llamadas encontradas. Puedes abrir el detalle o descargar el historial.`
    : "No se encontraron llamadas iniciadas. Verifica el crédito o teléfono.");
  $("#traceability-title").textContent = translateText(current.by === "credit" ? `Crédito ${current.query}` : `Teléfono ${current.query}`);
  $("#traceability-scope").textContent = translateText(`${number(data.total)} llamadas iniciadas en ${number(metrics.campaigns)} campañas`);
  ctx.setHTML($("#traceability-summary"), [
    ["Llamadas realizadas", metrics.calls],
    ["Llamadas contestadas", metrics.answered],
    ["Con agente", metrics.bridged],
    ["Grabaciones disponibles", `${number(metrics.recordings)} · ${bytes(metrics.recording_bytes)}`],
  ].map(([label,value]) => `<div><dt>${esc(label)}</dt><dd>${typeof value === "number" ? number(value) : esc(value)}</dd></div>`).join(""));
  const rows = data.items.map(row => `<tr><td><time datetime="${esc(row.started_at)}">${esc(date(row.started_at))}</time><button class="text-link trace-date" data-action="open-cdr" data-origin="traceability" data-id="${esc(row.id)}">Ver detalle</button></td><td>${esc(row.campaign_name)}</td><td class="trace-identifier">${esc(row.credit_id || "Sin crédito histórico")}</td><td class="trace-identifier">${esc(row.phone)}</td><td><span class="trunk-cell">${esc(trunk(row))}</span></td><td>${number(row.attempt_number || 1)}</td><td>${ctx.badge(row.status)}</td><td><span class="recording-state">${esc(recording(row))}</span>${row.recording_status === "ready" && ctx.state.user?.role !== "analyst" ? `<a class="text-link" href="/api/recordings/${encodeURIComponent(row.id)}">Abrir audio</a>` : ""}</td></tr>`).join("");
  ctx.setHTML($("#traceability-rows"), rows || '<tr><td colspan="8" class="no-measurements">No hay llamadas iniciadas para este cliente.</td></tr>');
  $("#traceability-page").textContent = data.total ? `${number(offset + 1)}–${number(Math.min(offset + data.items.length, data.total))} ${t("de")} ${number(data.total)}` : translateText("0 llamadas");
  $("#trace-previous").disabled = offset === 0;
  $("#trace-next").disabled = offset + pageSize >= data.total;
  $("#traceability-xlsx").href = `/api/traceability/report.xlsx?${params()}&lang=${getLanguage()}`;
  $("#traceability-bundle").href = `/api/traceability/bundle.zip?${params()}&lang=${getLanguage()}`;
  $("#traceability-bundle").hidden = ctx.state.user?.role === "analyst";
}
async function search(nextOffset = 0) {
  current = normalized();
  if (!current.query) {
    $("#traceability-feedback").textContent = translateText(`Escribe el ${current.by === "credit" ? "crédito" : "teléfono"} que deseas consultar.`);
    $("#traceability-query").focus();
    return;
  }
  offset = nextOffset;
  $("#traceability-feedback").textContent = t("Consultando historial…");
  $("#traceability-result").setAttribute("aria-busy", "true");
  try {
    render(await ctx.api(`/api/traceability?${params(true)}`));
  } catch (error) {
    $("#traceability-feedback").textContent = translateText(`${error.message}. Revisa el crédito o teléfono e intenta de nuevo.`);
  } finally {
    $("#traceability-result").removeAttribute("aria-busy");
  }
}
function updateField() {
  const phone = $("#traceability-by").value === "phone";
  const label = $("label[for=traceability-query]");
  $("#traceability-country-field").hidden = !phone;
  $("#traceability-form").classList.toggle("phone-search", phone);
  label.textContent = t(phone ? "Teléfono nacional" : "Crédito exacto");
  const example = countryExample($("#traceability-country").value || "MX") || "55 7856 4016";
  $("#traceability-query").placeholder = phone ? example : t("Ej. CRED-000184");
  $("#traceability-help").textContent = t(phone
    ? "Selecciona el país y escribe el teléfono sin código internacional. También puedes pegar un número completo con +."
    : "La búsqueda por crédito es exacta.");
}
async function download(link, filename) {
  $("#traceability-feedback").textContent = t(
    filename.endsWith(".zip")
      ? "Preparando grabaciones y reporte…"
      : "Preparando el reporte Excel…");
  link.setAttribute("aria-disabled", "true");
  try {
    const response = await fetch(link.href, {headers:{"Accept-Language":getLanguage()}});
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(ctx.commercialError(error.detail || "No se pudo preparar la descarga"));
    }
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = filename; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    $("#traceability-feedback").textContent = t("Descarga preparada.");
  } catch (error) {
    $("#traceability-feedback").textContent = error.message;
  } finally {
    link.removeAttribute("aria-disabled");
  }
}

export async function traceabilityAction(name) {
  if (name === "nav-traceability") {
    ctx.view("traceability");
    updateField();
    $("#traceability-query").focus();
    return true;
  }
  if (name === "trace-previous" || name === "trace-next") {
    await search(Math.max(0, offset + (name === "trace-next" ? pageSize : -pageSize)));
    return true;
  }
  return false;
}

export function installTraceability(context) {
  ctx = context;
  $("#traceability-by").addEventListener("change", updateField);
  $("#traceability-country").addEventListener("change", updateField);
  document.addEventListener("countries:loaded", updateField);
  $("#traceability-form").addEventListener("submit", event => {
    event.preventDefault();
    ctx.run(() => search(0), event.submitter);
  });
  $("#traceability-xlsx").addEventListener("click", event => {
    event.preventDefault();
    if (!event.currentTarget.hasAttribute("aria-disabled")) {
      download(event.currentTarget, getLanguage() === "en" ? "blaster-customer-history.xlsx" : "blaster-trazabilidad.xlsx");
    }
  });
  $("#traceability-bundle").addEventListener("click", event => {
    event.preventDefault();
    if (!event.currentTarget.hasAttribute("aria-disabled")) {
      download(event.currentTarget, getLanguage() === "en" ? "blaster-customer-recordings.zip" : "blaster-trazabilidad-grabaciones.zip");
    }
  });
  document.addEventListener("traceability:restore", event => {
    const target = [...document.querySelectorAll('[data-action="open-cdr"][data-origin="traceability"]')]
      .find(element => element.dataset.id === event.detail?.id);
    target?.focus({preventScroll:true});
    target?.scrollIntoView({block:"center"});
  });
}
