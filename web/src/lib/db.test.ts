import "fake-indexeddb/auto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { __clearSeedingMemoForTests, __resetForTests, checkForUpdate, deleteSearch, ensureComputed, ensureSeeded, getCarDetails, getDb, getRequirements, getSearches, resetSearches, saveRequirements, saveSearch } from "./db";

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

const car = (id: string) => ({ id, make: "Hyundai", model: "Ioniq 3", trim: id, seats: 5, picks: [], image: null, model_key: "hyundai/ioniq-3" });
const today = new Date().toISOString().slice(0, 10);

const span = (key: string, car_id: string, route: string, deal: Record<string, unknown>, present = true) =>
  ({ key, car_id, model: "hyundai/ioniq-3", route, source: "carwow", provider: "carwow_deals", status: "live", seller: "A dealer", from: "2026-09-01", to: today, present, deal });

function snapshot(generated_at: string, carIds: string[]) {
  return {
    "manifest.json": { schema_version: "7", generated_at, counts: { cars: carIds.length, offers: 2 } },
    "cars.json": carIds.map(car),
    "sightings.json": [
      span("k1", carIds[0], "cash", { list_price: 30000, vehicle_price: 27000 }),
      span("p1", carIds[0], "pcp", { list_price: 30000, vehicle_price: 27000, customer_deposit: 0, apr: 0.069, num_payments: 48, term_months: 49, gfv: 11000, monthly_payment: 380 }),
    ],
    "used_spans.json": [2021, 2021, 2021].map((year, i) => ({ key: `u${i}`, source: "cinch", model: "hyundai/ioniq-3", car_id: null, year, price: 12000 + i * 500, mileage: 10000 + i, vrm: `V${i}`, town: null, from: "2026-09-01", to: today, present: true })),
    "requirements.json": { as_of: "2026-10-06", hard: [], preferences: [], wants: [], quoting_basis: { term_months: 37, savings_rate_apr: 0.04, residual_pct_of_list: 0.45, residual_at_months: 36 },
                           searches: [{ name: "Hand-curated", query: "standard=curated" }, { name: "My brief", query: "r.seats=4-&listed=flag:heat_pump,flag:v2l_internal", default: true }] },
    "details.json": Object.fromEntries(carIds.map((id) => [id, { specs: [], spec_check: { rows: [], disagreements: 0 }, requirement_check: { passes: true, failures: [], unknown: [] } }])),
    "used.json": [],
    "data.json": { generated_at, stale_days: 14, providers: [], runs: [], unmapped_trims: [], offer_states: {}, counts: {}, sources: { carwow: "Carwow" } },
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

  it("seeds cars and spans on first load and memoises within a session", async () => {
    const calls = serve(snapshot("2026-10-06T10:00:00Z", ["a", "b"]));
    const m = await ensureSeeded();
    await ensureSeeded();
    expect(m.generated_at).toBe("2026-10-06T10:00:00Z");
    expect(await getDb().cars.count()).toBe(2);
    expect(await getDb().sightings.count()).toBe(2);
    expect(await getDb().used_spans.count()).toBe(3);
    expect(count(calls, "manifest.json")).toBe(1);
    expect(count(calls, "cars.json")).toBe(1);
  });

  it("on reload it reads the stored snapshot without touching the network; the update check asks for the manifest", async () => {
    const calls = serve(snapshot("2026-10-06T10:00:00Z", ["a", "b"]));
    await ensureSeeded();
    await new Promise((r) => setTimeout(r, 50));   // let the background fetch of the on-demand files finish
    __clearSeedingMemoForTests();
    const before = calls.length;
    const m = await ensureSeeded();
    expect(m.generated_at).toBe("2026-10-06T10:00:00Z");
    expect(calls.length).toBe(before);
    expect(await checkForUpdate()).toBe("current");
    expect(count(calls, "manifest.json")).toBe(2);
    expect(count(calls, "cars.json")).toBe(1);
    expect(await getDb().cars.count()).toBe(2);
  });

  it("works offline from the stored snapshot, car details included", async () => {
    serve(snapshot("2026-10-06T10:00:00Z", ["a", "b"]));
    await ensureSeeded();
    await new Promise((r) => setTimeout(r, 50));   // the on-demand files are fetched in the background
    expect(await getDb().details.count()).toBe(2);
    __clearSeedingMemoForTests();
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    expect((await ensureSeeded()).generated_at).toBe("2026-10-06T10:00:00Z");
    expect(await checkForUpdate()).toBe("offline");
    expect(await getCarDetails("a")).toBeTruthy();
    expect(await getDb().cars.count()).toBe(2);
  });

  it("swaps in a newer snapshot when the update check finds one", async () => {
    serve(snapshot("2026-10-06T10:00:00Z", ["a", "b"]));
    await ensureSeeded();
    __clearSeedingMemoForTests();
    vi.unstubAllGlobals();
    serve(snapshot("2026-10-07T09:00:00Z", ["c"]));
    expect((await ensureSeeded()).generated_at).toBe("2026-10-06T10:00:00Z");   // the stored one first
    expect(await checkForUpdate()).toBe("updated");
    expect((await ensureSeeded()).generated_at).toBe("2026-10-07T09:00:00Z");
    expect((await getDb().cars.toArray()).map((c) => c.id)).toEqual(["c"]);
    expect((await getDb().meta.get("generated_at"))?.value).toBe("2026-10-07T09:00:00Z");
  });

  it("does not download a data format this build cannot read", async () => {
    serve(snapshot("2026-10-06T10:00:00Z", ["a"]));
    await ensureSeeded();
    vi.unstubAllGlobals();
    const next = snapshot("2026-10-07T09:00:00Z", ["c"]);
    const calls = serve({ ...next, "manifest.json": { ...next["manifest.json"], schema_version: "8" } });
    expect(await checkForUpdate()).toBe("app-outdated");
    expect(count(calls, "cars.json")).toBe(0);
    expect((await getDb().cars.toArray()).map((c) => c.id)).toEqual(["a"]);
  });

  it("surfaces a failed manifest fetch and lets the next call retry", async () => {
    serve({});
    await expect(ensureSeeded()).rejects.toThrow(/manifest.json -> 404/);
    vi.unstubAllGlobals();
    serve(snapshot("2026-10-06T10:00:00Z", ["a"]));
    expect((await ensureSeeded()).counts.cars).toBe(1);
  });
});

