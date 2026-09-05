"use strict";

import { t, translateHTML } from "./i18n.js";

const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);

export function recordingMarkup(result, role, heading = 2) {
  const r = result.recording;
  const title = heading === 3 ? "h3" : "h2";
  const allowed = role === "admin" || role === "operator";
  const status = t({recording:"Grabando",encoding:"Procesando audio",ready:"Lista para escuchar",expired:"Conservación vencida",failed:"No disponible"}[r?.status] || "Sin grabación");
  const hints = {
    recording: "El audio estará disponible cuando termine la llamada y se procese.",
    encoding: "Estamos preparando la grabación. Aparecerá aquí automáticamente.",
    expired: "El audio se eliminó al cumplirse el plazo de conservación.",
    failed: r?.detail || "No se pudo guardar el audio de esta llamada."
  };
  const empty = t(result.status === "queued" ? "La llamada aún no ha iniciado." : "No hay audio guardado para esta llamada. La captura requiere grabaciones activas y evidencia de voz humana o interacción del teclado.");
  const duration = r?.duration_seconds == null ? "" : `${Math.floor(r.duration_seconds / 60)}:${String(Math.floor(r.duration_seconds % 60)).padStart(2,"0")} min · `;
  const evidence = t(r?.evidence === "amd_human_probable" ? "Comienza cuando se identifica una persona probable." : r?.evidence === "amd_inconclusive_continued" ? "Comienza cuando la llamada continúa después de evaluar la respuesta." : r?.evidence === "dtmf_interaction" ? "Comienza cuando el cliente selecciona una opción." : "");
  const url = `/api/recordings/${encodeURIComponent(result.id)}`;
  return translateHTML(`<section class="recording-panel"><div><${title}>Grabación de llamada</${title}><p class="recording-status">${esc(status)}</p>${r ? `<p class="recording-meta">${duration}${result.mode === "simulation" ? " · Muestra de prueba" : ""}</p>` : ""}</div>${r?.status === "ready" && allowed ? `<audio controls preload="none" src="${url}" aria-label="Grabación de la llamada"></audio><a class="text-link" download href="${url}">Descargar audio</a><p class="recording-error" role="status" hidden>No se pudo reproducir el audio. Intenta descargarlo; si ya no está disponible, recarga el detalle.</p>` : `<p class="recording-help">${esc(!allowed ? t("Tu perfil no permite escuchar grabaciones.") : r ? t(hints[r.status] || "El audio no está disponible.") : empty)}</p>`}${evidence ? `<p class="recording-meta">${evidence}</p>` : ""}</section>`);
}

export function stopRecordings(root = document) {
  root.querySelectorAll(".recording-panel audio").forEach(audio => audio.pause());
}

export function installRecordingPlayback() {
  document.addEventListener("play", event => {
    if (!event.target.matches?.(".recording-panel audio")) return;
    document.querySelectorAll("audio").forEach(audio => { if (audio !== event.target) audio.pause(); });
  }, true);
  document.addEventListener("error", event => {
    if (!event.target.matches?.(".recording-panel audio")) return;
    const hint = event.target.closest(".recording-panel").querySelector(".recording-error");
    if (hint) hint.hidden = false;
  }, true);
}
