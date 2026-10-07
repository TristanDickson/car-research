import { describe, expect, it } from "vitest";

import { budgetGap, carCosts, routeCosts, trueCostOf } from "./costs";
import type { SnapshotCar } from "./types";

const point = (key: string, source: string, true_monthly: number, extra: object = {}) =>
  ({ key, headline: 1, true_monthly, source, source_name: source, age_days: 0, ...extra });

const car = {
  id: "c",
  deal_summary: {
    best_cash_price: 27445, best_cash_offer_id: "cash", best_cash_age_days: 1, best_cash_dealer: "D",
    best_pcp_monthly: 526.07, best_pcp_offer_id: "pcp", best_pcp_age_days: 2, best_pcp_total: 18938.52,
    best_pch_effective_monthly: 427, best_pch_offer_id: "pch", best_pch_age_days: 2, best_pch_total: 20497,
    routes: {
      cash: { carwow: point("cash-c", "Carwow", 560, { end_value: 19000 }), ncd: point("cash-n", "New Car Discount", 540) },
      pcp: { hyundai: point("pcp-h", "Hyundai UK", 430, { true_monthly_floor: 500 }) },
      used: { cinch: point("used-1", "cinch", 254, { seller: "Corby", end_value: 6381 }) },
    },
  },
} as unknown as SnapshotCar;

describe("carCosts", () => {
  it("reads the cheapest true cost across routes and sources off the snapshot", () => {
    const t = trueCostOf(car);
    expect(t?.route).toBe("used");
    expect(t?.source).toBe("cinch");
    expect(t?.dealer).toBe("Corby");
    expect(t?.monthly).toBe(254);
    expect(t?.endValue).toBe(6381);
    const by = routeCosts(car);
    expect(by.cash?.offerId).toBe("cash-n"); // the cheaper source wins the route
    expect(by.pcp?.floor).toBe(500);
  });
  it("carries the headline bests for the small print and counts the sources", () => {
    const k = carCosts(car);
    expect(k.monthlyRoute).toBe("pch");
    expect(k.monthly).toBe(427);
    expect(k.threeYear).toBe(20497);
    expect(k.cash?.price).toBe(27445);
    expect(k.sources).toBe(4);
  });
  it("reports nothing when the car has no current figure", () => {
    const k = carCosts({ id: "x", deal_summary: { routes: {} } } as unknown as SnapshotCar);
    expect(k.trueCost).toBeNull();
    expect(k.monthly).toBeNull();
    expect(k.cash).toBeNull();
    expect(k.sources).toBe(0);
  });
  it("budget gap is positive when over the ceiling", () => {
    expect(budgetGap(526.07, 400)).toBeCloseTo(126.07);
    expect(budgetGap(325, 400)).toBeLessThan(0);
    expect(budgetGap(null, 400)).toBeNull();
  });
});
