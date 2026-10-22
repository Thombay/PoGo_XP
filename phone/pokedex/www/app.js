import { GOOGLE_CLIENT_ID } from "./google-client.js";
import {
  ACCOUNTS_FILE_NAME,
  DRIVE_SCOPE,
  PC_SYNC_MISSING_MESSAGE,
  REFERENCE_FILE_NAME,
  SPECIES_FILE_NAME,
  SYNC_FOLDER_NAME,
  buildRefreshTokenRequest,
  googleAndroidRedirectUrl,
  decodeJsonBytes,
  driveDownloadUrl,
  driveFetch,
  driveFilesUrl,
  driveMediaUploadUrl,
  folderChildrenQuery,
  planSync,
  syncFolderQuery,
  syncResultLine,
} from "./drive-sync.js";
import {
  accountNames,
  defaultKindId,
  factText,
  filterSpecies,
  kindChoices,
  latestSpeciesRow,
  parseCsv,
  parseSpeciesCsv,
  regionChoices,
  serializeSpeciesCsv,
  speciesKindRows,
  spriteUrl,
  todayLocalIso,
  upsertSpeciesRow,
} from "./pokedex-model.js";

const AUTH_KEY = "pogo.auth";
const PENDING_KEY = "pogo.pending";
const MTIME_KEY = "pogo.mtimes";
const UI_KEY = "pogo.ui";

const state = {
  referenceRows: [],
  speciesRows: [],
  accountRows: [],
  ui: {
    account: "",
    region: "",
    kind: "",
    filter: "missing",
    query: "",
    controlsOpen: true,
    screen: "list",
    detail: null,
  },
  savedUi: null,
  listScrollY: 0,
};

const dom = {
  gate: document.querySelector("#gate"),
  signIn: document.querySelector("#sign-in"),
  gateError: document.querySelector("#gate-error"),
  shell: document.querySelector("#shell"),
  sync: document.querySelector("#sync"),
  status: document.querySelector("#status"),
  controls: document.querySelector("#controls"),
  controlPanel: document.querySelector("#control-panel"),
  summary: document.querySelector("#summary"),
  account: document.querySelector("#account"),
  region: document.querySelector("#region"),
  search: document.querySelector("#search"),
  clear: document.querySelector("#clear"),
  kinds: document.querySelector("#kinds"),
  missing: document.querySelector("#missing"),
  list: document.querySelector("#list"),
  detail: document.querySelector("#detail"),
  back: document.querySelector("#back"),
  detailGerman: document.querySelector("#detail-german"),
  detailEnglish: document.querySelector("#detail-english"),
  detailKinds: document.querySelector("#detail-kinds"),
  detailLocation: document.querySelector("#detail-location"),
  detailEvent: document.querySelector("#detail-event"),
};

let plugins = null;
let lifecycleBound = false;
let ignoreScroll = 0;
let syncTail = Promise.resolve();
let syncing = false;
let refreshAttempted = false;

function clientId() {
  return String(GOOGLE_CLIENT_ID ?? "").trim();
}

function oneLine(value) {
  return String(value || "Sync failed.").replace(/\s+/g, " ").trim();
}

function nativePlugins() {
  if (plugins) return plugins;
  const cap = globalThis.Capacitor;
  if (!cap || typeof cap.isNativePlatform !== "function" || !cap.isNativePlatform()) return null;
  if (typeof cap.registerPlugin !== "function") return null;
  plugins = {
    preferences: cap.registerPlugin("Preferences"),
    filesystem: cap.registerPlugin("Filesystem"),
    app: cap.registerPlugin("App"),
    oauth: cap.registerPlugin("GenericOAuth2"),
  };
  return plugins;
}

async function prefsGet(key) {
  const native = nativePlugins();
  if (native) {
    const result = await native.preferences.get({ key });
    return result?.value ?? null;
  }
  return localStorage.getItem(key);
}

async function prefsSet(key, value) {
  const native = nativePlugins();
  if (native) {
    await native.preferences.set({ key, value });
    return;
  }
  localStorage.setItem(key, value);
}

async function prefsRemove(key) {
  const native = nativePlugins();
  if (native) {
    await native.preferences.remove({ key });
    return;
  }
  localStorage.removeItem(key);
}

