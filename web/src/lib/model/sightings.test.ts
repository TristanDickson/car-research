import { describe, expect, it } from "vitest";

import { DEFAULT_BASIS, usedRoute, type Basis, type DealFields } from "./dealMath";
import { pcpOverHorizon } from "./horizon";
import { bestByRoute, cost, costAll, current, floorGfvAt, goneDates, markCurrent, residualAt, residualSeries, series, subject, trend, usedStock, type Sighting } from "./sightings";

const BASIS: Basis = { ...DEFAULT_BASIS, term_months: 37, savings_rate_apr: 0.04, residual_pct_of_list: 0.45, residual_at_months: 36 };
const MODEL = "hyundai/ioniq-5";

const used = (key: string, price: number, year: number, from: string, to: string, o: { source?: string; vrm?: string; mileage?: number; present?: boolean } = {}): Sighting =>
  ({ key, route: "used", source: o.source ?? "cinch", model: MODEL, car_id: null, from, to, present: o.present ?? true,
     deal: { price, year, mileage: o.mileage ?? 30000, vrm: o.vrm ?? null }, seller: null });

const offer = (key: string, route: "cash" | "pcp" | "pch", source: string, deal: DealFields, from: string, to: string, o: { car_id?: string; present?: boolean } = {}): Sighting =>
  ({ key, route, source, model: MODEL, car_id: o.car_id ?? "car-a", from, to, present: o.present ?? true, deal, seller: (deal.dealer as string) ?? null });

const PCP: DealFields = { list_price: 40000, vehicle_price: 36000, customer_deposit: 0, manufacturer_contribution: 0, apr: 0, num_payments: 36, term_months: 37, gfv: 18000, monthly_payment: 500, dealer: "Hyundai Finance" };
const CASH: DealFields = { list_price: 40000, vehicle_price: 34000, dealer: "A broker" };
const STOCK = [20000, 21000, 22000].map((p, i) => used(`s${i}`, p, 2023, "2026-10-01", "2026-10-07", { vrm: `V${i}`, mileage: i + 1 }));

describe("evidence", () => {
  it("reads the residual as of a date and counts a car once", () => {
    const at = residualAt([
      used("a", 20000, 2023, "2026-10-01", "2026-10-07", { vrm: "AB23CDE" }),
      used("b", 20099, 2023, "2026-10-03", "2026-10-07", { source: "carwow", mileage: 30000 }),   // the same car, no plate
      used("c", 22000, 2023, "2026-10-03", "2026-10-07", { vrm: "ZZ23ZZZ", mileage: 1 }),
      used("d", 21000, 2023, "2026-10-05", "2026-10-07", { source: "motorpoint", mileage: 2 }),
      used("e", 15000, 2023, "2026-09-01", "2026-09-20", { vrm: "OLD23OLD", mileage: 3, present: false }),
    ]);
    expect(at(MODEL, 2023, "2026-10-02")).toBeNull();                 // one car is not evidence
    expect(at(MODEL, 2023, "2026-10-04")).toBeNull();                 // a and b are one car: two cars, not three
    expect(at(MODEL, 2023, "2026-10-06")).toEqual([21000, 3]);
    expect(at(MODEL, 2022, "2026-10-06")).toBeNull();
    expect(at(MODEL, 2023, "2026-09-10")).toBeNull();                 // a gone listing is not evidence
  });
  it("the floor is the highest gfv guaranteed on the day", () => {
    const at = floorGfvAt([offer("p1", "pcp", "hyundai", { ...PCP, gfv: 18000 }, "2026-01-01", "2026-06-30"),
                           offer("p2", "pcp", "carwow", { ...PCP, gfv: 19000 }, "2026-05-01", "2026-10-07")]);
    expect([at("car-a", "2026-03-01"), at("car-a", "2026-06-01"), at("car-a", "2026-09-01"), at("car-b", "2026-06-01")]).toEqual([18000, 19000, 19000, null]);
  });
});

