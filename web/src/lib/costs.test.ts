import { describe, expect, it } from "vitest";

import { budgetGap, carCosts, trueCostOf } from "./costs";
import type { SnapshotCar, SnapshotOffer } from "./types";

const now = new Date("2026-10-07T00:00:00Z");
const fresh = { state: "live" as const, stale: false, age_days: 2, first_seen_at: "2026-10-05", last_seen_at: "2026-10-05", last_checked_at: "2026-10-05", observations: 1, present: true, history: [] };
const offer = (over: Partial<SnapshotOffer>): SnapshotOffer => ({
  id: "x", car_id: "c", provider: "t", captured_at: "2026-10-05", finance_type: "pcp", status: "live", metrics: {}, freshness: fresh, ...over,
});

describe("carCosts", () => {
  it("picks the cheapest current monthly route and carries its three-year total", () => {
    const offers = [
      offer({ id: "pcp", dealer: "A", customer_deposit: 0, metrics: { monthly_payment: 526.07, paid_if_handed_back: 18938.52, term_months: 37, gfv: 14039.28 } }),
      offer({ id: "pcp-dep", dealer: "B", customer_deposit: 7999, metrics: { monthly_payment: 467.98, paid_if_handed_back: 24846, gfv: 18661.5 } }),
      offer({ id: "pch", finance_type: "pch", dealer: "C", metrics: { effective_monthly: 427, total_cost: 20497, term_months: 48 } }),
      offer({ id: "cash", finance_type: "cash", dealer: "D", vehicle_price: 27445, metrics: { vehicle_price: 27445 } }),
      offer({ id: "old", finance_type: "cash", dealer: "E", vehicle_price: 20000, metrics: { vehicle_price: 20000 }, freshness: { ...fresh, last_seen_at: "2026-08-01" } }),
      offer({ id: "gone", finance_type: "cash", dealer: "F", vehicle_price: 19000, metrics: { vehicle_price: 19000 }, freshness: { ...fresh, state: "gone" } }),
    ];
    const k = carCosts(offers, 14, now);
    expect(k.monthlyRoute).toBe("pch");
    expect(k.monthly).toBe(427);
    expect(k.threeYear).toBe(20497);
    expect(k.pcp?.offerId).toBe("pcp"); // the £7,999-down one is not a £0-deposit route
    expect(k.cash?.price).toBe(27445); // stale and gone cash offers ignored
    expect(k.trueCost).toBeNull(); // the true cost is the pipeline's, not derived here
  });
  it("reads the cheapest true cost across routes and sources off the snapshot", () => {
    const point = (key: string, source: string, true_monthly: number, extra: object = {}) =>
      ({ key, from: "2026-10-05", to: "2026-10-07", headline: 1, true_monthly, source, source_name: source, age_days: 0, ...extra });
    const car = { id: "c", deal_summary: { routes: {
      cash: { carwow: point("cash-c", "Carwow", 560), ncd: point("cash-n", "New Car Discount", 540) },
      pcp: { hyundai: point("pcp-h", "Hyundai UK", 430, { true_monthly_floor: 500 }) },
      used: { cinch: point("used-1", "cinch", 254, { seller: "Corby" }) },
    } } } as unknown as SnapshotCar;
    const t = trueCostOf(car);
    expect(t?.route).toBe("used");
    expect(t?.source).toBe("cinch");
    expect(t?.dealer).toBe("Corby");
    expect(t?.monthly).toBe(254);
    expect(carCosts([], 14, now, car).routes.cash?.ncd.true_monthly).toBe(540);
  });
  it("reports nothing when there are no current offers", () => {
    const k = carCosts([], 14, now);
    expect(k.monthly).toBeNull();
    expect(k.cash).toBeNull();
  });
  it("budget gap is positive when over the ceiling", () => {
    expect(budgetGap(526.07, 400)).toBeCloseTo(126.07);
    expect(budgetGap(325, 400)).toBeLessThan(0);
    expect(budgetGap(null, 400)).toBeNull();
  });
});
