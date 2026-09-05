import { locale, t, translateHTML, translateText } from "./i18n.js";

let clear = () => {};
export function clearAudioPreview() { clear(); }

export function installAudioPreview({api}) {
  const $ = selector => document.querySelector(selector);
  const button = $("#tts-preview-button"), audio = $("#tts-preview-audio");
  const status = $("#tts-preview-status"), result = $("#tts-preview-result");
  const performance = $("#tts-preview-performance");
  let url = null, revision = 0, pending = false;
  clear = () => {
    revision++;
    audio.pause(); audio.removeAttribute("src"); audio.load();
    if(url) URL.revokeObjectURL(url);
    url = null; result.hidden = true; performance.innerHTML = ""; status.textContent = "";
  };
  const changed = () => {
    const hadPreview = !!url || pending;
    clear();
    if(hadPreview) {
      status.textContent = t(pending ? "Los datos cambiaron. Espera a que termine y genera otra muestra." : "Los datos cambiaron. Pulsa Escuchar mensaje para actualizar la muestra.");
      $("#message-preview").textContent = t("Revisa o escucha el mensaje con los datos actualizados.");
      $("#preview-result").textContent = "";
    }
  };
  $("#campaign-form").addEventListener("input", event => {
    if(["message","contacts"].includes(event.target.id)) changed();
  });
  $("#template-picker").addEventListener("change", changed);
  $("#country").addEventListener("change", changed);
  $("#campaign-form").addEventListener("reset", clear);
  window.addEventListener("pagehide", clear);
  button.addEventListener("click", async () => {
    if(!$("#message").reportValidity()) return;
    if($("#contacts").validity.customError && !$("#contacts").reportValidity()) return;
    clear(); const current = revision;
    pending = true; button.disabled = true; button.textContent = t("Preparando mensaje…");
    status.textContent = t("Preparando la voz. La primera muestra puede tardar un poco más.");
    try {
      const data = await api("/api/preview/audio", {template:$("#message").value,csv_text:$("#contacts").value,country:$("#country").value});
      if(current !== revision) return;
      const bytes = Uint8Array.from(atob(data.audio_base64), char => char.charCodeAt(0));
      url = URL.createObjectURL(new Blob([bytes], {type:"audio/wav"}));
      audio.src = url; result.hidden = false;
      $("#message-preview").textContent = data.message;
      $("#tts-preview-caption").textContent = translateText(`Voz: ${data.voice} · ${data.phone ? "Primer contacto: " + data.phone : "Mensaje sin datos de contacto"}`);
      const rating=data.recommendation;
      performance.innerHTML=translateHTML(`<div class="voice-rating ${rating.code}"><strong>${translateText(rating.label)}</strong><p>${translateText(rating.detail)}</p></div><dl><div><dt>Tiempo de preparación</dt><dd>${(data.generation_ms/1000).toLocaleString(locale(),{minimumFractionDigits:2,maximumFractionDigits:2})} s</dd></div><div><dt>Duración del mensaje</dt><dd>${data.audio_seconds.toLocaleString(locale())} s</dd></div><div><dt>Disponibilidad de la voz</dt><dd>${data.model_cached?"Lista para usar":`Preparación inicial ${(data.load_ms/1000).toLocaleString(locale(),{minimumFractionDigits:2,maximumFractionDigits:2})} s`}</dd></div></dl>`);
      status.textContent = t("Audio listo. Puedes volver a escucharlo con el reproductor.");
      try { await audio.play(); }
      catch { status.textContent = t("Audio listo. Pulsa reproducir para escucharlo."); }
    } catch(error) {
      if(current === revision) status.textContent = error.message;
    } finally {
      pending = false; button.disabled = false; button.textContent = t("Escuchar mensaje");
      if(current !== revision && !$("#editor-view").hidden) status.textContent = t("Pulsa Escuchar mensaje para generar una muestra con los datos actuales.");
    }
  });
}
