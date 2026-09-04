"use strict";

const $ = selector => document.querySelector(selector);
let ctx, current = null, offset = 0;
const pageSize = 100;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[character]);
}
function number(value) { return new Intl.NumberFormat("es-MX").format(value || 0); }
function date(value) {
  return value ? new Date(value).toLocaleString("es-MX", {dateStyle:"medium",timeStyle:"short"}) : "—";
}
function bytes(value) {
  if (!value) return "0 MB";
  return `${(value / 1048576).toLocaleString("es-MX", {maximumFractionDigits:1})} MB`;
}
export function traceIdentifier(by, value) {
  let query = String(value || "").trim();
  if (by === "phone") query = query.replace(/[+ ()-]/g, "");
  return {by, query};
}
function normalized() {
  const by = $("#traceability-by").value;
  return traceIdentifier(by, $("#traceability-query").value);
}
function params(withOffset = false) {
  const value = new URLSearchParams(current);
  if (withOffset) { value.set("limit", pageSize); value.set("offset", offset); }
  return value.toString();
}
function recording(row) {
  const labels = {ready:"Disponible",recording:"Grabando",encoding:"Procesando",expired:"Vencida",failed:"Fallida"};
  return labels[row.recording_status] || "Sin grabación";
}
function render(data) {
  const {metrics} = data;
  $("#traceability-result").hidden = false;
  $("#traceability-empty").hidden = true;
  $("#traceability-feedback").textContent = data.total
    ? `${number(data.total)} llamadas encontradas. Puedes abrir un CDR o descargar el historial.`
    : "No se encontraron llamadas iniciadas. Verifica el identificador exacto.";
  $("#traceability-title").textContent = current.by === "credit" ? `Credito ${current.query}` : `Telefono ${current.query}`;
  $("#traceability-scope").textContent = `${number(data.total)} llamadas iniciadas en ${number(metrics.campaigns)} campañas`;
  ctx.setHTML($("#traceability-summary"), [
    ["Blasters enviados", metrics.calls],
    ["Llamadas contestadas", metrics.answered],
    ["Con agente", metrics.bridged],
    ["Grabaciones disponibles", `${number(metrics.recordings)} · ${bytes(metrics.recording_bytes)}`],
  ].map(([label,value]) => `<div><dt>${esc(label)}</dt><dd>${typeof value === "number" ? number(value) : esc(value)}</dd></div>`).join(""));
  const rows = data.items.map(row => `<tr><td><time datetime="${esc(row.started_at)}">${esc(date(row.started_at))}</time><button class="text-link trace-date" data-action="open-cdr" data-origin="traceability" data-id="${esc(row.id)}">Ver CDR</button></td><td>${esc(row.campaign_name)}</td><td class="trace-identifier">${esc(row.credit_id || "Sin crédito histórico")}</td><td class="trace-identifier">${esc(row.phone)}</td><td>${number(row.attempt_number || 1)}</td><td>${ctx.badge(row.status)}</td><td><span class="recording-state">${esc(recording(row))}</span>${row.recording_status === "ready" && ctx.state.user?.role !== "analyst" ? `<a class="text-link" href="/api/recordings/${encodeURIComponent(row.id)}">Abrir audio</a>` : ""}</td></tr>`).join("");
  ctx.setHTML($("#traceability-rows"), rows || '<tr><td colspan="7" class="no-measurements">No hay llamadas iniciadas para este identificador.</td></tr>');
  $("#traceability-page").textContent = data.total ? `${number(offset + 1)}–${number(Math.min(offset + data.items.length, data.total))} de ${number(data.total)}` : "0 llamadas";
  $("#trace-previous").disabled = offset === 0;
  $("#trace-next").disabled = offset + pageSize >= data.total;
  $("#traceability-xlsx").href = `/api/traceability/report.xlsx?${params()}`;
  $("#traceability-bundle").href = `/api/traceability/bundle.zip?${params()}`;
  $("#traceability-bundle").hidden = ctx.state.user?.role === "analyst";
}
async function search(nextOffset = 0) {
  current = normalized();
  if (!current.query) {
    $("#traceability-feedback").textContent = `Escribe el ${current.by === "credit" ? "Credito" : "Telefono"} que deseas consultar.`;
    $("#traceability-query").focus();
    return;
  }
  offset = nextOffset;
  $("#traceability-feedback").textContent = "Consultando historial…";
  $("#traceability-result").setAttribute("aria-busy", "true");
  try {
    render(await ctx.api(`/api/traceability?${params(true)}`));
  } catch (error) {
    $("#traceability-feedback").textContent = `${error.message}. Revisa el identificador e intenta de nuevo.`;
  } finally {
    $("#traceability-result").removeAttribute("aria-busy");
  }
}
function updateField() {
  const phone = $("#traceability-by").value === "phone";
  const label = $("label[for=traceability-query]");
  label.textContent = phone ? "Telefono completo" : "Credito exacto";
  $("#traceability-query").placeholder = phone ? "Ej. +52 55 1234 5678" : "Ej. CRED-000184";
}
async function download(link, filename) {
  $("#traceability-feedback").textContent =
    filename.endsWith(".zip")
      ? "Preparando grabaciones, manifiesto y reporte…"
      : "Preparando el reporte Excel…";
  link.setAttribute("aria-disabled", "true");
  try {
    const response = await fetch(link.href);
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || "No se pudo preparar la descarga");
    }
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = filename; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    $("#traceability-feedback").textContent = "Descarga preparada.";
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
  $("#traceability-form").addEventListener("submit", event => {
    event.preventDefault();
    ctx.run(() => search(0), event.submitter);
  });
  $("#traceability-xlsx").addEventListener("click", event => {
    event.preventDefault();
    if (!event.currentTarget.hasAttribute("aria-disabled")) {
      download(event.currentTarget, "blaster-trazabilidad.xlsx");
    }
  });
  $("#traceability-bundle").addEventListener("click", event => {
    event.preventDefault();
    if (!event.currentTarget.hasAttribute("aria-disabled")) {
      download(event.currentTarget, "blaster-trazabilidad-grabaciones.zip");
    }
  });
  document.addEventListener("traceability:restore", event => {
    const target = [...document.querySelectorAll('[data-action="open-cdr"][data-origin="traceability"]')]
      .find(element => element.dataset.id === event.detail?.id);
    target?.focus({preventScroll:true});
    target?.scrollIntoView({block:"center"});
  });
}
