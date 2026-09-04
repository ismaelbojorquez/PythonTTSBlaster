let clear = () => {};
export function clearAudioPreview() { clear(); }

export function installAudioPreview({api}) {
  const $ = selector => document.querySelector(selector);
  const button = $("#tts-preview-button"), audio = $("#tts-preview-audio");
  const status = $("#tts-preview-status"), result = $("#tts-preview-result");
  let url = null, revision = 0, pending = false;
  clear = () => {
    revision++;
    audio.pause(); audio.removeAttribute("src"); audio.load();
    if(url) URL.revokeObjectURL(url);
    url = null; result.hidden = true; status.textContent = "";
  };
  const changed = () => {
    const hadPreview = !!url || pending;
    clear();
    if(hadPreview) {
      status.textContent = pending ? "Los datos cambiaron. Espera a que termine y genera otra muestra." : "Los datos cambiaron. Pulsa Escuchar TTS para actualizar la muestra.";
      $("#message-preview").textContent = "Revisa o escucha el mensaje con los datos actualizados.";
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
    pending = true; button.disabled = true; button.textContent = "Generando audio…";
    status.textContent = "Preparando la voz local. La primera muestra puede tardar un poco más.";
    try {
      const data = await api("/api/preview/audio", {template:$("#message").value,csv_text:$("#contacts").value,country:$("#country").value});
      if(current !== revision) return;
      const bytes = Uint8Array.from(atob(data.audio_base64), char => char.charCodeAt(0));
      url = URL.createObjectURL(new Blob([bytes], {type:"audio/wav"}));
      audio.src = url; result.hidden = false;
      $("#message-preview").textContent = data.message;
      $("#tts-preview-caption").textContent = `Voz: ${data.voice} · ${data.phone ? "Primer contacto: " + data.phone : "Mensaje sin datos de contacto"}`;
      status.textContent = "Audio listo. Puedes volver a escucharlo con el reproductor.";
      try { await audio.play(); }
      catch { status.textContent = "Audio listo. Pulsa reproducir para escucharlo."; }
    } catch(error) {
      if(current === revision) status.textContent = error.message;
    } finally {
      pending = false; button.disabled = false; button.textContent = "Escuchar TTS";
      if(current !== revision && !$("#editor-view").hidden) status.textContent = "Pulsa Escuchar TTS para generar una muestra con los datos actuales.";
    }
  });
}