function bytesToBase64(bytes) {
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return btoa(binary);
}

function base64ToBytes(value) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

function textToBytes(text) {
  return new TextEncoder().encode(text);
}

function bytesToText(bytes) {
  return new TextDecoder("utf-8").decode(bytes);
}

async function readLocalBytes(name) {
  const native = nativePlugins();
  if (native) {
    try {
      const result = await native.filesystem.readFile({ path: name, directory: "DATA" });
      return base64ToBytes(result.data);
    } catch {
      return null;
    }
  }
  const stored = localStorage.getItem(`pogo.file.${name}`);
  if (stored == null) return null;
  return textToBytes(stored);
}

async function writeLocalBytes(name, bytes) {
  const native = nativePlugins();
  if (native) {
    await native.filesystem.writeFile({
      path: name,
      directory: "DATA",
      data: bytesToBase64(bytes),
    });
    return;
  }
  localStorage.setItem(`pogo.file.${name}`, bytesToText(bytes));
}

async function readLocalText(name) {
  const bytes = await readLocalBytes(name);
  if (!bytes) return "";
  return bytesToText(bytes);
}

async function loadAuth() {
  const raw = await prefsGet(AUTH_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    if (!parsed.accessToken && !parsed.refreshToken) return null;
    return parsed;
  } catch {
    return null;
  }
}

async function saveAuth(auth) {
  await prefsSet(AUTH_KEY, JSON.stringify(auth));
}

async function clearAuth() {
  await prefsRemove(AUTH_KEY);
}

async function loadPending() {
  return (await prefsGet(PENDING_KEY)) === "1";
}

async function savePending(pending) {
  await prefsSet(PENDING_KEY, pending ? "1" : "0");
}

