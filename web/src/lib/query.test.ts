import { describe, expect, it } from "vitest";

import type { CarCosts, TrueCost } from "./costs";
import { canonical, carPacks, cycleFacet, describeQuery, EMPTY_QUERY, matches, parseQuery, searchPacks, serializeQuery, type CarContext, type Query } from "./query";
import type { SnapshotCar } from "./types";

const car = (over: Partial<SnapshotCar>): SnapshotCar =>
  ({ id: "c", make: "Hyundai", model: "Kona Electric", trim: "Ultimate", picks: [], ...over }) as unknown as SnapshotCar;

const costs = (over: Partial<CarCosts> = {}): CarCosts =>
  ({ trueCost: null, byRoute: {}, sources: 0, monthly: null, monthlyRoute: null, threeYear: null, cash: null, trend: null, stock: null, ...over });
const tc = (over: Partial<TrueCost>): TrueCost =>
  ({ route: "pcp", offerId: "p", dealer: null, source: "carwow", sourceName: "Carwow", monthly: 350, floor: null, headline: 300, endValue: null, residualSource: null,
     ageDays: 0, horizonMonths: 37, atHorizon: "as_agreed", ownMonthly: 350, ownHorizonMonths: 37, terms: { paid: null }, ...over });
const ctx = (over: Partial<CarContext> = {}): CarContext => ({ costs: costs(), ...over });