describe("costing", () => {
  it("a pcp sighting is costed on what the market said that day", () => {
    const pcp = offer("p", "pcp", "hyundai", PCP, "2026-06-01", "2026-10-07");
    const residual = residualAt(STOCK), floor = floorGfvAt([pcp]);
    const june = cost(pcp, BASIS, residual, floor, "2026-06-01")!;
    const today = cost(pcp, BASIS, residual, floor, "2026-10-07")!;
    expect([june.residual_source, today.residual_source]).toEqual(["gfv-grown", "used-market"]);
    expect(today.end_value).toBe(21000);
    expect(today.true_monthly!).toBeLessThan(june.true_monthly!);      // equity above the GFV makes the PCP cheaper
    expect([june.headline, june.as_of, june.at_horizon, june.horizon_months]).toEqual([500, "2026-06-01", "as_agreed", 37]);
    expect(june.own_true_monthly).toBe(june.true_monthly);
  });
  it("a used sighting is costed like the used route", () => {
    const c = cost(used("x", 19000, 2024, "2026-10-07", "2026-10-07"), BASIS, residualAt(STOCK), floorGfvAt([]), "2026-10-07")!;
    expect([c.headline, c.residual_source]).toEqual([19000, "assumption"]);   // nothing from 2021 says what a 2024 car is worth in 2029
    expect(c.true_monthly).toBeCloseTo(usedRoute(19000, 2, BASIS).true_monthly!, 2);
  });
  it("costAll dates history by first day and today by today, and drops what it cannot cost", () => {
    const pcp = offer("p", "pcp", "hyundai", PCP, "2026-06-01", "2026-10-07");
    const cash = offer("k", "cash", "ncd", CASH, "2026-10-05", "2026-10-07");
    const gone = offer("g", "cash", "carwow", CASH, "2026-01-05", "2026-02-07", { present: false });
    const history = new Map(costAll([pcp, cash, gone, ...STOCK], BASIS).map((c) => [c.s.key, c]));
    expect(Array.from(history.keys()).sort()).toEqual(["k", "p", "s0", "s1", "s2"]);
    expect([history.get("p")!.as_of, history.get("p")!.residual_source, history.get("k")!.residual_source]).toEqual(["2026-06-01", "gfv-grown", "used-market"]);
    const now = new Map(costAll([pcp, cash, ...STOCK], BASIS, "2026-10-07").map((c) => [c.s.key, c]));
    expect(now.get("p")!.residual_source).toBe("used-market");
    expect(cost(offer("bad", "pcp", "x", { vehicle_price: 1 }, "2026-01-01", "2026-01-01"), BASIS, residualAt([]), floorGfvAt([]), "2026-01-01")).toBeNull();
  });
});