async function loadMtimes() {
  const raw = await prefsGet(MTIME_KEY);
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

async function saveMtimes(mtimes) {
  await prefsSet(MTIME_KEY, JSON.stringify(mtimes));
}

async function loadSavedUi() {
  const raw = await prefsGet(UI_KEY);
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

async function saveUi() {
  const { account, region, kind, filter } = state.ui;
  await prefsSet(UI_KEY, JSON.stringify({ account, region, kind, filter }));
}

function showGate(message = "") {
  dom.shell.hidden = true;
  dom.gate.hidden = false;
  const missingClient = !clientId();
  dom.signIn.textContent = missingClient
    ? "Sign in with Google — client id is not set"
    : "Sign in with Google";
  dom.signIn.setAttribute("aria-disabled", missingClient ? "true" : "false");
  if (message) {
    dom.gateError.hidden = false;
    dom.gateError.textContent = message;
  } else {
    dom.gateError.hidden = true;
    dom.gateError.textContent = "";
  }
}

function showShell() {
  dom.gate.hidden = true;
  dom.shell.hidden = false;
}

function setStatus(text) {
  dom.status.textContent = text || "";
}

function googleSignInOptions(id) {
  const redirectUrl = googleAndroidRedirectUrl(id);
  const android = {
    appId: id,
    responseType: "code",
    redirectUrl,
    pkceEnabled: true,
  };
  return {
    appId: id,
    authorizationBaseUrl: "https://accounts.google.com/o/oauth2/v2/auth",
    accessTokenEndpoint: "https://oauth2.googleapis.com/token",
    scope: DRIVE_SCOPE,
    responseType: "code",
    redirectUrl,
    pkceEnabled: true,
    logsEnabled: false,
    additionalParameters: {
      access_type: "offline",
      prompt: "consent",
    },
    android,
  };
}

function tokensFromOauth(result) {
  const nested = result && typeof result.access_token_response === "object" ? result.access_token_response : {};
  const accessToken = nested.access_token || result?.access_token || "";
  const refreshToken = nested.refresh_token || result?.refresh_token || "";
  const expiresIn = Number(nested.expires_in || result?.expires_in || 3600);
  return {
    accessToken,
    refreshToken,
    expiresAt: Date.now() + (Number.isFinite(expiresIn) ? expiresIn : 3600) * 1000,
  };
}

function cancelled(error) {
  const text = String(error?.message || error || "");
  return /cancel/i.test(text) || text.includes("USER_CANCELLED");
}

async function refreshAccessToken(auth) {
  const request = buildRefreshTokenRequest({
    clientId: clientId(),
    refreshToken: auth.refreshToken,
  });
  let response;
  try {
    response = await fetch(request.url, {
      method: request.method,
      headers: request.headers,
      body: request.body,
    });
  } catch (error) {
    const wrapped = new Error(oneLine(error.message || "Could not reach Google."));
    wrapped.keepLogin = true;
    throw wrapped;
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.access_token) {
    const wrapped = new Error(oneLine(payload.error_description || payload.error || "Google login expired."));
    wrapped.invalidGrant = response.status === 400 || response.status === 401 || payload.error === "invalid_grant";
    throw wrapped;
  }
  return {
    accessToken: payload.access_token,
    refreshToken: payload.refresh_token || auth.refreshToken,
    expiresAt: Date.now() + Number(payload.expires_in || 3600) * 1000,
  };
}

async function ensureAccessToken() {
  const auth = await loadAuth();
  if (!auth) return null;
  if (auth.accessToken && auth.expiresAt > Date.now() + 60_000) return auth.accessToken;
  if (!clientId()) {
    const error = new Error("The client id is not set.");
    error.keepLogin = true;
    throw error;
  }
  if (!auth.refreshToken) {
    await clearAuth();
    return null;
  }
  try {
    const next = await refreshAccessToken(auth);
    await saveAuth(next);
    return next.accessToken;
  } catch (error) {
    if (!error.keepLogin) await clearAuth();
    if (error.keepLogin) throw error;
    return null;
  }
}

async function driveCall(url, options) {
  const result = await driveFetch(url, options);
  if (result.status === 401) {
    const error = new Error("Google login expired.");
    error.status = 401;
    throw error;
  }
  if (!result.ok) {
    let message = `Drive error ${result.status}`;
    try {
      const body = decodeJsonBytes(result.bytes);
      if (body?.error?.message) message = body.error.message;
    } catch {
      /* The body was not JSON. */
    }
    const error = new Error(oneLine(message));
    error.status = result.status;
    throw error;
  }
  return result;
}

async function findSyncFiles(accessToken) {
  const folderResult = await driveCall(
    driveFilesUrl(syncFolderQuery(), "files(id,name)"),
    { accessToken },
  );
  const folders = decodeJsonBytes(folderResult.bytes)?.files || [];
  const folder = folders.find((file) => file.name === SYNC_FOLDER_NAME);
  if (!folder?.id) return null;
  const childResult = await driveCall(
    driveFilesUrl(folderChildrenQuery(folder.id), "files(id,name,modifiedTime)"),
    { accessToken },
  );
  const files = decodeJsonBytes(childResult.bytes)?.files || [];
  const byName = new Map(files.map((file) => [file.name, file]));
  const species = byName.get(SPECIES_FILE_NAME);
  const reference = byName.get(REFERENCE_FILE_NAME);
  const accounts = byName.get(ACCOUNTS_FILE_NAME);
  if (!species?.id || !reference?.id || !accounts?.id) return null;
  return { species, reference, accounts };
}

async function uploadSpecies(accessToken, fileId, bytes) {
  const result = await driveCall(driveMediaUploadUrl(fileId), {
    accessToken,
    method: "PATCH",
    contentType: "text/csv",
    body: bytes,
  });
  return decodeJsonBytes(result.bytes) || {};
}

async function downloadFile(accessToken, fileId) {
  const result = await driveCall(driveDownloadUrl(fileId), { accessToken });
  return result.bytes;
}

async function syncBody(accessToken) {
  const files = await findSyncFiles(accessToken);
  if (!files) return PC_SYNC_MISSING_MESSAGE;
  const pendingAtStart = await loadPending();
  const mtimes = await loadMtimes();
  let uploadSucceeded = null;
  let speciesLocalModified = mtimes[SPECIES_FILE_NAME] || null;
  let speciesRemoteModified = files.species.modifiedTime || null;
  if (pendingAtStart) {
    const localBytes = await readLocalBytes(SPECIES_FILE_NAME);
    if (!localBytes) {
      uploadSucceeded = false;
    } else {
      try {
        const uploaded = await uploadSpecies(accessToken, files.species.id, localBytes);
        uploadSucceeded = true;
        const stamped = uploaded.modifiedTime || new Date().toISOString();
        speciesLocalModified = stamped;
        speciesRemoteModified = stamped;
        mtimes[SPECIES_FILE_NAME] = stamped;
      } catch {
        uploadSucceeded = false;
      }
    }
  }
  const plan = planSync({
    pending: pendingAtStart,
    uploadSucceeded: pendingAtStart ? uploadSucceeded : null,
    speciesLocalModified,
    speciesRemoteModified,
    referenceLocalModified: mtimes[REFERENCE_FILE_NAME] || null,
    referenceRemoteModified: files.reference.modifiedTime || null,
    accountsLocalModified: mtimes[ACCOUNTS_FILE_NAME] || null,
    accountsRemoteModified: files.accounts.modifiedTime || null,
  });
  if (plan.clearPending) await savePending(false);
  if (plan.pendingKept) {
    await savePending(true);
    await saveMtimes(mtimes);
    return syncResultLine({ pendingKept: true });
  }
  const errors = [];
  if (plan.acceptRemoteSpecies) {
    try {
      await writeLocalBytes(SPECIES_FILE_NAME, await downloadFile(accessToken, files.species.id));
      mtimes[SPECIES_FILE_NAME] = files.species.modifiedTime;
    } catch (error) {
      errors.push(error.message);
    }
  }
  if (plan.downloadReference) {
    try {
      await writeLocalBytes(REFERENCE_FILE_NAME, await downloadFile(accessToken, files.reference.id));
      mtimes[REFERENCE_FILE_NAME] = files.reference.modifiedTime;
    } catch (error) {
      errors.push(error.message);
    }
  }
  if (plan.downloadAccounts) {
    try {
      await writeLocalBytes(ACCOUNTS_FILE_NAME, await downloadFile(accessToken, files.accounts.id));
      mtimes[ACCOUNTS_FILE_NAME] = files.accounts.modifiedTime;
    } catch (error) {
      errors.push(error.message);
    }
  }
  await saveMtimes(mtimes);
  return syncResultLine({ error: errors[0] || "" });
}

async function reloadLocal() {
  state.speciesRows = parseSpeciesCsv(await readLocalText(SPECIES_FILE_NAME));
  state.referenceRows = parseCsv(await readLocalText(REFERENCE_FILE_NAME));
  state.accountRows = parseCsv(await readLocalText(ACCOUNTS_FILE_NAME));
  applySelections();
}

function applySelections() {
  const saved = state.savedUi || {};
  const accounts = accountNames(state.accountRows);
  const regions = regionChoices(state.referenceRows);
  const kinds = kindChoices(state.referenceRows);
  state.ui.account = saved.account && accounts.includes(saved.account) ? saved.account : (accounts[0] || "");
  state.ui.region = saved.region && regions.some((region) => region.id === saved.region)
    ? saved.region
    : (regions[0]?.id || "");
  state.ui.kind = saved.kind && kinds.some((kind) => kind.id === saved.kind)
    ? saved.kind
    : defaultKindId(kinds);
  state.ui.filter = ["missing", "all", "registered"].includes(saved.filter) ? saved.filter : "missing";
}

function rememberSelections() {
  state.savedUi = {
    account: state.ui.account,
    region: state.ui.region,
    kind: state.ui.kind,
    filter: state.ui.filter,
  };
  saveUi().catch(() => {});
}

async function syncOnce() {
  syncing = true;
  dom.sync.disabled = true;
  setStatus("Syncing");
  let line = "synced";
  try {
    refreshAttempted = false;
    let token = await ensureAccessToken();
    if (!(await loadAuth())) {
      showGate();
      return;
    }
    if (!token) {
      line = "Could not reach Google.";
    } else {
      try {
        line = await syncBody(token);
      } catch (error) {
        if (error.status === 401 && !refreshAttempted) {
          refreshAttempted = true;
          await clearAuthTokenOnly();
          token = await ensureAccessToken();
          if (!(await loadAuth())) {
            showGate();
            return;
          }
          if (!token) {
            line = oneLine(error.message);
          } else {
            line = await syncBody(token);
          }
        } else {
          line = syncResultLine({ error: oneLine(error.message) });
        }
      }
    }
  } catch (error) {
    if (!(await loadAuth())) {
      showGate();
      return;
    }
    line = syncResultLine({ error: oneLine(error.message) });
  } finally {
    syncing = false;
    dom.sync.disabled = false;
  }
  if (dom.shell.hidden) return;
  setStatus(line);
  await reloadLocal();
  render();
}

async function clearAuthTokenOnly() {
  const auth = await loadAuth();
  if (!auth) return;
  auth.accessToken = "";
  auth.expiresAt = 0;
  await saveAuth(auth);
}

function requestSync() {
  syncTail = syncTail.then(() => syncOnce()).catch((error) => {
    setStatus(syncResultLine({ error: oneLine(error.message) }));
  });
  return syncTail;
}

function listItems(filter = state.ui.filter, query = state.ui.query) {
  return filterSpecies({
    referenceRows: state.referenceRows,
    speciesRows: state.speciesRows,
    today: todayLocalIso(),
    account: state.ui.account,
    region: state.ui.region,
    entryType: state.ui.kind,
    filter,
    query,
  });
}

function missingTotal() {
  return listItems("missing", "").length;
}

function regionLabel(id) {
  return regionChoices(state.referenceRows).find((region) => region.id === id)?.label || id || "Region";
}

function kindLabel(id) {
  return kindChoices(state.referenceRows).find((kind) => kind.id === id)?.label || id || "Kind";
}

function summaryLine() {
  return `${state.ui.account || "Account"} · ${regionLabel(state.ui.region)} · ${kindLabel(state.ui.kind)} · ${missingTotal()} missing`;
}

function secondLine(item) {
  const parts = [item.name, `#${item.dexNumber}`];
  if (item.form) parts.push(item.form);
  return parts.filter(Boolean).join(" · ");
}

function fillSelect(select, options, selected) {
  select.replaceChildren();
  options.forEach((option) => {
    const node = document.createElement("option");
    node.value = option.id;
    node.textContent = option.label;
    select.append(node);
  });
  select.value = selected;
}

function setControlsOpen(open) {
  state.ui.controlsOpen = open;
  dom.controlPanel.hidden = !open;
  dom.summary.hidden = open;
  if (open) ensureChipVisible();
}

function ensureChipVisible() {
  const selected = dom.kinds.querySelector("[aria-pressed='true']");
  if (!selected) return;
  const left = selected.offsetLeft;
  const right = left + selected.offsetWidth;
  if (left < dom.kinds.scrollLeft) dom.kinds.scrollLeft = left;
  else if (right > dom.kinds.scrollLeft + dom.kinds.clientWidth) {
    dom.kinds.scrollLeft = right - dom.kinds.clientWidth;
  }
}

function renderControls() {
  const accounts = accountNames(state.accountRows).map((account) => ({ id: account, label: account }));
  fillSelect(dom.account, accounts, state.ui.account);
  fillSelect(dom.region, regionChoices(state.referenceRows), state.ui.region);
  dom.kinds.replaceChildren();
  kindChoices(state.referenceRows).forEach((kind) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "kind-chip";
    button.textContent = kind.label;
    button.setAttribute("aria-pressed", kind.id === state.ui.kind ? "true" : "false");
    button.addEventListener("click", () => {
      state.ui.kind = kind.id;
      rememberSelections();
      renderControls();
      renderList();
    });
    dom.kinds.append(button);
  });
  document.querySelectorAll("#controls [data-filter]").forEach((button) => {
    button.setAttribute("aria-pressed", button.dataset.filter === state.ui.filter ? "true" : "false");
  });
  dom.summary.textContent = summaryLine();
  setControlsOpen(state.ui.controlsOpen);
  ensureChipVisible();
}

function makeSwitch(item, entryType) {
  const input = document.createElement("input");
  input.type = "checkbox";
  input.className = "reg-switch";
  input.setAttribute("role", "switch");
  input.checked = item.registered;
  input.setAttribute("aria-label", `${item.germanName || item.name} ${kindLabel(entryType)} registered`);
  input.dataset.dex = item.dexNumber;
  input.dataset.form = item.form;
  input.dataset.entryType = entryType;
  input.addEventListener("change", () => {
    toggleRegistration({
      dexNumber: input.dataset.dex,
      form: input.dataset.form,
      entryType: input.dataset.entryType,
      registered: input.checked,
    }).catch((error) => setStatus(oneLine(error.message)));
  });
  return input;
}

function renderList() {
  const items = listItems();
  dom.missing.textContent = `${missingTotal()} missing`;
  dom.summary.textContent = summaryLine();
  dom.list.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "None";
    dom.list.append(empty);
    return;
  }
  items.forEach((item) => {
    const row = document.createElement("article");
    row.className = "species";
    const image = document.createElement("img");
    image.className = "sprite";
    image.alt = "";
    image.width = 40;
    image.height = 40;
    image.decoding = "async";
    image.loading = "lazy";
    image.src = spriteUrl(item.dexNumber);
    image.addEventListener("error", () => {
      image.classList.add("failed");
    });
    const name = document.createElement("button");
    name.type = "button";
    name.className = "name";
    const german = document.createElement("span");
    german.className = "line line-german";
    german.textContent = item.germanName || item.name || `#${item.dexNumber}`;
    const english = document.createElement("span");
    english.className = "line";
    english.textContent = secondLine(item);
    name.append(german, english);
    name.addEventListener("click", () => openDetail(item));
    row.append(image, name, makeSwitch(item, state.ui.kind));
    dom.list.append(row);
  });
}

