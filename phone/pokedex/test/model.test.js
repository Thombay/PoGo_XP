import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  buildRefreshTokenRequest,
  googleAndroidRedirectUrl,
  planSync,
  speciesBytesAfterSync,
  syncResultLine,
} from "../www/drive-sync.js";
import {
  ALL_REGIONS,
  accountNames,
  defaultKindId,
  filterSpecies,
  kindChoices,
  latestSpeciesRow,
  parseSpeciesCsv,
  regionChoices,
  unavailableKindRows,
  upsertSpeciesRow,
} from "../www/pokedex-model.js";

const today = "2026-10-22";

function speciesRow(overrides) {
  return {
    date: today,
    account: "Main",
    entry_type: "pokemon",
    dex_number: "1",
    form: "",
    registered: "false",
    can_evolve_now: "false",
    notes: "",
    ...overrides,
  };
}

function referenceRow(overrides) {
  return {
    dex_number: "1",
    name: "Bulbasaur",
    german_name: "Bisasam",
    region: "kanto",
    region_label: "Kanto",
    form: "",
    entry_type: "pokemon",
    entry_type_label: "Pokémon",
    available: "true",
    location_restriction: "",
    last_event: "",
    ...overrides,
  };
}

describe("species csv", () => {
  it("parses a species file with a form column and a BOM", () => {
    const csv = "\uFEFFdate,account,entry_type,dex_number,form,registered,can_evolve_now,notes\r\n"
      + "2026-10-22,Main,pokemon,25,Alola,false,false,\"line, \"\"quoted\"\"\"\r\n";
    const rows = parseSpeciesCsv(csv);
    assert.equal(rows.length, 1);
    assert.equal(rows[0].form, "Alola");
    assert.equal(rows[0].dex_number, "25");
    assert.equal(rows[0].entry_type, "pokemon");
    assert.equal(rows[0].notes, "line, \"quoted\"");
  });

  it("upserts one row without rewriting another dex", () => {
    const other = speciesRow({
      dex_number: "1",
      registered: "false",
      can_evolve_now: "true",
      notes: "leave-me",
    });
    const rows = [other];
    const next = upsertSpeciesRow(rows, {
      today,
      account: "Main",
      entryType: "pokemon",
      dexNumber: "25",
      form: "",
      registered: true,
    });
    assert.equal(next[0], other);
    assert.equal(next[0].dex_number, "1");
    assert.equal(next[0].notes, "leave-me");
    assert.equal(next[0].registered, "false");
    assert.equal(next[1].dex_number, "25");
    assert.equal(next[1].registered, "true");
    assert.equal(next[1].notes, "");
    assert.equal(next[1].can_evolve_now, "false");
  });

  it("replaces registered on a same-day same-key upsert and keeps notes", () => {
    const rows = [speciesRow({
      dex_number: "4",
      form: "alola",
      registered: "false",
      can_evolve_now: "true",
      notes: "keep me",
    })];
    const next = upsertSpeciesRow(rows, {
      today,
      account: "Main",
      entryType: "pokemon",
      dexNumber: "4",
      form: " Alola ",
      registered: true,
    });
    assert.equal(next.length, 1);
    assert.equal(next[0].registered, "true");
    assert.equal(next[0].form, "Alola");
    assert.equal(next[0].notes, "keep me");
    assert.equal(next[0].can_evolve_now, "true");
    assert.equal(next[0].date, today);
  });

  it("uses the newest date on or before today and ignores a newer date", () => {
    const rows = [
      speciesRow({ date: "2026-10-25", registered: "false", notes: "future" }),
      speciesRow({ date: "2026-10-22", registered: "true", notes: "today" }),
      speciesRow({ date: "2026-10-21", registered: "false", notes: "older" }),
      speciesRow({ date: "2026-10-23", account: "Other", registered: "false" }),
    ];
    const latest = latestSpeciesRow(rows, {
      account: "Main",
      entryType: "pokemon",
      dexNumber: "1",
      form: "",
    }, "2026-10-24");
    assert.equal(latest.date, "2026-10-22");
    assert.equal(latest.registered, "true");
    assert.equal(latest.notes, "today");
  });
});

