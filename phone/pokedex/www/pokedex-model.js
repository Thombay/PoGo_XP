export const SPECIES_COLUMNS = [
  "date",
  "account",
  "entry_type",
  "dex_number",
  "form",
  "registered",
  "can_evolve_now",
  "notes",
];

export const REFERENCE_COLUMNS = [
  "dex_number",
  "name",
  "german_name",
  "region",
  "region_label",
  "form",
  "entry_type",
  "entry_type_label",
  "available",
  "location_restriction",
  "last_event",
];

export const ACCOUNTS_COLUMNS = ["account"];

export function todayLocalIso(now = new Date()) {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function isTrue(value) {
  return String(value ?? "").trim().toLowerCase() === "true";
}

export function spriteUrl(dexNumber) {
  const raw = String(dexNumber ?? "").trim();
  const numeric = /^\d+$/.test(raw) ? String(Number(raw)) : raw;
  return `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/${numeric}.png`;
}

function csvField(value) {
  const text = String(value ?? "");
  if (/[",\r\n]/.test(text)) return `"${text.replaceAll('"', '""')}"`;
  return text;
}

export function parseCsv(text) {
  const source = String(text ?? "").replace(/^\uFEFF/, "");
  if (!source.trim()) return [];
  const table = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    if (quoted) {
      if (char === '"') {
        if (source[index + 1] === '"') {
          field += '"';
          index += 1;
        } else {
          quoted = false;
        }
      } else {
        field += char;
      }
      continue;
    }
    if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && source[index + 1] === "\n") index += 1;
      row.push(field);
      table.push(row);
      row = [];
      field = "";
    } else {
      field += char;
    }
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    table.push(row);
  }
  if (!table.length) return [];
  const headers = table[0].map((header) => header.trim());
  const records = [];
  for (let index = 1; index < table.length; index += 1) {
    const cells = table[index];
    if (cells.every((cell) => cell === "")) continue;
    const record = {};
    headers.forEach((header, cellIndex) => {
      if (!header) return;
      record[header] = cells[cellIndex] ?? "";
    });
    records.push(record);
  }
  return records;
}

export function serializeCsv(headers, rows) {
  const lines = [headers.join(",")];
  rows.forEach((row) => {
    lines.push(headers.map((header) => csvField(row[header] ?? "")).join(","));
  });
  return `${lines.join("\n")}\n`;
}

export function parseSpeciesCsv(text) {
  return parseCsv(text).map((row) => {
    const record = { ...row };
    SPECIES_COLUMNS.forEach((column) => {
      if (record[column] == null) record[column] = "";
    });
    return record;
  });
}

export function serializeSpeciesCsv(rows) {
  const extras = [];
  rows.forEach((row) => {
    Object.keys(row).forEach((key) => {
      if (!SPECIES_COLUMNS.includes(key) && !extras.includes(key)) extras.push(key);
    });
  });
  return serializeCsv([...SPECIES_COLUMNS, ...extras], rows);
}

function sameSpeciesKey(row, { date, account, entryType, dexNumber, form }) {
  return String(row.date ?? "").trim() === date
    && String(row.account ?? "").trim() === account
    && String(row.entry_type ?? "").trim() === entryType
    && String(row.dex_number ?? "").trim() === dexNumber
    && String(row.form ?? "").trim().toLowerCase() === form;
}

export function upsertSpeciesRow(rows, input) {
  const today = String(input.today ?? "").trim();
  const account = String(input.account ?? "").trim();
  const entryType = String(input.entryType ?? "").trim();
  const dexNumber = String(input.dexNumber ?? "").trim();
  const form = String(input.form ?? "").trim();
  const formKey = form.toLowerCase();
  const registered = isTrue(input.registered) ? "true" : "false";
  const kept = [];
  let found = false;
  let insertAt = 0;
  let notes = "";
  let canEvolveNow = "false";
  rows.forEach((row) => {
    const matches = sameSpeciesKey(row, {
      date: today,
      account,
      entryType,
      dexNumber,
      form: formKey,
    });
    if (!matches) {
      kept.push(row);
      return;
    }
    if (!found) insertAt = kept.length;
    found = true;
    notes = row.notes ?? "";
    canEvolveNow = row.can_evolve_now ?? "";
  });
  const nextRow = {
    date: today,
    account,
    entry_type: entryType,
    dex_number: dexNumber,
    form,
    registered,
    can_evolve_now: found ? canEvolveNow : "false",
    notes: found ? notes : "",
  };
  if (!found) {
    kept.push(nextRow);
    return kept;
  }
  kept.splice(insertAt, 0, nextRow);
  return kept;
}