function registeredFor(dexNumber, form, entryType) {
  const latest = latestSpeciesRow(state.speciesRows, {
    account: state.ui.account,
    entryType,
    dexNumber,
    form,
  }, todayLocalIso());
  return Boolean(latest && String(latest.registered).trim().toLowerCase() === "true");
}

function renderDetail() {
  const detail = state.ui.detail;
  if (!detail) return;
  const kinds = speciesKindRows(state.referenceRows, detail.dexNumber, detail.form);
  dom.detailGerman.textContent = detail.germanName || detail.name || `#${detail.dexNumber}`;
  const parts = [detail.name, `#${detail.dexNumber}`];
  if (detail.form) parts.push(detail.form);
  dom.detailEnglish.textContent = parts.filter(Boolean).join(" · ");
  dom.detailKinds.replaceChildren();
  kinds.forEach((kind) => {
    const line = document.createElement("div");
    line.className = "kind-line";
    const label = document.createElement("span");
    label.textContent = kind.entryTypeLabel;
    const registered = registeredFor(detail.dexNumber, kind.form || detail.form, kind.entryType);
    line.append(label, makeSwitch({
      ...kind,
      germanName: detail.germanName,
      name: detail.name,
      registered,
    }, kind.entryType));
    dom.detailKinds.append(line);
  });
  dom.detailLocation.textContent = factText(kinds, "locationRestriction");
  dom.detailEvent.textContent = factText(kinds, "lastEvent");
}