describe("hunting list", () => {
  const referenceRows = [
    referenceRow({ dex_number: "10", name: "Caterpie", german_name: "Raupy" }),
    referenceRow({ dex_number: "2", name: "Ivysaur", german_name: "Bisaknosp" }),
    referenceRow({
      dex_number: "151",
      name: "Mew",
      german_name: "Mew",
      available: "false",
      location_restriction: "special",
    }),
    referenceRow({
      dex_number: "2",
      name: "Ivysaur",
      german_name: "Bisaknosp",
      form: "Party",
      entry_type: "shiny",
      entry_type_label: "Shiny",
    }),
  ];
  const speciesRows = [
    speciesRow({ dex_number: "2", registered: "true" }),
  ];

  it("hides registered species from the missing filter", () => {
    const missing = filterSpecies({
      referenceRows,
      speciesRows,
      today,
      account: "Main",
      region: "kanto",
      entryType: "pokemon",
      filter: "missing",
      query: "",
    });
    assert.deepEqual(missing.map((row) => row.dexNumber), ["10"]);
  });

  it("excludes reference rows that are not available", () => {
    const all = filterSpecies({
      referenceRows,
      speciesRows,
      today,
      account: "Main",
      region: "kanto",
      entryType: "pokemon",
      filter: "all",
      query: "",
    });
    assert.deepEqual(all.map((row) => row.dexNumber), ["2", "10"]);
    assert.equal(all.some((row) => row.name === "Mew"), false);
  });

  it("lists only not-available rows in the unavailable filter", () => {
    const unavailable = filterSpecies({
      referenceRows,
      speciesRows,
      today,
      account: "Main",
      region: "kanto",
      entryType: "pokemon",
      filter: "unavailable",
      query: "",
    });
    assert.deepEqual(unavailable.map((row) => row.dexNumber), ["151"]);
    assert.equal(unavailable[0].available, false);
    assert.equal(unavailable[0].registered, false);
  });

  it("spans every region when all regions is selected", () => {
    const rows = [
      ...referenceRows,
      referenceRow({ dex_number: "152", name: "Chikorita", german_name: "Endivie", region: "johto", region_label: "Johto" }),
    ];
    const scoped = (region) => filterSpecies({
      referenceRows: rows,
      speciesRows,
      today,
      account: "Main",
      region,
      entryType: "pokemon",
      filter: "all",
      query: "",
    }).map((row) => row.dexNumber);
    assert.deepEqual(scoped("kanto"), ["2", "10"]);
    assert.deepEqual(scoped(ALL_REGIONS), ["2", "10", "152"]);
  });

  it("names the kinds a species does not have in GO", () => {
    const rows = [
      referenceRow({ dex_number: "7", entry_type: "pokemon" }),
      referenceRow({ dex_number: "7", entry_type: "shiny", entry_type_label: "Shiny", form: "Party" }),
      referenceRow({ dex_number: "7", entry_type: "shadow", entry_type_label: "Shadow", available: "false" }),
      referenceRow({ dex_number: "8", entry_type: "lucky", entry_type_label: "Lucky", available: "false" }),
    ];
    assert.deepEqual(unavailableKindRows(rows, "7").map((kind) => kind.entryType), ["shadow"]);
  });

  it("builds kinds and regions from the file without adding overall", () => {
    const rows = [
      referenceRow({ region: "johto", region_label: "Johto", entry_type: "shiny", entry_type_label: "Shiny" }),
      referenceRow({ region: "kanto", region_label: "Kanto", entry_type: "pokemon", entry_type_label: "Pokémon" }),
      referenceRow({ region: "kanto", region_label: "Kanto", entry_type: "shadow", entry_type_label: "Shadow" }),
    ];
    assert.deepEqual(regionChoices(rows).map((region) => region.id), ["johto", "kanto"]);
    assert.equal(regionChoices(rows).some((region) => region.id === "overall"), false);
    assert.deepEqual(kindChoices(rows).map((kind) => kind.id), ["shiny", "pokemon", "shadow"]);
    assert.equal(defaultKindId(kindChoices(rows)), "pokemon");
    assert.deepEqual(accountNames([{ account: "Main" }, { account: "" }, { account: "Alt" }]), ["Main", "Alt"]);
  });
});

