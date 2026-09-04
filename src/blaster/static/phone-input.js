export function removePhonePlus(value) {
  return value.replace(/\+/g, "");
}

export function removeCsvPhonePlus(value) {
  if (!value.includes("+")) return value;
  let start = value.match(/^\uFEFF*/)[0].length;
  let column = 0;
  let phoneColumn = -1;
  let header = true;
  let quoted = false;
  const removed = [];

  // Walk CSV fields without rewriting commas, quotes, line breaks, or variables.
  for (let i = start; i <= value.length; i++) {
    const char = value[i];
    if (char === '"') {
      if (quoted && value[i + 1] === '"') { i++; continue; }
      if (quoted || i === start) quoted = !quoted;
    }
    if (i < value.length && (quoted || ![",", "\r", "\n"].includes(char))) continue;
    if (header) {
      const name = value.slice(start, i).replace(/^"(.*)"$/, "$1").replace(/""/g, '"');
      if (name === "telefono") phoneColumn = column;
    } else if (column === phoneColumn) {
      for (let j = start; j < i; j++) if (value[j] === "+") removed.push(j);
    }
    if (char === ",") column++;
    else {
      header = false;
      column = 0;
      if (char === "\r" && value[i + 1] === "\n") i++;
    }
    start = i + 1;
  }
  const parts = [];
  let from = 0;
  for (const index of removed) {
    parts.push(value.slice(from, index));
    from = index + 1;
  }
  parts.push(value.slice(from));
  return parts.join("");
}

export function cleanPhoneInput(field, normalize) {
  const original = field.value;
  const cleaned = normalize(original);
  if (original === cleaned) return;
  const { selectionStart, selectionEnd, selectionDirection } = field;
  // Both normalizers only delete + signs; map the selection through those deletions.
  let next = 0;
  let start = 0;
  let end = 0;
  for (let i = 0; i < original.length; i++) {
    if (original[i] === cleaned[next]) next++;
    if (i < selectionStart) start = next;
    if (i < selectionEnd) end = next;
  }
  field.value = cleaned;
  field.setSelectionRange(start, end, selectionDirection);
}
