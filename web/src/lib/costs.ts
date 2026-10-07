// What a car costs, read off the snapshot. The cost model lives in the pipeline
// (model/sightings.py costs every sighting; deal_summary carries the cheapest
// current figure per route and source as of the snapshot date, and the
// headline bests for the small print). Nothing here is computed from offers,
// so no page needs the offers table to show a price.
import type { Route, RouteSource, SnapshotCar } from "./types";

export interface RouteCost {
  offerId: string | null;
  dealer: string | null;
  /** Monthly cash flow: PCP monthly at £0 down, or PCH total spread over the term. */
  monthly: number;
  /** Everything paid over the agreement if the car is handed back. */
  threeYear: number | null;
  ageDays: number | null;
}

export interface CashCost {
  offerId: string | null;
  dealer: string | null;
  price: number;
  ageDays: number | null;
}

export interface TrueCost {
  route: Route;
  offerId: string;
  dealer: string | null;
  source: string;
  /** Present cost at the savings rate, expected end value credited back, spread over the agreement. */
  monthly: number;
  /** The same with the car worth only its GFV at the end. */
  floor: number | null;
  /** What the source printed: a price, or a monthly. */
  headline: number | null;
  /** What the car is expected to be worth at the end of the term under this route. */
  endValue: number | null;
  ageDays: number | null;
}

export interface CarCosts {
  /** Cheapest current sighting on one footing across cash, PCP, lease and used (model/sightings.py). */
  trueCost: TrueCost | null;
  /** Every route the car has a current figure for, cheapest source first. */
  byRoute: Partial<Record<Route, TrueCost>>;
  /** How many distinct sources price this car today, across routes. */
  sources: number;
  /** Cheapest current monthly route, if any (as printed). */
  monthly: number | null;
  monthlyRoute: "pcp" | "pch" | null;
  threeYear: number | null;
  pcp: RouteCost | null;
  pch: RouteCost | null;
  cash: CashCost | null;
}

function toTrueCost(route: Route, p: RouteSource): TrueCost | null {
  if (p.true_monthly == null) return null;
  return { route, offerId: p.key, dealer: p.seller ?? null, source: p.source_name, monthly: p.true_monthly,
           floor: p.true_monthly_floor ?? null, headline: p.headline, endValue: p.end_value ?? null, ageDays: p.age_days ?? null };
}

/** The cheapest current sighting per route, from the snapshot. */
export function routeCosts(car: SnapshotCar | undefined): Partial<Record<Route, TrueCost>> {
  const out: Partial<Record<Route, TrueCost>> = {};
  for (const [route, bySource] of Object.entries(car?.deal_summary?.routes ?? {})) {
    for (const p of Object.values(bySource ?? {})) {
      const t = toTrueCost(route as Route, p);
      if (t && (!out[route as Route] || t.monthly < out[route as Route]!.monthly)) out[route as Route] = t;
    }
  }
  return out;
}

/** The cheapest current sighting across every route and source. */
export function trueCostOf(car: SnapshotCar | undefined): TrueCost | null {
  let best: TrueCost | null = null;
  for (const t of Object.values(routeCosts(car))) if (!best || t.monthly < best.monthly) best = t;
  return best;
}

export function carCosts(car: SnapshotCar): CarCosts {
  const d = car.deal_summary;
  const byRoute = routeCosts(car);
  const sources = new Set<string>();
  for (const bySource of Object.values(d.routes ?? {})) for (const s of Object.keys(bySource ?? {})) sources.add(s);

  const pcp: RouteCost | null = d.best_pcp_monthly != null
    ? { offerId: d.best_pcp_offer_id, dealer: d.best_pcp_dealer ?? null, monthly: d.best_pcp_monthly, threeYear: d.best_pcp_total ?? null, ageDays: d.best_pcp_age_days }
    : null;
  const pch: RouteCost | null = d.best_pch_effective_monthly != null
    ? { offerId: d.best_pch_offer_id, dealer: d.best_pch_dealer ?? null, monthly: d.best_pch_effective_monthly, threeYear: d.best_pch_total ?? null, ageDays: d.best_pch_age_days }
    : null;
  const cash: CashCost | null = d.best_cash_price != null
    ? { offerId: d.best_cash_offer_id, dealer: d.best_cash_dealer ?? null, price: d.best_cash_price, ageDays: d.best_cash_age_days }
    : null;

  const candidates: { route: "pcp" | "pch"; r: RouteCost }[] = [];
  if (pcp) candidates.push({ route: "pcp", r: pcp });
  if (pch) candidates.push({ route: "pch", r: pch });
  candidates.sort((a, b) => a.r.monthly - b.r.monthly);
  const best = candidates[0] ?? null;

  return {
    trueCost: trueCostOf(car),
    byRoute,
    sources: sources.size,
    monthly: best ? best.r.monthly : null,
    monthlyRoute: best ? best.route : null,
    threeYear: best ? best.r.threeYear : null,
    pcp,
    pch,
    cash,
  };
}

/** Positive = over the ceiling by this much per month; 0 or negative = within budget. */
export function budgetGap(monthly: number | null, ceiling: number | null | undefined): number | null {
  if (monthly == null || ceiling == null) return null;
  return monthly - ceiling;
}

export const IONIQ5_WIDTH_MM = 1890;

export const ROUTE_LABEL: Record<Route, string> = { pcp: "PCP", pch: "lease", cash: "buy outright", used: "buy used" };
export const ROUTE_SHORT: Record<Route, string> = { pcp: "PCP", pch: "Lease", cash: "Cash", used: "Used" };
export const ROUTES: Route[] = ["cash", "pcp", "pch", "used"];
