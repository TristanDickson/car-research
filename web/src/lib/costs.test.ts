import { describe, expect, it } from "vitest";

import { budgetGap, carCosts } from "./costs";
import type { CarCostRow } from "./model/recompute";
import type { CurrentPoint } from "./model/sightings";
import type { SnapshotCar } from "./types";

const point = (key: string, source: string, true_monthly: number, extra: Partial<CurrentPoint> = {}): CurrentPoint =>
  ({ key, from: "2026-10-01", to: "2026-10-07", seller: null, headline: 1, true_monthly, true_monthly_floor: null, residual_source: null, end_value: null,
     horizon_months: 37, at_horizon: "as_agreed", own_true_monthly: true_monthly, own_horizon_months: 37, terms: { paid: null }, source, age_days: 0, ...extra });

const car = { id: "c" } as unknown as SnapshotCar;
const row: CarCostRow = {
  id: "c", model: "hyundai/kona-electric",
  routes: {
    cash: { carwow: point("cash-c", "carwow", 560, { headline: 27445, end_value: 19000, terms: { paid: 27445, price: 27445 } }), ncd: point("cash-n", "ncd", 540, { headline: 26966, terms: { paid: 26966, price: 26966 } }) },
    pcp: { hyundai: point("pcp-h", "hyundai", 430, { headline: 526.07, true_monthly_floor: 500, terms: { paid: 18938.52, monthly: 526.07, payments: 36 } }) },
    pch: { leaseloco: point("pch-l", "leaseloco", 445, { headline: 427, horizon_months: 36, at_horizon: "lease_ends", terms: { paid: 20497, monthly: 427, rentals: 35 } }) },
    used: { cinch: point("used-1", "cinch", 254, { seller: "Corby", end_value: 6381, at_horizon: "sold" }) },
  },
  best: {},
  trend: { now: 26966, then: 27445, delta: -479, window_days: 30, first_at: "2026-09-01", days_at_now: 3, spark: [] },
  stock: null,
};

describe("carCosts", () => {
  it("reads the cheapest comparable figure across routes and sources off the stored row", () => {
    const k = carCosts(car, row, { ncd: "New Car Discount" });
    expect(k.trueCost?.route).toBe("used");
    expect(k.trueCost?.source).toBe("cinch");
    expect(k.trueCost?.dealer).toBe("Corby");
    expect(k.trueCost?.monthly).toBe(254);
    expect(k.trueCost?.endValue).toBe(6381);
    expect(k.byRoute.cash?.offerId).toBe("cash-n");   // the cheaper source wins the route
    expect(k.byRoute.cash?.sourceName).toBe("New Car Discount");
    expect(k.byRoute.pcp?.floor).toBe(500);
    expect([k.byRoute.pch?.horizonMonths, k.byRoute.pch?.atHorizon]).toEqual([36, "lease_ends"]);
  });
  it("carries the figures as printed for the small print and counts the sources", () => {
    const k = carCosts(car, row);
    expect(k.monthlyRoute).toBe("pch");
    expect(k.monthly).toBe(427);
    expect(k.threeYear).toBe(20497);
    expect(k.cash?.price).toBe(26966);
    expect(k.sources).toBe(5);
    expect(k.trend?.delta).toBe(-479);
  });
  it("reports nothing when the car has no row", () => {
    const k = carCosts(car, undefined);
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