describe("the reader's horizon", () => {
  const zero: Basis = { ...BASIS, savings_rate_apr: 0, residual_pct_of_list: 0.45, residual_at_months: 37 };
  const long: DealFields = { ...PCP, num_payments: 48, term_months: 49, monthly_payment: 400, gfv: 14000 };
  const short: DealFields = { ...PCP, num_payments: 24, term_months: 25, monthly_payment: 600, gfv: 22000 };

  it("a longer pcp is settled early at the horizon: at 0% that is the remaining payments and the balloon", () => {
    const h = pcpOverHorizon({ ...long, car_id: "c", finance_type: "pcp" }, 37, zero, null, null, 0)!;
    expect(h.at_horizon).toBe("settle_early");
    // 36 payments before month 37, then at 37: payments 37..48 (12 × 400) + the 14,000 balloon, less the car,
    // worth the lender's GFV grown at the (zero) savings rate: no market evidence, so the GFV beats the flat assumption.
    const paid = 36 * 400 + 12 * 400 + 14000, worth = 14000;
    expect(h.residual_source).toBe("gfv-grown");
    expect(h.pv_cost).toBeCloseTo(paid - worth, 1);
    expect(h.true_monthly).toBeCloseTo((paid - worth) / 37, 1);
  });
  it("a shorter pcp pays its balloon and keeps the car to the horizon", () => {
    const h = pcpOverHorizon({ ...short, car_id: "c", finance_type: "pcp" }, 37, zero, null, null, 0)!;
    expect(h.at_horizon).toBe("balloon_then_keep");
    expect(h.pv_cost).toBeCloseTo(24 * 600 + 22000 - 22000, 1);
    const assumed = pcpOverHorizon({ ...short, gfv: 0, car_id: "c", finance_type: "pcp" }, 37, zero, null, null, 0)!;
    expect([assumed.residual_source, assumed.pv_cost]).toEqual(["assumption", 24 * 600 - 40000 * 0.45]);
  });
  it("the same length is the deal as agreed, and ranking over own terms keeps each deal's own figure", () => {
    const same = pcpOverHorizon({ ...PCP, car_id: "c", finance_type: "pcp" }, 37, zero, null, null, 0)!;
    expect(same.at_horizon).toBe("as_agreed");
    expect(same.true_monthly).toBeCloseTo(500 * 36 / 37, 2);
    const s = offer("p49", "pcp", "hyundai", long, "2026-10-01", "2026-10-07");
    const overH = cost(s, BASIS, residualAt([]), floorGfvAt([]), "2026-10-07")!;
    const own = cost(s, { ...BASIS, compare_over: "own" }, residualAt([]), floorGfvAt([]), "2026-10-07")!;
    expect([overH.horizon_months, overH.at_horizon, own.horizon_months, own.at_horizon]).toEqual([37, "settle_early", 49, "as_agreed"]);
    expect(own.true_monthly).toBe(overH.own_true_monthly);
    expect(own.own_horizon_months).toBe(49);
  });
  it("a longer lease is costed on the rentals that fall within the horizon; a shorter one keeps its own per-month figure", () => {
    const lease = (term: number, n: number) => offer("l", "pch", "leaseloco", { term_months: term, num_rentals: n, monthly_rental: 300, initial_rental: 2700 }, "2026-10-01", "2026-10-07");
    const kinds = [24, 37, 48].map((t) => cost(lease(t, t - 1), BASIS, residualAt([]), floorGfvAt([]), "2026-10-07")!);
    expect(kinds.map((c) => c.at_horizon)).toEqual(["lease_ends", "as_agreed", "lease_cut"]);
    expect(kinds.map((c) => c.horizon_months)).toEqual([37, 37, 37]);
    expect(kinds[0].true_monthly).toBe(kinds[0].own_true_monthly);
    expect(kinds[1].true_monthly).toBe(kinds[1].own_true_monthly);
    // 48 months: the initial rental and 36 of the 47 rentals, spread over 37 months: dearer per month than over its own term.
    const zero = { ...BASIS, savings_rate_apr: 0 };
    const cut = cost(lease(48, 47), zero, residualAt([]), floorGfvAt([]), "2026-10-07")!;
    expect(cut.pv_cost).toBe(2700 + 36 * 300);
    expect(cut.true_monthly).toBeCloseTo((2700 + 36 * 300) / 37, 2);
    expect(cut.true_monthly!).toBeGreaterThan(cut.own_true_monthly!);
  });
});