function render() {
  const detailOpen = state.ui.screen === "detail";
  dom.controls.hidden = detailOpen;
  dom.list.hidden = detailOpen;
  dom.detail.hidden = !detailOpen;
  if (detailOpen) {
    renderDetail();
    return;
  }
  renderControls();
  renderList();
}

function openDetail(item) {
  state.listScrollY = window.scrollY;
  state.ui.screen = "detail";
  state.ui.detail = {
    dexNumber: item.dexNumber,
    form: item.form,
    name: item.name,
    germanName: item.germanName,
  };
  render();
  ignoreScroll = 3;
  window.scrollTo(0, 0);
}

function closeDetail() {
  state.ui.screen = "list";
  state.ui.detail = null;
  render();
  ignoreScroll = 3;
  window.scrollTo(0, state.listScrollY);
}

async function toggleRegistration(target) {
  const previous = state.speciesRows;
  state.speciesRows = upsertSpeciesRow(state.speciesRows, {
    today: todayLocalIso(),
    account: state.ui.account,
    entryType: target.entryType,
    dexNumber: target.dexNumber,
    form: target.form,
    registered: target.registered,
  });
  try {
    await writeLocalBytes(SPECIES_FILE_NAME, textToBytes(serializeSpeciesCsv(state.speciesRows)));
    const mtimes = await loadMtimes();
    mtimes[SPECIES_FILE_NAME] = new Date().toISOString();
    await saveMtimes(mtimes);
    await savePending(true);
  } catch (error) {
    state.speciesRows = previous;
    setStatus(oneLine(error.message));
  }
  if (state.ui.screen === "detail") renderDetail();
  else renderList();
}

