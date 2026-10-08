// One deal over the reader's horizon.
//
// Deals run for different lengths: a 25-month lease, a 37-month PCP, a 49-month
// PCP, a car bought outright. A true £ per month over each deal's own term is
// an equivalent-annual-cost figure (it assumes you would repeat a similar deal),
// which is one honest way to rank them. The other is to cost every deal over
// the same number of months, the reader's term, and say what has to happen at
// that month:
//
//   PCP longer than the horizon   settle the agreement early at the horizon
//                                 (the remaining payments and the balloon
//                                 discounted at the deal's rate) and sell the car
//   PCP shorter                   pay the balloon when it falls due, keep the car
//                                 to the horizon, sell it then
//   PCP the same length           buy at the GFV and sell: the equity, never below zero
//   lease of another length       its own-term figure (ending a lease early is
//                                 priced by the lender, not by arithmetic), flagged
//   cash, used                    the price now, sold at the horizon
//
// `pcpOverHorizon` and friends return the comparable figure and the assumption
// it rests on; `basis.compare_over` picks which figure ranks.
import { annuityFactor, expectedValue, monthlyRate, npv, pcpOutflows, pcpTerms, round2, trueMonthly, type Basis, type DealFields, type Flow, type Residuals } from "./dealMath";

/** What the figure assumes happens at the horizon. */
export type AtHorizon = "as_agreed" | "settle_early" | "balloon_then_keep" | "lease_ends" | "lease_runs_on" | "sold";

export const AT_HORIZON_LABEL: Record<AtHorizon, string> = {
  as_agreed: "runs the full term, then buy at the GFV and sell",
  settle_early: "settled early at the horizon (remaining payments and balloon at the deal's rate), car sold",
  balloon_then_keep: "balloon paid when due, car kept to the horizon and sold then",
  lease_ends: "lease ends before the horizon; per month of its own term",
  lease_runs_on: "lease runs past the horizon; per month of its own term (ending early costs more)",
  sold: "sold at the horizon at its expected value",
};

export interface HorizonCost {
  /** Months the figure is spread over. */
  horizon_months: number;
  at_horizon: AtHorizon;
  pv_cost: number;
  true_monthly: number | null;
  /** The same with the car worth only what a lender guaranteed. */
  pv_cost_floor: number | null;
  true_monthly_floor: number | null;
  expected_value_at_end: number | null;
  residual_source: string;
}

/** The deal's own rate for settling early: the stated APR, else what the payments imply. */
function settleRate(apr: number | null, impliedApr: number | null): number {
  return monthlyRate(apr ?? impliedApr ?? 0);
}

export function pcpOverHorizon(d: DealFields, horizon: number, basis: Basis, residuals: Residuals | null | undefined, floorGfv: number | null | undefined,
                               impliedApr: number | null): HorizonCost | null {
  const solved = pcpTerms(d);
  if ("skipped" in solved) return null;
  const t = solved.terms;
  const H = Math.max(1, Math.trunc(horizon));
  const list = (typeof d.list_price === "number" && d.list_price) || t.price;
  const [v, vSrc] = expectedValue(d.car_id, list, H, basis, residuals, t.gfv || floorGfv);
  let outflows: Flow[];
  let kind: AtHorizon;
  let inflow: number;
  let floorInflow: number;
  if (H === t.n + 1) {
    outflows = pcpOutflows(t);
    kind = "as_agreed";
    inflow = v != null ? Math.max(v - t.gfv, 0) : 0;
    floorInflow = 0;
  } else if (H < t.n + 1) {
    // Payments before the horizon as they fall; at the horizon the settlement:
    // the payments still owed and the balloon, discounted at the deal's rate.
    const r = settleRate(t.apr, impliedApr);
    outflows = [[0, t.dep + t.fees]];
    let settlement = 0;
    for (let k = 1; k <= t.n; k++) {
      const pay = k === 1 ? t.first : t.m;
      if (k < H) outflows.push([k, pay]);
      else settlement += pay / Math.pow(1 + r, k - H);
    }
    settlement += t.gfv / Math.pow(1 + r, t.n + 1 - H);
    outflows.push([H, settlement]);
    kind = "settle_early";
    inflow = v ?? 0;
    floorInflow = t.gfv;   // worth at least what the lender guaranteed for it later
  } else {
    outflows = [...pcpOutflows(t), [t.n + 1, t.gfv]];
    kind = "balloon_then_keep";
    inflow = v ?? 0;
    floorInflow = floorGfv ?? t.gfv;
  }
  const [pv, tm] = trueMonthly(outflows, [[H, inflow]], H, basis);
  const [pvF, tmF] = trueMonthly(outflows, [[H, floorInflow]], H, basis);
  return { horizon_months: H, at_horizon: kind, pv_cost: pv, true_monthly: tm, pv_cost_floor: pvF, true_monthly_floor: tmF,
           expected_value_at_end: v != null ? round2(v) : null, residual_source: vSrc };
}

/** A lease is its own-term figure whatever the horizon; the kind says how the lengths relate. */
export function pchOverHorizon(term: number, pvCost: number, trueMonthlyOwn: number | null, horizon: number): HorizonCost {
  const H = Math.trunc(horizon);
  return { horizon_months: term, at_horizon: term === H ? "as_agreed" : term < H ? "lease_ends" : "lease_runs_on",
           pv_cost: pvCost, true_monthly: trueMonthlyOwn, pv_cost_floor: pvCost, true_monthly_floor: trueMonthlyOwn,
           expected_value_at_end: null, residual_source: "none" };
}

/** What a PCP's true monthly would be over `months` at a flat annuity, for the table's small print. */
export function annuityOver(pv: number, months: number, basis: Basis): number {
  return round2(pv / annuityFactor(monthlyRate(basis.savings_rate_apr || 0), months));
}

/** Present value of flows at the reader's savings rate; exported for the tests. */
export function presentValue(flows: Flow[], basis: Basis): number {
  return npv(flows, monthlyRate(basis.savings_rate_apr || 0));
}