describe("series", () => {
  it("group by subject, route and source", () => {
    const rows = costAll([
      offer("p", "pcp", "hyundai", PCP, "2026-06-01", "2026-10-07"),
      offer("p-again", "pcp", "hyundai", { ...PCP, monthly_payment: 480 }, "2026-10-01", "2026-10-07"),
      offer("k", "cash", "ncd", CASH, "2026-10-05", "2026-10-07"),
      offer("k2", "cash", "carwow", { ...CASH, vehicle_price: 35000 }, "2026-10-05", "2026-10-07"),
      used("u1", 20000, 2023, "2026-10-01", "2026-10-07", { vrm: "A" }),
      used("u2", 18000, 2023, "2026-10-04", "2026-10-07", { vrm: "B" }),
      used("u3", 19000, 2023, "2026-10-02", "2026-10-07", { source: "carwow" }),
    ], BASIS);
    const out = new Map(series(rows).map((s) => [s.id, s]));
    expect(Array.from(out.keys())).toEqual(["car-a|cash|carwow", "car-a|cash|ncd", "car-a|pcp|hyundai", "model:hyundai/ioniq-5|used|carwow", "model:hyundai/ioniq-5|used|cinch"]);
    expect(out.get("car-a|pcp|hyundai")!.points.map((p) => p.key)).toEqual(["p", "p-again"]);
    const steps = out.get("model:hyundai/ioniq-5|used|cinch")!.points;
    expect(steps.map((p) => [p.from, p.to, p.key])).toEqual([["2026-10-01", "2026-10-04", "u1"], ["2026-10-04", "2026-10-07", "u2"]]);
    expect(steps[1].n).toBe(2);
  });
  it("an offer holds to its next sighting unless seen gone between", () => {
    const sightings = [
      offer("k", "cash", "carwow", CASH, "2025-06-01", "2025-06-01"),
      offer("k", "cash", "carwow", { ...CASH, vehicle_price: 33000 }, "2025-08-01", "2025-08-01"),
      offer("k", "cash", "carwow", { ...CASH, vehicle_price: 33000 }, "2025-09-15", "2025-09-15", { present: false }),
      offer("k", "cash", "carwow", { ...CASH, vehicle_price: 32000 }, "2026-02-01", "2026-10-06"),
    ];
    const pts = series(costAll(sightings, BASIS), goneDates(sightings))[0].points;
    expect(pts.map((p) => [p.from, p.to])).toEqual([["2025-06-01", "2025-08-01"], ["2025-08-01", "2025-08-01"], ["2026-02-01", "2026-10-06"]]);
    expect(goneDates(sightings).get("k")).toEqual(["2025-09-15"]);
  });
  it("residual series samples the evidence monthly", () => {
    const stock = [0, 1, 2].map((i) => used(`s${i}`, 20000 + i * 1000, 2023, "2026-08-15", "2026-10-07", { vrm: `V${i}` }));
    const out = residualSeries(stock, "2026-10-07");
    expect([out[0].model, out[0].year]).toEqual([MODEL, 2023]);
    expect(out[0].points.map((p) => p.date)).toEqual(["2026-09-01", "2026-10-01", "2026-10-07"]);
    expect(out[0].points[2]).toEqual({ date: "2026-10-07", median: 21000, n: 3 });
  });
  it("current is the cheapest per route and source as of today", () => {
    const today = "2026-10-07";
    const rows = costAll([
      offer("k", "cash", "ncd", CASH, "2026-10-05", "2026-10-07"),
      offer("k-old", "cash", "ncd", { ...CASH, vehicle_price: 30000 }, "2026-08-01", "2026-08-20"),   // stale
      offer("k2", "cash", "carwow", { ...CASH, vehicle_price: 35000 }, "2026-10-05", "2026-10-07"),
      offer("p", "pcp", "hyundai", PCP, "2026-06-01", "2026-10-07"),
      used("u1", 20000, 2023, "2026-10-01", "2026-10-07", { vrm: "A" }), used("u2", 18000, 2023, "2026-10-04", "2026-10-07", { vrm: "B" }),
    ], BASIS, today);
    const cur = current(rows, today, 14);
    expect(Array.from(cur.keys()).sort()).toEqual(["car-a", "model:hyundai/ioniq-5"]);
    const cash = cur.get("car-a")!.cash!;
    expect(Object.keys(cash).sort()).toEqual(["carwow", "ncd"]);
    expect([cash.ncd.key, cash.ncd.headline, cash.ncd.age_days]).toEqual(["k", 34000, 0]);
    expect(cur.get("model:hyundai/ioniq-5")!.used!.cinch.key).toBe("u2");
    const best = bestByRoute({ ...cur.get("car-a")!, ...cur.get("model:hyundai/ioniq-5")! });
    expect([best.cash!.key, best.used!.key]).toEqual(["k", "u2"]);
  });
  it("trend reads the cheapest headline now, a window ago and how long it has held", () => {
    const rows = series(costAll([
      offer("k", "cash", "ncd", { ...CASH, vehicle_price: 35000 }, "2026-07-01", "2026-08-31"),
      offer("k", "cash", "ncd", CASH, "2026-09-01", "2026-10-07"),
      offer("k2", "cash", "carwow", { ...CASH, vehicle_price: 34500 }, "2026-09-20", "2026-10-07"),
    ], BASIS));
    const t = trend(rows, "2026-10-07")!;
    expect([t.now, t.then, t.delta, t.first_at, t.days_at_now]).toEqual([34000, 34000, 0, "2026-07-01", 36]);
    expect(t.spark[t.spark.length - 1]).toEqual(["2026-10-07", 34000]);
    expect(t.spark[0][1]).toBe(35000);
  });
  it("used stock counts cars once, per year, and names the residual year", () => {
    const st = usedStock(MODEL, [...STOCK, used("dup", 20500, 2023, "2026-10-01", "2026-10-07", { source: "carwow", mileage: 1 }), used("y24", 26000, 2024, "2026-10-01", "2026-10-07", { vrm: "Y24" })], "2026-10-07", BASIS);
    expect([st.count, st.sources, st.by_year["2023"], st.residual]).toEqual([4, { cinch: 4, carwow: 1 }, { n: 3, median: 21000, min: 20000 }, { value: 21000, n: 3, year: 2023 }]);
    expect(st.cheapest!.key).toBe("s0");
  });
  it("sources are a dimension of their own", () => {
    expect(subject(used("u", 1, 2023, "2026-10-01", "2026-10-01"))).toBe("model:hyundai/ioniq-5");
    expect(subject(offer("o", "cash", "ncd", CASH, "2026-10-01", "2026-10-01"))).toBe("car-a");
  });
});

