import { describe, expect, it } from "vitest";

import type { Brief } from "./brief";
import type { CarCosts } from "./costs";
import { cycleFacet, EMPTY_QUERY, matches, parseQuery, serializeQuery, type CarContext, type Query } from "./query";
import type { SnapshotCar } from "./types";

const car = (over: Partial<SnapshotCar>): SnapshotCar =>
  ({ id: "c", make: "Hyundai", model: "Kona Electric", trim: "Ultimate", picks: [], deal_summary: { routes: {} }, ...over }) as unknown as SnapshotCar;

const brief = (status: Brief["status"]): Brief => ({ status, failures: [], unknown: [], failedLabels: [], unknownLabels: [], rules: [] });
const costs = (over: Partial<CarCosts> = {}): CarCosts =>
  ({ trueCost: null, byRoute: {}, sources: 0, monthly: null, monthlyRoute: null, threeYear: null, pcp: null, pch: null, cash: null, ...over });
const ctx = (over: Partial<CarContext> = {}): CarContext => ({ brief: brief("pass"), costs: costs(), starred: false, ...over });

describe("query", () => {
  it("round-trips through the URL", () => {
    const q: Query = { ...EMPTY_QUERY, scope: "all", q: "ultimate", make: "Hyundai", mode: "any", brief: "pass",
      ranges: { true: [200, 400], seats: [5, null] }, facets: { "flag:heat_pump": "standard", "route:used": "hide", "flag:glass_roof": "listed" } };
    const qs = serializeQuery(q);
    expect(qs).toContain("r.true=200-400");
    expect(qs).toContain("r.seats=5-");
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
    const base: Query = { ...EMPTY_QUERY, scope: "all" };
    expect(matches(c, ctx(), { ...base, facets: { "flag:heat_pump": "standard" } })).toBe(true);
    expect(matches(c, ctx(), { ...base, facets: { "flag:glass_roof": "standard" } })).toBe(false);
    expect(matches(c, ctx(), { ...base, facets: { "flag:glass_roof": "listed" } })).toBe(true);
    expect(matches(c, ctx(), { ...base, facets: { "flag:glass_roof": "hide" } })).toBe(false);
    expect(matches(c, ctx(), { ...base, facets: { "flag:tow_prep": "hide" } })).toBe(true);
    const two = { "flag:heat_pump": "standard" as const, "flag:tow_prep": "standard" as const };
    expect(matches(c, ctx(), { ...base, facets: two, mode: "all" })).toBe(false);
    expect(matches(c, ctx(), { ...base, facets: two, mode: "any" })).toBe(true);
  });

  it("ranges read costs and fields and drop cars that carry no value; the brief and scope gate first", () => {
    const c = car({ seats: 5, wltp_range_mi: 282 });
    const k = ctx({ costs: costs({ trueCost: { route: "pcp", offerId: "p", dealer: null, source: "Carwow", monthly: 350, floor: null, headline: 300, endValue: null, ageDays: 0 }, byRoute: {} }) });
    expect(matches(c, k, { ...EMPTY_QUERY, ranges: { true: [300, 400] } })).toBe(true);
    expect(matches(c, k, { ...EMPTY_QUERY, ranges: { true: [null, 300] } })).toBe(false);
    expect(matches(c, k, { ...EMPTY_QUERY, ranges: { dc: [100, null] } })).toBe(false);
    expect(matches(c, ctx({ brief: brief("fail") }), { ...EMPTY_QUERY })).toBe(false);
    expect(matches(c, ctx({ brief: brief("unknown") }), { ...EMPTY_QUERY })).toBe(true);
    expect(matches(c, ctx({ brief: brief("unknown") }), { ...EMPTY_QUERY, brief: "pass" })).toBe(false);
    expect(matches(car({ auto: true }), ctx(), { ...EMPTY_QUERY })).toBe(false);
    expect(matches(car({ auto: true }), ctx(), { ...EMPTY_QUERY, scope: "all" })).toBe(true);
  });

  it("routes and provenance are facets too", () => {
    const c = car({});
    const k = ctx({ costs: costs({ byRoute: { used: { route: "used", offerId: "u", dealer: null, source: "cinch", monthly: 250, floor: null, headline: 14000, endValue: null, ageDays: 0 } } }), starred: true });
    expect(matches(c, k, { ...EMPTY_QUERY, facets: { "route:used": "standard" } })).toBe(true);
    expect(matches(c, k, { ...EMPTY_QUERY, facets: { "route:pcp": "standard" } })).toBe(false);
    expect(matches(c, k, { ...EMPTY_QUERY, facets: { starred: "standard", curated: "standard" } })).toBe(true);
  });
});