describe("sync decisions", () => {
  it("does not accept remote species bytes when a pending upload fails", () => {
    const result = speciesBytesAfterSync({
      localBytes: "local-species",
      remoteBytes: "remote-species",
      pending: true,
      uploadSucceeded: false,
      speciesLocalModified: "2026-10-22T10:00:00.000Z",
      speciesRemoteModified: "2026-10-22T12:00:00.000Z",
    });
    assert.equal(result.bytes, "local-species");
    assert.equal(result.replaced, false);
    assert.equal(result.pending, true);
    assert.equal(syncResultLine({ pendingKept: true, error: "upload failed" }), "pending kept");
  });

  it("may pull reference after a pending upload succeeds", () => {
    const plan = planSync({
      pending: true,
      uploadSucceeded: true,
      speciesLocalModified: "2026-10-22T12:00:00.000Z",
      speciesRemoteModified: "2026-10-22T12:00:00.000Z",
      referenceLocalModified: "2026-10-21T00:00:00.000Z",
      referenceRemoteModified: "2026-10-22T00:00:00.000Z",
      accountsLocalModified: "2026-10-22T00:00:00.000Z",
      accountsRemoteModified: "2026-10-21T00:00:00.000Z",
    });
    assert.equal(plan.pendingKept, false);
    assert.equal(plan.clearPending, true);
    assert.equal(plan.acceptRemoteSpecies, false);
    assert.equal(plan.downloadReference, true);
    assert.equal(plan.downloadAccounts, false);
  });

  it("replaces species from a newer remote when nothing is pending", () => {
    const replaced = speciesBytesAfterSync({
      localBytes: "local",
      remoteBytes: "remote",
      pending: false,
      uploadSucceeded: null,
      speciesLocalModified: "2026-10-22T08:00:00.000Z",
      speciesRemoteModified: "2026-10-22T09:00:00.000Z",
    });
    assert.equal(replaced.bytes, "remote");
    assert.equal(replaced.replaced, true);
    assert.equal(replaced.pending, false);
    const sameTime = speciesBytesAfterSync({
      localBytes: "local",
      remoteBytes: "remote",
      pending: false,
      uploadSucceeded: null,
      speciesLocalModified: "2026-10-22T09:00:00.000Z",
      speciesRemoteModified: "2026-10-22T09:00:00.000Z",
    });
    assert.equal(sameTime.bytes, "local");
    assert.equal(sameTime.replaced, false);
    assert.equal(syncResultLine({}), "synced");
    assert.equal(syncResultLine({ error: "Drive down" }), "Drive down");
  });

  it("builds a refresh request without a client secret", () => {
    const request = buildRefreshTokenRequest({ clientId: "android-client", refreshToken: "ref" });
    const params = new URLSearchParams(request.body);
    assert.equal(request.url, "https://oauth2.googleapis.com/token");
    assert.equal(params.get("client_id"), "android-client");
    assert.equal(params.get("grant_type"), "refresh_token");
    assert.equal(params.get("refresh_token"), "ref");
    assert.equal(params.has("client_secret"), false);
  });

  it("builds the Android redirect from the reversed client id", () => {
    assert.equal(
      googleAndroidRedirectUrl("123-abc.apps.googleusercontent.com"),
      "com.googleusercontent.apps.123-abc:/oauth2redirect",
    );
    assert.equal(googleAndroidRedirectUrl(""), "");
  });
});