describe("saved searches", () => {
  beforeEach(async () => {
    await __resetForTests();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("are seeded from the snapshot once, in one spelling, with the seed's default", async () => {
    serve(snapshot("2026-10-06T10:00:00Z", ["a"]));
    const list = await getSearches();
    expect(list.searches.map((x) => x.name)).toEqual(["Hand-curated", "My brief"]);
    expect(list.default_id).toBe(list.searches[1].id);
    expect(list.searches[1].query).toBe("r.seats=4-&listed=flag%3Aheat_pump%2Cflag%3Av2l_internal");
  });

  it("save under a name, replace by the same name, delete the default and the next one takes over, reset to the seed", async () => {
    serve(snapshot("2026-10-06T10:00:00Z", ["a"]));
    let list = await saveSearch("Seven seats", "r.seats=7-");
    expect(list.searches.map((x) => x.name)).toEqual(["Hand-curated", "My brief", "Seven seats"]);
    list = await saveSearch("seven seats ", "r.seats=7-&sort=range");
    expect(list.searches).toHaveLength(3);
    expect(list.searches[2].query).toBe("sort=range&r.seats=7-");
    list = await deleteSearch(list.default_id!);
    expect(list.searches.map((x) => x.name)).toEqual(["Hand-curated", "seven seats"]);   // the name as last typed
    expect(list.default_id).toBe(list.searches[0].id);
    list = await resetSearches();
    expect(list.searches.map((x) => x.name)).toEqual(["Hand-curated", "My brief"]);
  });

  it("a list begun before the snapshot carried seeded searches gets them once, keeping the reader's own", async () => {
    const old = snapshot("2026-10-06T10:00:00Z", ["a"]);
    const { searches: _drop, ...bare } = old["requirements.json"];
    serve({ ...old, "requirements.json": bare });
    expect((await getSearches()).searches).toEqual([]);
    await saveSearch("Mine", "make=Kia");
    vi.unstubAllGlobals();
    serve(snapshot("2026-10-07T09:00:00Z", ["c"]));
    expect(await checkForUpdate()).toBe("updated");
    const list = await getSearches();
    expect(list.searches.map((x) => x.name)).toEqual(["Mine", "Hand-curated", "My brief"]);
    expect(list.default_id).toBe(list.searches[0].id);
    await deleteSearch(list.searches[1].id);
    expect((await getSearches()).searches.map((x) => x.name)).toEqual(["Mine", "My brief"]);   // not merged back in
  });

  it("survive a new snapshot", async () => {
    serve(snapshot("2026-10-06T10:00:00Z", ["a"]));
    await saveSearch("Mine", "make=Kia");
    vi.unstubAllGlobals();
    serve(snapshot("2026-10-07T09:00:00Z", ["c"]));
    expect(await checkForUpdate()).toBe("updated");
    expect((await getSearches()).searches.map((x) => x.name)).toContain("Mine");
  });
});

describe("the cost model runs in the browser and its results are stored", () => {
  beforeEach(async () => {
    await __resetForTests();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("costs every span under the seeded basis, once, and stores costs, series, residuals and offers", async () => {
    serve(snapshot("2026-10-06T10:00:00Z", ["a", "b"]));
    await ensureComputed();
    const db = getDb();
    const row = await db.costs.get("a");
    expect(row).toBeTruthy();
    expect(Object.keys(row!.routes).sort()).toEqual(["cash", "pcp", "used"]);
    expect(row!.routes.pcp!.carwow.at_horizon).toBe("settle_early");     // a 49-month PCP over a 37-month term
    expect(row!.routes.pcp!.carwow.own_horizon_months).toBe(49);
    expect(row!.routes.used!.cinch.headline).toBe(12000);
    expect(row!.stock?.by_year["2021"].n).toBe(3);
    expect(Object.keys((await db.costs.get("b"))!.routes)).toEqual(["used"]);   // no offer of its own, but its model has used stock
    expect(await db.series.count()).toBe(3);
    expect(await db.residuals.count()).toBe(1);
    expect((await db.offers.toArray()).map((o) => o.id).sort()).toEqual(["k1", "p1"]);
    const key = (await db.meta.get("costed"))?.value;
    expect(key).toContain('"term_months":37');
    await ensureComputed();
    expect((await db.meta.get("costed"))?.value).toBe(key);
  });

  it("a changed basis recomputes everything; the stored key follows", async () => {
    serve(snapshot("2026-10-06T10:00:00Z", ["a"]));
    await ensureComputed();
    const before = (await getDb().costs.get("a"))!.routes.pcp!.carwow;
    const reqs = (await getRequirements())!;
    await saveRequirements({ ...reqs, quoting_basis: { ...(reqs.quoting_basis ?? {}), term_months: 49, compare_over: "own" } });
    const after = (await getDb().costs.get("a"))!.routes.pcp!.carwow;
    expect(after.at_horizon).toBe("as_agreed");
    expect(after.horizon_months).toBe(49);
    expect(after.true_monthly).not.toBe(before.true_monthly);
    expect((await getDb().meta.get("costed"))?.value).toContain('"term_months":49');
  });
});
