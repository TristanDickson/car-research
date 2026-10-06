import "fake-indexeddb/auto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { __clearSeedingMemoForTests, __resetForTests, ensureSeeded, getDb } from "./db";

type Files = Record<string, unknown>;

/** Stub fetch to serve snapshot files by basename; returns the list of names requested. */
function serve(files: Files): string[] {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const name = String(url).split("/").pop() ?? "";
      calls.push(name);
      const body = files[name];
      if (body === undefined) return { ok: false, status: 404, json: async () => null };
      return { ok: true, status: 200, json: async () => body };
    }),
  );
  return calls;
}

const car = (id: string) => ({
  id,
  make: "Hyundai",
  model: "Ioniq 3",
  trim: id,
  seats: 5,
  picks: [],
  image: null,
  requirement_check: { passes: true, failures: [], unknown: [] },
  deal_summary: {
    offers: 0, current_offers: 0, best_cash_price: null, best_cash_offer_id: null, best_cash_age_days: null,
    best_pcp_monthly: null, best_pcp_offer_id: null, best_pcp_age_days: null,
    best_pch_effective_monthly: null, best_pch_offer_id: null, best_pch_age_days: null,
  },
});

function snapshot(generated_at: string, carIds: string[]) {
  return {
    "manifest.json": { schema_version: "2", generated_at, counts: { cars: carIds.length, offers: 1 } },
    "cars.json": carIds.map(car),
    "offers.json": [{ id: "o1", car_id: carIds[0], provider: "test", captured_at: "2026-10-05", finance_type: "pcp", status: "live", metrics: {},
      freshness: { state: "live", stale: false, age_days: 1, first_seen_at: "2026-10-05", last_seen_at: "2026-10-05", last_checked_at: "2026-10-05", observations: 1, present: true, history: [] } }],
    "requirements.json": { as_of: "2026-10-06", hard: [], preferences: [], wants: [] },
    "data.json": { generated_at, stale_days: 14, providers: [], runs: [], unmapped_trims: [], offer_states: {}, counts: {} },
  };
}

const count = (calls: string[], name: string) => calls.filter((c) => c === name).length;

describe("IndexedDB seeding from the snapshot", () => {
  beforeEach(async () => {
    await __resetForTests();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("seeds cars and offers on first load and memoises within a session", async () => {
    const calls = serve(snapshot("2026-10-06T10:00:00Z", ["a", "b"]));
    const m = await ensureSeeded();
    await ensureSeeded();
    expect(m.generated_at).toBe("2026-10-06T10:00:00Z");
    expect(await getDb().cars.count()).toBe(2);
    expect(await getDb().offers.count()).toBe(1);
    expect(count(calls, "manifest.json")).toBe(1);
    expect(count(calls, "cars.json")).toBe(1);
  });

  it("on reload with the same snapshot it re-checks the manifest only", async () => {
    const calls = serve(snapshot("2026-10-06T10:00:00Z", ["a", "b"]));
    await ensureSeeded();
    __clearSeedingMemoForTests();
    await ensureSeeded();
    expect(count(calls, "manifest.json")).toBe(2);
    expect(count(calls, "cars.json")).toBe(1);
    expect(await getDb().cars.count()).toBe(2);
  });

  it("re-seeds and replaces rows when a newer snapshot is published", async () => {
    serve(snapshot("2026-10-06T10:00:00Z", ["a", "b"]));
    await ensureSeeded();
    __clearSeedingMemoForTests();
    vi.unstubAllGlobals();
    serve(snapshot("2026-10-07T09:00:00Z", ["c"]));
    const m = await ensureSeeded();
    expect(m.generated_at).toBe("2026-10-07T09:00:00Z");
    expect((await getDb().cars.toArray()).map((c) => c.id)).toEqual(["c"]);
    expect((await getDb().meta.get("generated_at"))?.value).toBe("2026-10-07T09:00:00Z");
  });

  it("surfaces a failed manifest fetch and lets the next call retry", async () => {
    serve({});
    await expect(ensureSeeded()).rejects.toThrow(/manifest.json -> 404/);
    vi.unstubAllGlobals();
    serve(snapshot("2026-10-06T10:00:00Z", ["a"]));
    expect((await ensureSeeded()).counts.cars).toBe(1);
  });
});