async function onSignIn() {
  if (!clientId()) return;
  const native = nativePlugins();
  if (!native) {
    showGate("Sign in with Google runs in the Android app.");
    return;
  }
  try {
    const result = await native.oauth.authenticate(googleSignInOptions(clientId()));
    const tokens = tokensFromOauth(result);
    if (!tokens.accessToken) throw new Error("Google did not return an access token.");
    await saveAuth(tokens);
    showShell();
    bindLifecycle();
    await requestSync();
  } catch (error) {
    if (cancelled(error)) return;
    showGate(oneLine(error.message || "Sign in failed."));
  }
}

function bindLifecycle() {
  if (lifecycleBound) return;
  lifecycleBound = true;
  const syncIfPending = () => {
    loadPending().then((pending) => {
      if (pending) requestSync();
    }).catch(() => {});
  };
  const native = nativePlugins();
  if (native) {
    try {
      Promise.resolve(native.app.addListener("appStateChange", () => {
        syncIfPending();
      })).catch(() => {});
    } catch {
      /* The web preview has no native app plugin. */
    }
    return;
  }
  document.addEventListener("visibilitychange", syncIfPending);
}

function syncKeyboardInset() {
  const viewport = window.visualViewport;
  let inset = 0;
  if (viewport) inset = Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop);
  document.documentElement.style.setProperty("--keyboard-inset", `${inset}px`);
  if (inset > 0 && document.activeElement === dom.search) {
    dom.search.scrollIntoView({ block: "nearest" });
  }
}