describe("recompute", () => {
  it("a price confirmed last night is still today's: the latest state of a key holds until seen gone or stale", async () => {
    const { computeAll } = await import("./recompute");
    type S = import("../types").SnapshotSighting;
    type U = import("../types").SnapshotUsedSpan;
    const spans: S[] = [{ key: "k", car_id: "car-a", model: MODEL, route: "cash", source: "ncd", provider: "ncd", status: "live", seller: null, from: "2026-10-01", to: "2026-10-07", present: true, deal: { ...CASH } }];
    const usedSpans: U[] = [0, 1, 2].map((i) => ({ key: `u${i}`, source: "cinch", model: MODEL, car_id: null, year: 2023, price: 20000 + i * 1000, mileage: i + 1, vrm: `V${i}`, town: null, from: "2026-10-01", to: "2026-10-07", present: true }));
    const r = computeAll({ sightings: spans, usedSpans, cars: [{ id: "car-a", model_key: MODEL }], basis: BASIS, today: "2026-10-09", staleDays: 14 });
    const row = r.cars[0];
    expect(row.stock?.count).toBe(3);                                   // yesterday's stock is today's stock
    expect(row.routes.cash!.ncd.residual_source).toBe("used-market");   // and the evidence behind the cash route
    expect(row.routes.cash!.ncd.age_days).toBe(2);                      // but the age is real
    const stale = computeAll({ sightings: spans, usedSpans, cars: [{ id: "car-a", model_key: MODEL }], basis: BASIS, today: "2026-11-09", staleDays: 14 });
    expect([Object.keys(stale.cars[0].routes), stale.cars[0].stock]).toEqual([[], null]);   // a month on with no sighting, nothing is current (the trend remains)
    const marked = markCurrent([used("a", 1, 2023, "2026-10-01", "2026-10-07"), used("a", 2, 2023, "2026-10-08", "2026-10-08", { present: false })], "2026-10-09", 14);
    expect(marked.map((s) => !!s.current)).toEqual([false, false]);     // seen gone: the earlier state is not current
  });
});