export function latestSpeciesRow(rows, key, today) {
  const account = String(key.account ?? "").trim();
  const entryType = String(key.entryType ?? "").trim();
  const dexNumber = String(key.dexNumber ?? "").trim();
  const formKey = String(key.form ?? "").trim().toLowerCase();
  let best = null;
  let bestDate = "";
  rows.forEach((row) => {
    if (String(row.account ?? "").trim() !== account) return;
    if (String(row.entry_type ?? "").trim() !== entryType) return;
    if (String(row.dex_number ?? "").trim() !== dexNumber) return;
    if (String(row.form ?? "").trim().toLowerCase() !== formKey) return;
    const date = String(row.date ?? "").trim();
    if (!date || date > today) return;
    if (!best || date >= bestDate) {
      best = row;
      bestDate = date;
    }
  });
  return best;
}

export function kindChoices(referenceRows) {
  const choices = [];
  const seen = new Set();
  referenceRows.forEach((row) => {
    const id = String(row.entry_type ?? "").trim();
    if (seen.has(id)) return;
    seen.add(id);
    const label = String(row.entry_type_label ?? "").trim() || id;
    choices.push({ id, label });
  });
  return choices;
}

export function regionChoices(referenceRows) {
  const choices = [];
  const seen = new Set();
  referenceRows.forEach((row) => {
    const id = String(row.region ?? "").trim();
    if (seen.has(id)) return;
    seen.add(id);
    const label = String(row.region_label ?? "").trim() || id;
    choices.push({ id, label });
  });
  return choices;
}

export function defaultKindId(kinds) {
  if (kinds.some((kind) => kind.id === "pokemon")) return "pokemon";
  return kinds[0]?.id ?? "";
}

export function accountNames(accountRows) {
  const names = [];
  accountRows.forEach((row) => {
    const name = String(row.account ?? "").trim();
    if (!name || names.includes(name)) return;
    names.push(name);
  });
  return names;
}

function referenceItem(row) {
  return {
    dexNumber: String(row.dex_number ?? "").trim(),
    name: String(row.name ?? ""),
    germanName: String(row.german_name ?? ""),
    form: String(row.form ?? "").trim(),
    entryType: String(row.entry_type ?? "").trim(),
    entryTypeLabel: String(row.entry_type_label ?? "").trim() || String(row.entry_type ?? "").trim(),
    region: String(row.region ?? "").trim(),
    regionLabel: String(row.region_label ?? "").trim(),
    locationRestriction: String(row.location_restriction ?? ""),
    lastEvent: String(row.last_event ?? ""),
  };
}

export function filterSpecies({
  referenceRows,
  speciesRows,
  today,
  account,
  region,
  entryType,
  filter = "missing",
  query = "",
}) {
  const selectedRegion = String(region ?? "").trim();
  const selectedKind = String(entryType ?? "").trim();
  const needle = String(query ?? "").trim().toLowerCase();
  const seen = new Set();
  const items = [];
  referenceRows.forEach((row) => {
    if (!isTrue(row.available)) return;
    const item = referenceItem(row);
    if (item.region !== selectedRegion || item.entryType !== selectedKind) return;
    const id = `${item.dexNumber}\0${item.form.toLowerCase()}`;
    if (seen.has(id)) return;
    seen.add(id);
    if (needle) {
      const matches = item.germanName.toLowerCase().includes(needle)
        || item.name.toLowerCase().includes(needle)
        || item.dexNumber.toLowerCase().includes(needle);
      if (!matches) return;
    }
    const latest = latestSpeciesRow(speciesRows, {
      account,
      entryType: item.entryType,
      dexNumber: item.dexNumber,
      form: item.form,
    }, today);
    const registered = Boolean(latest && isTrue(latest.registered));
    if (filter === "registered" && !registered) return;
    if (filter !== "all" && filter !== "registered" && registered) return;
    items.push({ ...item, registered });
  });
  items.sort((left, right) => {
    const leftDex = Number(left.dexNumber);
    const rightDex = Number(right.dexNumber);
    const leftNumeric = Number.isFinite(leftDex);
    const rightNumeric = Number.isFinite(rightDex);
    if (leftNumeric && rightNumeric && leftDex !== rightDex) return leftDex - rightDex;
    if (left.dexNumber !== right.dexNumber) {
      return left.dexNumber.localeCompare(right.dexNumber, "en");
    }
    return left.form.localeCompare(right.form, "en");
  });
  return items;
}

export function speciesKindRows(referenceRows, dexNumber, form) {
  const dex = String(dexNumber ?? "").trim();
  const formKey = String(form ?? "").trim().toLowerCase();
  const seen = new Set();
  const kinds = [];
  referenceRows.forEach((row) => {
    if (!isTrue(row.available)) return;
    const item = referenceItem(row);
    if (item.dexNumber !== dex || item.form.toLowerCase() !== formKey) return;
    if (seen.has(item.entryType)) return;
    seen.add(item.entryType);
    kinds.push(item);
  });
  return kinds;
}

export function factText(kinds, field) {
  const labeled = [];
  const plain = [];
  kinds.forEach((kind) => {
    const text = String(kind[field] ?? "").trim();
    if (!text) return;
    if (!plain.includes(text)) plain.push(text);
    labeled.push(`${kind.entryTypeLabel}: ${text}`);
  });
  if (plain.length <= 1) return plain[0] ?? "";
  return labeled.join("\n");
}
