export const SYNC_FOLDER_NAME = "PoGo Sync";
export const SPECIES_FILE_NAME = "pokedex_species_entries.csv";
export const REFERENCE_FILE_NAME = "pokedex_atlas_reference.csv";
export const ACCOUNTS_FILE_NAME = "pokedex_accounts.csv";
export const DRIVE_SCOPE = "https://www.googleapis.com/auth/drive";
export const PC_SYNC_MISSING_MESSAGE = "The PC command has not been run yet.";
export const TOKEN_URL = "https://oauth2.googleapis.com/token";

export function googleAndroidRedirectUrl(clientId) {
  const prefix = String(clientId || "")
    .trim()
    .replace(/\.apps\.googleusercontent\.com$/i, "");
  if (!prefix || prefix.includes("/")) return "";
  return `com.googleusercontent.apps.${prefix}:/oauth2redirect`;
}

export function isRemoteNewer(localModified, remoteModified) {
  if (!remoteModified) return false;
  const remote = Date.parse(remoteModified);
  if (Number.isNaN(remote)) return false;
  if (!localModified) return true;
  const local = Date.parse(localModified);
  if (Number.isNaN(local)) return true;
  return remote > local;
}

export function planSync({
  pending = false,
  uploadSucceeded = null,
  speciesLocalModified = null,
  speciesRemoteModified = null,
  referenceLocalModified = null,
  referenceRemoteModified = null,
  accountsLocalModified = null,
  accountsRemoteModified = null,
} = {}) {
  const isPending = Boolean(pending);
  const uploadFailed = isPending && uploadSucceeded !== true;
  const settled = !uploadFailed;
  return {
    uploadSpecies: isPending && uploadSucceeded == null,
    acceptRemoteSpecies: settled && isRemoteNewer(speciesLocalModified, speciesRemoteModified),
    downloadReference: settled && isRemoteNewer(referenceLocalModified, referenceRemoteModified),
    downloadAccounts: settled && isRemoteNewer(accountsLocalModified, accountsRemoteModified),
    clearPending: isPending && uploadSucceeded === true,
    pendingKept: uploadFailed,
  };
}

export function speciesBytesAfterSync(input) {
  const plan = planSync(input);
  if (plan.acceptRemoteSpecies) {
    return { bytes: input.remoteBytes, replaced: true, pending: false };
  }
  return {
    bytes: input.localBytes,
    replaced: false,
    pending: plan.pendingKept,
  };
}

export function syncResultLine({ pendingKept = false, error = "" } = {}) {
  if (pendingKept) return "pending kept";
  const text = String(error || "").replace(/\s+/g, " ").trim();
  if (text) return text;
  return "synced";
}

export function buildRefreshTokenRequest({ clientId, refreshToken }) {
  const body = new URLSearchParams({
    client_id: clientId,
    grant_type: "refresh_token",
    refresh_token: refreshToken,
  });
  return {
    url: TOKEN_URL,
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  };
}

export function syncFolderQuery() {
  return "name = 'PoGo Sync' and mimeType = 'application/vnd.google-apps.folder' and trashed = false";
}

export function folderChildrenQuery(folderId) {
  const escaped = String(folderId ?? "").replaceAll("\\", "\\\\").replaceAll("'", "\\'");
  return `'${escaped}' in parents and trashed = false`;
}

export function driveFilesUrl(query, fields) {
  const url = new URL("https://www.googleapis.com/drive/v3/files");
  url.searchParams.set("q", query);
  url.searchParams.set("fields", fields);
  url.searchParams.set("pageSize", "100");
  url.searchParams.set("spaces", "drive");
  return url.toString();
}

export function driveDownloadUrl(fileId) {
  const url = new URL(`https://www.googleapis.com/drive/v3/files/${encodeURIComponent(fileId)}`);
  url.searchParams.set("alt", "media");
  return url.toString();
}

export function driveMediaUploadUrl(fileId) {
  const url = new URL(`https://www.googleapis.com/upload/drive/v3/files/${encodeURIComponent(fileId)}`);
  url.searchParams.set("uploadType", "media");
  url.searchParams.set("fields", "id,modifiedTime");
  return url.toString();
}

export function decodeJsonBytes(bytes) {
  const text = new TextDecoder("utf-8").decode(bytes);
  if (!text) return null;
  return JSON.parse(text);
}

export async function driveFetch(url, options = {}) {
  const fetchImpl = options.fetchImpl ?? globalThis.fetch;
  const headers = new Headers(options.headers || {});
  if (options.accessToken) headers.set("Authorization", `Bearer ${options.accessToken}`);
  if (options.contentType) headers.set("Content-Type", options.contentType);
  const response = await fetchImpl(url, {
    method: options.method || "GET",
    headers,
    body: options.body,
    signal: options.signal ?? AbortSignal.timeout(30000),
  });
  const bytes = new Uint8Array(await response.arrayBuffer());
  return { ok: response.ok, status: response.status, bytes };
}
