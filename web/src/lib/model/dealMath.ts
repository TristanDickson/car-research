// PCP, PCH, cash and used on one footing: the one cost model, in the browser.
//
// A port of model/deal_math.py, which stays in the repo as the oracle: the
// fixture tests/fixtures/cost_cases.json is generated from it and both suites
// check their arithmetic against the same numbers. Conventions: payments at
// months 1..n, the balloon at month n+1 (a 37-month UK PCP has 36 payments);
// APR is an effective annual rate, so the monthly rate is (1+APR)^(1/12)-1.
//
// Every figure is pure: deals, a basis (the reader's term, savings rate and
// residual assumption) and the residual evidence in; numbers out. Nothing here
// reads the store or the clock.
import type { DealMetrics } from "../types";

export interface Basis {
  term_months: number;
  savings_rate_apr: number;
  residual_pct_of_list: number;
  residual_at_months: number;
  /** How deals of different lengths are ranked: over the reader's term, or each over its own. */
  compare_over?: "horizon" | "own";
}

export const DEFAULT_BASIS: Basis = { term_months: 37, savings_rate_apr: 0.04, residual_pct_of_list: 0.45, residual_at_months: 36, compare_over: "horizon" };

/** The reader's quoting basis, whatever else the requirements document carries beside it. */
export function basisOf(qb: Record<string, unknown> | null | undefined): Basis {
  const n = (k: keyof Basis, d: number) => (typeof qb?.[k] === "number" && Number.isFinite(qb[k] as number) ? (qb[k] as number) : d);
  return {
    term_months: Math.max(1, Math.round(n("term_months", DEFAULT_BASIS.term_months))),
    savings_rate_apr: n("savings_rate_apr", DEFAULT_BASIS.savings_rate_apr),
    residual_pct_of_list: n("residual_pct_of_list", DEFAULT_BASIS.residual_pct_of_list),
    residual_at_months: Math.max(1, n("residual_at_months", DEFAULT_BASIS.residual_at_months)),
    compare_over: qb?.compare_over === "own" ? "own" : "horizon",
  };
}

/** The price-bearing fields of an offer, as the sources print them. */
export interface DealFields {
  id?: string;
  car_id?: string | null;
  finance_type?: string;
  status?: string;
  list_price?: number | null;
  vehicle_price?: number | null;
  customer_deposit?: number | null;
  manufacturer_contribution?: number | null;
  fees_gbp?: number | null;
  apr?: number | null;
  amount_of_credit?: number | null;
  monthly_payment?: number | null;
  first_payment?: number | null;
  num_payments?: number | null;
  term_months?: number | null;
  gfv?: number | null;
  initial_rental?: number | null;
  num_rentals?: number | null;
  monthly_rental?: number | null;
  total_stated?: number | null;
  annual_mileage?: number | null;
  [k: string]: unknown;
}

export interface Residual {
  value: number;
  source?: string;
  n?: number;
}
export type Residuals = Record<string, Residual | undefined>;

/** A costed deal: model/deal_math's metrics dict, with the identity fields it carries. */
export interface Metrics extends DealMetrics {
  id?: string;
  car_id?: string | null;
  finance_type: string;
  status?: string;
  floor_value_at_end?: number | null;
  pv_cost_floor?: number | null;
}

export type Flow = [month: number, amount: number];

export const round2 = (x: number): number => Math.round(x * 100) / 100;
const round3 = (x: number): number => Math.round(x * 1000) / 1000;
const round4 = (x: number): number => Math.round(x * 10000) / 10000;

export const monthlyRate = (apr: number): number => Math.pow(1 + apr, 1 / 12) - 1;
export const annualise = (rm: number): number => Math.pow(1 + rm, 12) - 1;

export function npv(flows: Flow[], r: number): number {
  let s = 0;
  for (const [m, a] of flows) s += a / Math.pow(1 + r, m);
  return s;
}

/** Bisection on the monthly rate; flows positive = money to you. */
export function irrMonthly(flows: Flow[]): number | null {
  let lo = -0.5, hi = 0.5;
  let fLo = npv(flows, lo);
  const fHi = npv(flows, hi);
  if (fLo * fHi > 0) return null;
  for (let i = 0; i < 200; i++) {
    const mid = (lo + hi) / 2;
    const fMid = npv(flows, mid);
    if (fLo * fMid <= 0) hi = mid;
    else { lo = mid; fLo = fMid; }
  }
  return (lo + hi) / 2;
}

export function annuityFactor(r: number, n: number): number {
  return r === 0 ? n : (1 - Math.pow(1 + r, -n)) / r;
}

