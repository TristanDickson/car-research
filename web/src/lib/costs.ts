// What a car costs, read off the stored results of the one cost model
// (lib/model, run by lib/db.ts under the reader's basis). Nothing here is
// computed from offers at render time; a page needs a car and its cost row.
import type { AtHorizon } from "./model/horizon";
import type { CarCostRow } from "./model/recompute";
import type { CurrentPoint, PrintedTerms, Trend, UsedStock } from "./model/sightings";
import type { Route, SnapshotCar } from "./types";

export interface TrueCost {
  route: Route;
  offerId: string;
  dealer: string | null;
  /** The source id, and its display name where data.json names it. */
  source: string;
  sourceName: string;
  /** The comparable figure: present cost at the savings rate, expected end value credited back, spread over the months. */
  monthly: number;
  /** The same with the car worth only its GFV at the end. */
  floor: number | null;
  /** What the source printed: a price, or a monthly. */
  headline: number | null;
  /** What the car is expected to be worth at the end under this route. */
  endValue: number | null;
  residualSource: string | null;
  ageDays: number | null;
  /** The months the figure is spread over and what it assumes happens at the end. */
  horizonMonths: number;
  atHorizon: AtHorizon;
  /** The deal over its own term. */
  ownMonthly: number | null;
  ownHorizonMonths: number;
  terms: PrintedTerms;
}

export interface CarCosts {
  /** Cheapest current sighting on one footing across cash, PCP, lease and used. */
  trueCost: TrueCost | null;
  /** Every route the car has a current figure for. */
  byRoute: Partial<Record<Route, TrueCost>>;
  /** How many distinct sources price this car today, across routes. */
  sources: number;
  /** Cheapest current monthly as printed, if any (PCP or lease). */
  monthly: number | null;
  monthlyRoute: "pcp" | "pch" | null;
  /** Everything paid over that deal if handed back. */
  threeYear: number | null;
  cash: { offerId: string; dealer: string | null; price: number; ageDays: number | null } | null;
  /** Movement of the best cash price. */
  trend: Trend | null;
  /** The model's used stock: the evidence behind the end values. */
  stock: UsedStock | null;
}

function toTrueCost(route: Route, p: CurrentPoint, names: Record<string, string>): TrueCost | null {
  if (p.true_monthly == null) return null;
  return { route, offerId: p.key, dealer: p.seller ?? null, source: p.source, sourceName: names[p.source] ?? p.source, monthly: p.true_monthly,
           floor: p.true_monthly_floor ?? null, headline: p.headline, endValue: p.end_value ?? null, residualSource: p.residual_source ?? null,
           ageDays: p.age_days ?? null, horizonMonths: p.horizon_months, atHorizon: p.at_horizon, ownMonthly: p.own_true_monthly,
           ownHorizonMonths: p.own_horizon_months, terms: p.terms };
}

export const NO_COSTS: CarCosts = { trueCost: null, byRoute: {}, sources: 0, monthly: null, monthlyRoute: null, threeYear: null, cash: null, trend: null, stock: null };

/** The car's costs from its stored row; `names` maps source ids to display names (data.json). */
export function carCosts(car: SnapshotCar, row: CarCostRow | null | undefined, names: Record<string, string> = {}): CarCosts {
  if (!row) return NO_COSTS;
  const byRoute: Partial<Record<Route, TrueCost>> = {};
  const sources = new Set<string>();
  for (const [route, bySource] of Object.entries(row.routes) as [Route, Record<string, CurrentPoint>][]) {
    for (const [src, p] of Object.entries(bySource ?? {})) {
      sources.add(src);
      const t = toTrueCost(route, p, names);
      if (t && (!byRoute[route] || t.monthly < byRoute[route]!.monthly)) byRoute[route] = t;
    }
  }
  let trueCost: TrueCost | null = null;
  for (const t of Object.values(byRoute)) if (!trueCost || t.monthly < trueCost.monthly) trueCost = t;

  // As printed: the cheapest monthly on offer and the cheapest cash price, for the small print.
  let monthly: TrueCost | null = null;
  for (const route of ["pcp", "pch"] as const) {
    for (const p of Object.values(row.routes[route] ?? {})) {
      const t = toTrueCost(route, p, names);
      if (t?.headline != null && (!monthly || t.headline < monthly.headline!)) monthly = t;
    }
  }
  let cash: TrueCost | null = null;
  for (const p of Object.values(row.routes.cash ?? {})) {
    const t = toTrueCost("cash", p, names);
    if (t?.headline != null && (!cash || t.headline < cash.headline!)) cash = t;
  }
  return {
    trueCost, byRoute, sources: sources.size,
    monthly: monthly?.headline ?? null, monthlyRoute: monthly ? (monthly.route as "pcp" | "pch") : null, threeYear: monthly?.terms.paid ?? null,
    cash: cash ? { offerId: cash.offerId, dealer: cash.dealer, price: cash.headline!, ageDays: cash.ageDays } : null,
    trend: row.trend, stock: row.stock,
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
