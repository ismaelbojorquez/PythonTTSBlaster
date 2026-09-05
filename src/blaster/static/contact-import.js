import { getLanguage, t, translateText } from "./i18n.js";

export function installContactImport({api, expireSession, clearAudioPreview}) {
  const $ = selector => document.querySelector(selector);
  const contacts = $("#contacts"), fileInput = $("#csv-file"), message = $("#message");
  const status = $("#contacts-status"), list = $("#contact-variables");
  const sheetField = $("#contact-sheet-field"), sheetSelect = $("#contact-sheet");
  let revision = 0, timer, sourceFile = null;

  function clearPreview() {
    $("#message-preview").textContent = t("Revisa o escucha el mensaje con los datos actualizados.");
    $("#preview-result").textContent = "";
  }
  function showVariables(data) {
    list.replaceChildren();
    for (const variable of data.variables) {
      const button = document.createElement("button");
      button.type = "button"; button.className = "variable-insert";
      const token = `{${variable.name}}`;
      const label = document.createElement("code"); label.textContent = token;
      const sample = document.createElement("span");
      sample.textContent = variable.sample || t("Sin valor en la primera fila");
      button.title = translateText(`Insertar ${token}. Ejemplo: ${sample.textContent}`);
      button.setAttribute("aria-label", translateText(`Insertar ${token}`));
      button.append(label, sample);
      button.addEventListener("click", () => {
        const start = message.selectionStart, end = message.selectionEnd;
        if (message.value.length - (end - start) + token.length > message.maxLength) {
          status.textContent = t("El mensaje admite hasta 4000 caracteres. Acórtalo para agregar este dato.");
          return;
        }
        message.setRangeText(token, start, end, "end");
        message.dispatchEvent(new Event("input", {bubbles:true}));
        message.focus();
      });
      list.append(button);
    }
    $("#variables-empty").hidden = data.variables.length > 0;
  }
  function edited() {
    const current = ++revision;
    clearTimeout(timer); clearPreview(); showVariables({variables:[]});
    contacts.setCustomValidity("");
    if (!contacts.value.trim()) { status.textContent = ""; return; }
    status.textContent = t("Revisando datos…");
    timer = setTimeout(async () => {
      try {
        const data = await api("/api/contacts/inspect", {csv_text:contacts.value});
        if (current !== revision) return;
        showVariables(data);
        status.textContent = translateText(`${data.count} contactos · ${data.variables.length} datos disponibles. Revisa la personalización para validar los teléfonos y el mensaje.`);
      } catch (error) {
        if (current === revision) status.textContent = error.message;
      }
    }, 400);
  }
  contacts.addEventListener("input", edited);
  message.addEventListener("input", clearPreview);
  async function loadFile(file, sheet = "") {
    const current = ++revision;
    clearTimeout(timer);
    // A failed replacement must not silently leave the previous recipients ready to send.
    contacts.setCustomValidity(t("Importa un archivo válido o edita los contactos para continuar."));
    clearAudioPreview();
    clearPreview(); showVariables({variables:[]});
    status.textContent = t("Importando contactos…");
    fileInput.disabled = true; sheetSelect.disabled = true;
    try {
      if (file.size > 8_000_000) throw new Error(t("El archivo supera 8 MB. Divide la lista en campañas más pequeñas."));
      const query = new URLSearchParams({filename:file.name, sheet});
      const response = await fetch(`/api/contacts/import?${query}`, {
        method:"POST", headers:{"Content-Type":"application/octet-stream","Accept-Language":getLanguage()}, body:file,
      });
      if (response.status === 401) expireSession();
      const data = await response.json();
      if (!response.ok) throw new Error(translateText(data.detail || "No se pudo importar el archivo."));
      if (current !== revision) return;
      sheetSelect.replaceChildren();
      for (const name of data.sheets) {
        const option = document.createElement("option"); option.value = name; option.textContent = name;
        sheetSelect.append(option);
      }
      sheetSelect.value = data.sheet; sheetField.hidden = data.sheets.length < 2;
      contacts.value = data.csv_text;
      contacts.dispatchEvent(new Event("input", {bubbles:true}));
      clearTimeout(timer);
      showVariables(data);
      status.textContent = translateText(`${file.name}${data.sheet ? " · " + data.sheet : ""}: ${data.count} contactos y ${data.variables.length} datos personalizados listos para usar.`);
    } catch (error) {
      if (current === revision) status.textContent = error.message;
    } finally {
      fileInput.disabled = false; sheetSelect.disabled = false;
      fileInput.value = "";
    }
  }
  fileInput.addEventListener("change", () => {
    const file = fileInput.files[0];
    if (!file) return;
    sourceFile = file; sheetField.hidden = true;
    loadFile(file);
  });
  sheetSelect.addEventListener("change", () => { if (sourceFile) loadFile(sourceFile, sheetSelect.value); });
  $("#campaign-form").addEventListener("reset", () => {
    revision++; clearTimeout(timer); sourceFile = null;
    sheetField.hidden = true; status.textContent = "";
    contacts.setCustomValidity(""); showVariables({variables:[]});
  });
}