/** Expected market value after `months` on the basis's smooth curve: list × pct^(t/at). */
export function residualValue(listPrice: number | null | undefined, months: number, basis: Basis): number | null {
  if (!listPrice) return null;
  const pct = basis.residual_pct_of_list, at = basis.residual_at_months || 36;
  if (!pct) return null;
  return listPrice * Math.pow(pct, months / at);
}

/** A lender's guaranteed value grown at the savings rate: the floor they stood behind, plus the discount they applied. */
export function gfvGrown(gfv: number | null | undefined, months: number, basis: Basis): number | null {
  if (!gfv) return null;
  return gfv * Math.pow(1 + (basis.savings_rate_apr || 0), months / 12);
}

/** (value, source) at `months`: the used market's figure where there is one, else the best GFV grown, else the assumption. */
export function expectedValue(carId: string | null | undefined, listPrice: number | null | undefined, months: number, basis: Basis,
                              residuals?: Residuals | null, gfv?: number | null): [number | null, string] {
  const r = carId ? residuals?.[carId] : undefined;
  if (r && r.value) return [r.value, r.source || "used-market"];
  const grown = gfvGrown(gfv, months, basis);
  if (grown) return [grown, "gfv-grown"];
  const v = residualValue(listPrice, months, basis);
  return [v, v ? "assumption" : "none"];
}

/** [pv_cost, true_monthly]: outflows less inflows discounted at the savings rate, spread as an annuity over `horizon` months. */
export function trueMonthly(outflows: Flow[], inflows: Flow[], horizon: number | null | undefined, basis: Basis): [number, number | null] {
  const r = monthlyRate(basis.savings_rate_apr || 0);
  const pv = npv(outflows, r) - npv(inflows, r);
  if (!horizon || horizon <= 0) return [round2(pv), null];
  return [round2(pv), round2(pv / annuityFactor(r, horizon))];
}

export function solveMonthly(credit: number, apr: number, gfv: number, n: number): number {
  const r = monthlyRate(apr);
  const pvBalloon = gfv / Math.pow(1 + r, n + 1);
  return (credit - pvBalloon) / annuityFactor(r, n);
}

export function pvOfPayments(monthly: number, apr: number, gfv: number, n: number, first?: number | null): number {
  const r = monthlyRate(apr);
  const f = first ?? monthly;
  let pv = f / (1 + r);
  for (let k = 2; k <= n; k++) pv += monthly / Math.pow(1 + r, k);
  return pv + gfv / Math.pow(1 + r, n + 1);
}