function bindUi() {
  dom.signIn.addEventListener("click", () => {
    onSignIn().catch((error) => showGate(oneLine(error.message)));
  });
  dom.sync.addEventListener("click", () => {
    if (!syncing) requestSync();
  });
  dom.account.addEventListener("change", () => {
    state.ui.account = dom.account.value;
    rememberSelections();
    renderList();
  });
  dom.region.addEventListener("change", () => {
    state.ui.region = dom.region.value;
    rememberSelections();
    renderList();
  });
  dom.search.addEventListener("input", () => {
    state.ui.query = dom.search.value;
    renderList();
  });
  dom.clear.addEventListener("click", () => {
    state.ui.query = "";
    dom.search.value = "";
    renderList();
    dom.search.focus();
  });
  document.querySelectorAll("#controls [data-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.ui.filter = button.dataset.filter;
      rememberSelections();
      renderControls();
      renderList();
    });
  });
  dom.summary.addEventListener("click", () => {
    ignoreScroll = 2;
    setControlsOpen(true);
  });
  dom.back.addEventListener("click", closeDetail);
  window.addEventListener("scroll", () => {
    if (ignoreScroll > 0) {
      ignoreScroll -= 1;
      return;
    }
    if (state.ui.screen !== "list" || !state.ui.controlsOpen) return;
    if (document.activeElement === dom.search) return;
    if (window.scrollY > 16) setControlsOpen(false);
  }, { passive: true });
  window.visualViewport?.addEventListener("resize", syncKeyboardInset);
  window.visualViewport?.addEventListener("scroll", syncKeyboardInset);
}

async function boot() {
  bindUi();
  state.savedUi = await loadSavedUi();
  const auth = await loadAuth();
  if (!auth) {
    showGate();
    return;
  }
  showShell();
  bindLifecycle();
  let token = null;
  try {
    token = await ensureAccessToken();
  } catch (error) {
    setStatus(oneLine(error.message));
  }
  if (!(await loadAuth())) {
    showGate();
    return;
  }
  if (!token) {
    await reloadLocal();
    render();
    return;
  }
  await requestSync();
}

boot().catch((error) => {
  showGate(oneLine(error.message || "The app could not start."));
});