describe("query", () => {
  it("round-trips through the URL", () => {
    const q: Query = { ...EMPTY_QUERY, q: "ultimate", make: "Hyundai", mode: "any",
      ranges: { true: [200, 400], seats: [5, null], turn: [null, 10.5] }, facets: { "flag:heat_pump": "standard", "route:used": "hide", "flag:glass_roof": "listed" } };
    const qs = serializeQuery(q);
    expect(qs).toContain("r.true=200-400");
    expect(qs).toContain("r.seats=5-");
    expect(qs).toContain("r.turn=-10.5");
    expect(parseQuery(new URLSearchParams(qs))).toEqual(q);
    expect(serializeQuery(EMPTY_QUERY)).toBe("");
  });

  it("cycles a facet off → standard → listed → hide → off, two-state facets skipping listed", () => {
    let q: Query = { ...EMPTY_QUERY };
    q = { ...q, ...cycleFacet(q, "flag:heat_pump") };
    expect(q.facets["flag:heat_pump"]).toBe("standard");
    q = { ...q, ...cycleFacet(q, "flag:heat_pump") };
    expect(q.facets["flag:heat_pump"]).toBe("listed");
    q = { ...q, ...cycleFacet(q, "flag:heat_pump") };
    expect(q.facets["flag:heat_pump"]).toBe("hide");
    q = { ...q, ...cycleFacet(q, "flag:heat_pump") };
    expect(q.facets["flag:heat_pump"]).toBeUndefined();
    q = { ...q, ...cycleFacet(q, "priced", true) };
    q = { ...q, ...cycleFacet(q, "priced", true) };
    expect(q.facets.priced).toBe("hide");
  });

  it("standard, listed and hide read the car's flags; all and any combine the wanted ones", () => {
    const c = car({ auto: true, flags: { heat_pump: "standard", glass_roof: "option" } });
    const base: Query = { ...EMPTY_QUERY };
    expect(matches(c, ctx(), { ...base, facets: { "flag:heat_pump": "standard" } })).toBe(true);
    expect(matches(c, ctx(), { ...base, facets: { "flag:glass_roof": "standard" } })).toBe(false);
    expect(matches(c, ctx(), { ...base, facets: { "flag:glass_roof": "listed" } })).toBe(true);
    expect(matches(c, ctx(), { ...base, facets: { "flag:glass_roof": "hide" } })).toBe(false);
    expect(matches(c, ctx(), { ...base, facets: { "flag:tow_prep": "hide" } })).toBe(true);
    const two = { "flag:heat_pump": "standard" as const, "flag:tow_prep": "standard" as const };
    expect(matches(c, ctx(), { ...base, facets: two, mode: "all" })).toBe(false);
    expect(matches(c, ctx(), { ...base, facets: two, mode: "any" })).toBe(true);
  });

  it("ranges read costs and fields and drop cars that carry no value; an empty search admits every car", () => {
    const c = car({ seats: 5, wltp_range_mi: 282, turning_circle_m: 10.2 });
    const k = ctx({ costs: costs({ trueCost: tc({}), byRoute: {} }) });
    expect(matches(c, k, { ...EMPTY_QUERY, ranges: { true: [300, 400] } })).toBe(true);
    expect(matches(c, k, { ...EMPTY_QUERY, ranges: { true: [null, 300] } })).toBe(false);
    expect(matches(c, k, { ...EMPTY_QUERY, ranges: { dc: [100, null] } })).toBe(false);
    expect(matches(c, k, { ...EMPTY_QUERY, ranges: { turn: [null, 10.5] } })).toBe(true);
    expect(matches(c, k, { ...EMPTY_QUERY, ranges: { turn: [null, 10] } })).toBe(false);
    expect(matches(car({ auto: true }), ctx(), { ...EMPTY_QUERY })).toBe(true);
    expect(matches(car({}), ctx(), { ...EMPTY_QUERY })).toBe(true);
  });

  it("routes and provenance are facets too", () => {
    const c = car({});
    const k = ctx({ costs: costs({ byRoute: { used: tc({ route: "used", offerId: "u", source: "cinch", monthly: 250, headline: 14000 }) } }) });
    expect(matches(c, k, { ...EMPTY_QUERY, facets: { "route:used": "standard" } })).toBe(true);
    expect(matches(c, k, { ...EMPTY_QUERY, facets: { "route:pcp": "standard" } })).toBe(false);
    expect(matches(c, k, { ...EMPTY_QUERY, facets: { curated: "standard" } })).toBe(true);
    expect(matches(car({ auto: true }), k, { ...EMPTY_QUERY, facets: { curated: "standard" } })).toBe(false);
  });

  it("old links' scope and brief parameters are ignored; a saved search compares in one spelling", () => {
    expect(parseQuery(new URLSearchParams("scope=all&brief=all&make=Kia"))).toEqual({ ...EMPTY_QUERY, ranges: {}, facets: {}, make: "Kia" });
    expect(canonical("r.seats=4-&listed=flag%3Av2l_internal%2Cflag%3Aheat_pump")).toBe(canonical("listed=flag:heat_pump,flag:v2l_internal&r.seats=4-"));
  });

  it("the packs a car needs are the ones behind the equipment the search asks for", () => {
    const c = car({ flags: { heat_pump: "pack", v2l_internal: "pack", camera_360: "pack" },
      packs_required: { heat_pump: "Heat Pump", internal_v2l: "Tech Pack", camera_360: "Tech Pack" }, pack_prices_gbp: { "Heat Pump": 760, "Tech Pack": 500 } });
    const q: Query = { ...EMPTY_QUERY, facets: { "flag:heat_pump": "listed", "flag:v2l_internal": "listed", "flag:glass_roof": "standard" } };
    expect(searchPacks(q, c)).toEqual([{ flag: "heat_pump", pack: "Heat Pump", price: 760 }, { flag: "v2l_internal", pack: "Tech Pack", price: 500 }]);
    expect(searchPacks(EMPTY_QUERY, c)).toEqual([]);
    expect(carPacks(c)).toEqual([{ pack: "Heat Pump", price: 760, flags: ["heat_pump"] }, { pack: "Tech Pack", price: 500, flags: ["v2l_internal", "camera_360"] }]);
  });

  it("describes a search in words", () => {
    const q = parseQuery(new URLSearchParams("listed=flag:heat_pump,flag:v2l_internal&r.seats=4-&r.width=-1890&sort=range"));
    expect(describeQuery(q, { heat_pump: "Heat pump", v2l_internal: "Internal V2L socket" }))
      .toBe("Heat pump: standard, pack or option · Internal V2L socket: standard, pack or option · Width ≤ 1,890 mm · Seats ≥ 4 · sorted by longest range");
    expect(describeQuery(parseQuery(new URLSearchParams("r.true=200-400&r.wheels=-18")), {}))
      .toBe("True cost per month £200–£400 · Wheel size ≤ 18 in");
    expect(describeQuery(EMPTY_QUERY, {})).toBe("every car");
  });

  it("bounds any number a car carries or costs; an unknown key is dropped", () => {
    const q = parseQuery(new URLSearchParams("r.wheels=-18&r.real_cold=150-&r.fell=-1000--100&r.nonsense=1-2&r.usable=x-5"));
    expect(q.ranges).toEqual({ wheels: [null, 18], real_cold: [150, null], fell: [-1000, -100] });
    expect(parseQuery(new URLSearchParams(serializeQuery(q)))).toEqual(q);
    const fits = car({ wheel_in: 17, real_range_cold_mi: 160 });
    const tod = (k: Partial<CarCosts>) => ctx({ costs: costs(k) });
    const down = { delta: -500, from: 30000, to: 29500, days: 30 } as unknown as CarCosts["trend"];
    expect(matches(fits, tod({ trend: down }), q)).toBe(true);
    expect(matches(car({ wheel_in: 19, real_range_cold_mi: 160 }), tod({ trend: down }), q)).toBe(false);
    // A car no source has a value for is left out of a bound on that value.
    expect(matches(car({ real_range_cold_mi: 160 }), tod({ trend: down }), q)).toBe(false);
    expect(matches(fits, tod({ trend: { ...down!, delta: 200 } as CarCosts["trend"] }), q)).toBe(false);
  });
});