function paymentFlows(n: number, m: number, first: number, gfv: number): Flow[] {
  const flows: Flow[] = [[1, -first]];
  for (let k = 2; k <= n; k++) flows.push([k, -m]);
  flows.push([n + 1, -gfv]);
  return flows;
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** The resolved shape of a PCP: what the source printed, with the gaps solved. */
export interface PcpTerms {
  n: number;
  m: number;
  first: number;
  dep: number;
  contrib: number;
  fees: number;
  gfv: number;
  apr: number | null;
  price: number;
  credit: number;
  derived: string[];
}

/** Solve a PCP's missing figures; null (with why) when it cannot be costed. */
export function pcpTerms(d: DealFields): { terms: PcpTerms } | { skipped: string } {
  const n = num(d.num_payments);
  const gfv = num(d.gfv) ?? 0;
  const dep = num(d.customer_deposit) ?? 0;
  const contrib = num(d.manufacturer_contribution) ?? 0;
  const fees = num(d.fees_gbp) ?? 0;
  const apr = num(d.apr);
  let price = num(d.vehicle_price);
  let credit = num(d.amount_of_credit);
  if (credit == null && price != null) credit = price - dep - contrib;
  let m = num(d.monthly_payment);
  const derived: string[] = [];
  if (m == null) {
    if (credit == null || apr == null || n == null) return { skipped: "no monthly and not enough to solve it" };
    m = solveMonthly(credit, apr, gfv, n);
    derived.push("monthly_payment");
  }
  if (n == null) return { skipped: "no number of payments" };
  const first = num(d.first_payment) ?? m;
  if (credit == null) {
    if (apr == null) return { skipped: "no credit and no apr to back-solve" };
    credit = pvOfPayments(m, apr, gfv, n, first);
    derived.push("amount_of_credit");
    if (price == null) {
      price = credit + dep + contrib;
      derived.push("vehicle_price");
    }
  }
  if (price == null) return { skipped: "no price" };
  return { terms: { n, m, first, dep, contrib, fees, gfv, apr, price, credit, derived } };
}

/** The payments as outflows: deposit and fees now, the first payment at month 1, the rest to month n. */
export function pcpOutflows(t: PcpTerms): Flow[] {
  const out: Flow[] = [[0, t.dep + t.fees], [1, t.first]];
  for (let k = 2; k <= t.n; k++) out.push([k, t.m]);
  return out;
}

export function pcpMetrics(d: DealFields, bestCash: DealFields | null | undefined, basis: Basis = DEFAULT_BASIS,
                           residuals?: Residuals | null, floorGfv?: number | null): Metrics {
  const out: Metrics = { id: d.id, car_id: d.car_id ?? null, finance_type: "pcp", status: d.status };
  const solved = pcpTerms(d);
  if ("skipped" in solved) return { ...out, skipped: solved.skipped };
  const t = solved.terms;
  const { n, m, first, dep, contrib, fees, gfv, apr, price, credit } = t;

  const paidHandBack = dep + first + m * (n - 1) + fees;
  const paidBought = paidHandBack + gfv;
  const costOfCredit = paidBought - dep - credit;
  const netVsOwnCash = paidBought - price;
  const r = irrMonthly([[0, credit], ...paymentFlows(n, m, first, gfv)]);
  const impliedApr = r != null ? annualise(r) : null;
  const zeroPctMonthly = (credit - gfv) / n;
  const term = num(d.term_months) ?? n + 1;
  const list = num(d.list_price);

  Object.assign(out, {
    list_price: list,
    vehicle_price: round2(price),
    manufacturer_contribution: contrib,
    customer_deposit: dep,
    amount_of_credit: round2(credit),
    num_payments: n,
    term_months: term,
    monthly_payment: round2(m),
    apr_stated: apr,
    apr_implied: impliedApr != null ? round4(impliedApr) : null,
    gfv,
    gfv_pct_of_list: list ? round3(gfv / list) : null,
    gfv_pct_of_price: price ? round3(gfv / price) : null,
    paid_if_handed_back: round2(paidHandBack),
    paid_if_bought: round2(paidBought),
    cost_of_credit: round2(costOfCredit),
    finance_vs_own_cash_price: round2(netVsOwnCash),
    effective_monthly_hand_back: round2(paidHandBack / term),
    monthly_at_0pct_same_gfv: round2(zeroPctMonthly),
    interest_per_month: round2(m - zeroPctMonthly),
    derived_fields: t.derived,
  });
  // True monthly: deposit and fees now, the payments, and at the end the option
  // to buy at the GFV and sell at the expected value (worth max(V - GFV, 0)).
  const outflows = pcpOutflows(t);
  const [v, vSrc] = expectedValue(d.car_id, list || price, n + 1, basis, residuals, gfv || floorGfv);
  const equity = v != null ? Math.max(v - gfv, 0) : 0;
  const [pv, tm] = trueMonthly(outflows, [[n + 1, equity]], n + 1, basis);
  const [pvFloor, tmFloor] = trueMonthly(outflows, [], n + 1, basis);
  Object.assign(out, {
    expected_value_at_end: v != null ? round2(v) : null, residual_source: vSrc,
    expected_equity: round2(equity),
    pv_cost: pv, true_monthly: tm,
    pv_cost_floor: pvFloor, true_monthly_floor: tmFloor,
    horizon_months: n + 1,
  });
  if (bestCash && num(bestCash.vehicle_price) != null) {
    const bc = bestCash.vehicle_price as number;
    const r2 = irrMonthly([[0, bc - dep], ...paymentFlows(n, m, first, gfv)]);
    Object.assign(out, {
      best_cash_price: bc,
      best_cash_deal_id: bestCash.id,
      acquisition_penalty_vs_cash: round2(price - contrib - bc),
      funding_premium_vs_cash: round2(paidBought - bc),
      effective_rate_vs_cash: r2 != null ? round4(annualise(r2)) : null,
    });
  }
  return out;
}

export function pchMetrics(d: DealFields, basis: Basis = DEFAULT_BASIS): Metrics {
  const out: Metrics = { id: d.id, car_id: d.car_id ?? null, finance_type: "pch", status: d.status };
  const term = num(d.term_months), n = num(d.num_rentals), m = num(d.monthly_rental);
  const init = num(d.initial_rental) ?? 0;
  const fees = num(d.fees_gbp) ?? 0;
  if (term == null || n == null || m == null) return { ...out, skipped: "term or rental profile missing" };
  const total = num(d.total_stated) ?? init + n * m + fees;
  Object.assign(out, {
    term_months: term, initial_rental: init, monthly_rental: m, num_rentals: n, fees,
    total_cost: round2(total), effective_monthly: round2(total / term), annual_mileage: num(d.annual_mileage),
  });
  // True monthly: initial rental and fees now, then the rentals; nothing comes back.
  const [pv, tm] = trueMonthly(pchOutflows(init, fees, n, m), [], term, basis);
  Object.assign(out, { pv_cost: pv, true_monthly: tm, pv_cost_floor: pv, true_monthly_floor: tm, horizon_months: term });
  return out;
}

export function pchOutflows(init: number, fees: number, n: number, m: number): Flow[] {
  const out: Flow[] = [[0, init + fees]];
  for (let k = 1; k <= n; k++) out.push([k, m]);
  return out;
}

export function cashMetrics(d: DealFields, basis: Basis = DEFAULT_BASIS, floorGfv?: number | null, residuals?: Residuals | null): Metrics {
  const price = num(d.vehicle_price);
  const list = num(d.list_price);
  const out: Metrics = {
    id: d.id, car_id: d.car_id ?? null, finance_type: "cash", status: d.status,
    list_price: list, vehicle_price: price ?? undefined,
    discount_vs_list: list && price != null ? round2(list - price) : null,
  };
  if (price == null) return { ...out, skipped: "no price" };
  // True monthly: the price now (money that would otherwise earn the savings
  // rate), the car sold at its expected value at the end of the standard term.
  const horizon = Math.trunc(basis.term_months || 37);
  const [v, vSrc] = expectedValue(d.car_id, list || price, horizon, basis, residuals, floorGfv);
  const [pv, tm] = trueMonthly([[0, price]], [[horizon, v ?? 0]], horizon, basis);
  Object.assign(out, { expected_value_at_end: v != null ? round2(v) : null, residual_source: vSrc, pv_cost: pv, true_monthly: tm, horizon_months: horizon });
  if (floorGfv) {
    const [pvF, tmF] = trueMonthly([[0, price]], [[horizon, floorGfv]], horizon, basis);
    Object.assign(out, { floor_value_at_end: floorGfv, pv_cost_floor: pvF, true_monthly_floor: tmF });
  }
  return out;
}

/** Every deal costed: the cheapest cash price per car is the benchmark, the highest GFV per car the floor. */
export function compute(deals: DealFields[], basis: Partial<Basis> | null = null, residuals?: Residuals | null): Metrics[] {
  const b: Basis = { ...DEFAULT_BASIS, ...(basis ?? {}) };
  const bestCash = new Map<string, DealFields>();
  for (const d of deals) {
    if (d.finance_type !== "cash" || !num(d.vehicle_price)) continue;
    const cur = bestCash.get(d.car_id ?? "");
    if (!cur || (d.vehicle_price as number) < (cur.vehicle_price as number)) bestCash.set(d.car_id ?? "", d);
  }
  const floorGfv = new Map<string, number>();
  for (const d of deals) {
    if (d.finance_type === "pcp" && num(d.gfv)) floorGfv.set(d.car_id ?? "", Math.max(floorGfv.get(d.car_id ?? "") ?? 0, d.gfv as number));
  }
  return deals.map((d) => {
    const car = d.car_id ?? "";
    switch (d.finance_type) {
      case "pcp": return pcpMetrics(d, bestCash.get(car), b, residuals, floorGfv.get(car));
      case "pch": return pchMetrics(d, b);
      case "cash": return cashMetrics(d, b, floorGfv.get(car), residuals);
      default: return { id: d.id, car_id: d.car_id ?? null, finance_type: d.finance_type ?? "?", status: d.status,
                        apr: num(d.apr), manufacturer_contribution: num(d.manufacturer_contribution) ?? undefined, skipped: "campaign terms only" } as Metrics;
    }
  });
}

export interface UsedRoute {
  finance_type: "used";
  vehicle_price: number;
  age_years: number | null;
  expected_value_at_end: number;
  residual_source: string;
  pv_cost: number;
  true_monthly: number | null;
  horizon_months: number;
}

/** The buy-used route for one listing: the price now, the car sold after the term at `valueAtEnd` (the market's figure where there is one) else on the flat curve from here. */
export function usedRoute(price: number, ageYears: number | null, basis: Basis, valueAtEnd?: number | null): UsedRoute {
  const horizon = Math.trunc(basis.term_months || 37);
  let v = valueAtEnd ?? 0;
  let src = "used-market";
  if (!v) {
    const pct = basis.residual_pct_of_list, at = basis.residual_at_months || 36;
    v = pct ? price * Math.pow(pct, horizon / at) : 0;
    src = "assumption";
  }
  const [pv, tm] = trueMonthly([[0, price]], [[horizon, v]], horizon, basis);
  return { finance_type: "used", vehicle_price: price, age_years: ageYears, expected_value_at_end: round2(v), residual_source: src, pv_cost: pv, true_monthly: tm, horizon_months: horizon };
}
