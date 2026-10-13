import { describe, expect, it } from "vitest";

import { breakEvens, MAX_RATE } from "./breakeven";
import { DEFAULT_BASIS, type Basis, type DealFields } from "./dealMath";
import { cost, floorGfvAt, MIN_EVIDENCE, residualAt, trimScale, type Sighting } from "./sightings";

const BASIS: Basis = { ...DEFAULT_BASIS, term_months: 37, savings_rate_apr: 0.04 };
const MODEL = "hyundai/kona-electric";
const TODAY = "2026-10-07";

const offer = (key: string, route: "cash" | "pcp" | "pch", deal: DealFields): Sighting =>
  ({ key, route, source: "x", model: MODEL, car_id: "car-a", from: "2026-10-01", to: TODAY, present: true, current: true, deal, seller: null });
const used = (key: string, price: number, year: number, i: number): Sighting =>
  ({ key, route: "used", source: "cinch", model: MODEL, car_id: null, from: "2026-10-01", to: TODAY, present: true, deal: { price, year, mileage: 30000 + i, vrm: `V${key}` }, seller: null });

const STOCK = [15000, 16000, 17000].map((p, i) => used(`s${i}`, p, 2023, i));
const CASH = offer("cash", "cash", { list_price: 40000, vehicle_price: 27000 });
const LEASE = offer("lease", "pch", { initial_rental: 3500, monthly_rental: 290, num_rentals: 47, term_months: 48 });
const PCP = offer("pcp", "pcp", { list_price: 40000, vehicle_price: 27000, customer_deposit: 0, manufacturer_contribution: 0, apr: 0.079, num_payments: 36, term_months: 37, gfv: 13000,
                                   monthly_payment: Math.round(((27000 - 13000 / Math.pow(1.079, 37 / 12)) / ((1 - Math.pow(Math.pow(1.079, 1 / 12), -36)) / (Math.pow(1.079, 1 / 12) - 1))) * 100) / 100 });

const residual = residualAt(STOCK);
const floor = floorGfvAt([PCP]);
const monthly = (s: Sighting, basis: Basis, res = residual) => cost(s, basis, res, floor, TODAY)!.true_monthly!;

describe("trim scale", () => {
  it("is a car's list price over its model's median", () => {
    const t = trimScale([{ id: "a", model_key: MODEL, list_price_gbp: 30000 }, { id: "b", model_key: MODEL, list_price_gbp: 40000 },
                         { id: "c", model_key: MODEL, list_price_gbp: 50000 }, { id: "d", model_key: MODEL, list_price_gbp: null }]);
    expect([t("a"), t("b"), t("c"), t("d"), t("unknown"), t(null)]).toEqual([0.75, 1, 1.25, 1, 1, 1]);
  });
  it("counts each trim once, and only trims on sale, in the model's typical price", () => {
    const t = trimScale([...["a1", "a2", "a3"].map((id) => ({ id, model_key: MODEL, used_key: "base", list_price_gbp: 30000 })),
                         { id: "b", model_key: MODEL, used_key: "mid", list_price_gbp: 40000 }, { id: "c", model_key: MODEL, used_key: "top", list_price_gbp: 50000 },
                         { id: "old", model_key: MODEL, used_key: "gone", list_price_gbp: 99000, on_sale: false }]);
    expect([t("a1"), t("b"), t("c"), t("old")]).toEqual([0.75, 1, 1.25, 99000 / 40000]);   // three listings of the base trim are one trim
  });
  it("scales the model's used median to the trim", () => {
    const t = trimScale([{ id: "car-a", model_key: MODEL, list_price_gbp: 50000 }, { id: "b", model_key: MODEL, list_price_gbp: 40000 }, { id: "c", model_key: MODEL, list_price_gbp: 30000 }]);
    expect(cost(CASH, BASIS, residual, floor, TODAY)!.end_value).toBe(16000);
    expect(cost(CASH, BASIS, residual, floor, TODAY, t)!.end_value).toBe(20000);   // 1.25 × the 2023 median
  });
});

describe("break-evens", () => {
  const [pcp, lease] = breakEvens(CASH, { pcp: PCP, pch: LEASE }, BASIS, residual, floor, TODAY);
  it("finds the savings rate at which finance and cash cost the same", () => {
    expect(lease.rate).not.toBeNull();
    const at = { ...BASIS, savings_rate_apr: lease.rate! };
    expect(Math.abs(monthly(CASH, at) - monthly(LEASE, at))).toBeLessThan(0.05);
    expect(lease.cheaper_below).toBe("cash");
    expect(monthly(CASH, BASIS) < monthly(LEASE, BASIS)).toBe(BASIS.savings_rate_apr < lease.rate!);
  });
  it("finds what the car must sell for at the end for them to cost the same", () => {
    expect(lease.resale).not.toBeNull();
    expect(Math.abs(monthly(CASH, BASIS, () => [lease.resale!, MIN_EVIDENCE]) - monthly(LEASE, BASIS))).toBeLessThan(0.01);
    expect(lease.cheaper_above).toBe("cash");
    expect(lease.expected).toBe(16000);
  });
  it("a PCP with nothing from the maker costs what cash does when savings earn its APR", () => {
    expect([pcp.route, pcp.key, pcp.cash_key, pcp.cheaper_below]).toEqual(["pcp", "pcp", "cash", "cash"]);
    expect(pcp.rate!).toBeCloseTo(0.079, 4);
  });
  it("a PCP's equity comes back on both routes alike above its GFV, so the resale break-even lies below it", () => {
    const gap = (v: number) => monthly(CASH, BASIS, () => [v, MIN_EVIDENCE]) - monthly(PCP, BASIS, () => [v, MIN_EVIDENCE]);
    expect(gap(16000)).toBeCloseTo(gap(20000), 6);
    expect(pcp.resale!).toBeLessThan(13000);
    expect(Math.abs(gap(pcp.resale!))).toBeLessThan(0.01);
    expect(pcp.cheaper_above).toBe("cash");
  });
  it("says which is cheaper at every rate when they never cross", () => {
    const dear = offer("dear", "pch", { initial_rental: 9000, monthly_rental: 900, num_rentals: 47, term_months: 48 });
    const [b] = breakEvens(CASH, { pch: dear }, BASIS, residual, floor, TODAY);
    expect([b.rate, b.cheaper_below]).toEqual([null, "cash"]);
    expect(monthly(CASH, { ...BASIS, savings_rate_apr: MAX_RATE })).toBeLessThan(monthly(dear, { ...BASIS, savings_rate_apr: MAX_RATE }));
  });
  it("needs a cash price", () => {
    expect(breakEvens(null, { pch: LEASE }, BASIS, residual, floor, TODAY)).toEqual([]);
  });
});
