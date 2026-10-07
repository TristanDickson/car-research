// What a car costs, read off the snapshot. The cost model lives in the pipeline
// (model/sightings.py costs every sighting; deal_summary.routes carries the
// cheapest current one per route and source, as of the snapshot date). This
// file only picks and labels; the headline route details (dealer, term, GFV)
// still come from the current offers for the card's small print.
import { isCurrent } from "./freshness";
import type { Route, RouteSource, SnapshotCar, SnapshotOffer } from "./types";

export interface RouteCost {
  offerId: string;
  dealer: string | null;
  /** Monthly cash flow: PCP monthly at £0 down, or PCH total spread over the term. */
  monthly: number;
  /** Everything paid over the agreement if the car is handed back. */
  threeYear: number | null;
  termMonths: number | null;
  gfv: number | null;
  lastSeenAt: string | null;
}

export interface CashCost {
  offerId: string;
  dealer: string | null;
  price: number;
  lastSeenAt: string | null;
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
  ageDays: number | null;
}

export interface CarCosts {
  /** Cheapest current sighting on one footing across cash, PCP, lease and used (model/sightings.py). */
  trueCost: TrueCost | null;
  /** Every route and source the car has a current figure for. */
  routes: Partial<Record<Route, Record<string, RouteSource>>>;
  /** Cheapest current monthly route, if any. */
  monthly: number | null;
  monthlyRoute: "pcp" | "pch" | null;
  threeYear: number | null;
  pcp: RouteCost | null;
  pch: RouteCost | null;
  cash: CashCost | null;
}

function label(o: SnapshotOffer): string | null {
  return o.dealer ?? o.source ?? null;
}

/** The cheapest current sighting across every route and source, from the snapshot. */
export function trueCostOf(car: SnapshotCar | undefined): TrueCost | null {
  let best: TrueCost | null = null;
  for (const [route, bySource] of Object.entries(car?.deal_summary?.routes ?? {})) {
    for (const p of Object.values(bySource ?? {})) {
      if (p.true_monthly == null) continue;
      if (!best || p.true_monthly < best.monthly) {
        best = { route: route as Route, offerId: p.key, dealer: p.seller ?? null, source: p.source_name, monthly: p.true_monthly,
                 floor: p.true_monthly_floor ?? null, headline: p.headline, ageDays: p.age_days ?? null };
      }
    }
  }
  return best;
}

export function carCosts(offers: SnapshotOffer[], staleDays: number, now: Date = new Date(), car?: SnapshotCar): CarCosts {
  const current = offers.filter((o) => isCurrent(o, staleDays, now) && !o.metrics.skipped);

  let pcp: RouteCost | null = null;
  for (const o of current) {
    const m = o.metrics;
    if (o.finance_type !== "pcp" || m.monthly_payment == null || (o.customer_deposit ?? 0) !== 0) continue;
    if (!pcp || m.monthly_payment < pcp.monthly) {
      pcp = {
        offerId: o.id, dealer: label(o), monthly: m.monthly_payment,
        threeYear: m.paid_if_handed_back ?? null, termMonths: m.term_months ?? null, gfv: m.gfv ?? null,
        lastSeenAt: o.freshness.last_seen_at,
      };
    }
  }

  let pch: RouteCost | null = null;
  for (const o of current) {
    const m = o.metrics;
    if (o.finance_type !== "pch" || m.effective_monthly == null) continue;
    if (!pch || m.effective_monthly < pch.monthly) {
      pch = {
        offerId: o.id, dealer: label(o), monthly: m.effective_monthly,
        threeYear: m.total_cost ?? null, termMonths: m.term_months ?? null, gfv: null,
        lastSeenAt: o.freshness.last_seen_at,
      };
    }
  }

  let cash: CashCost | null = null;
  for (const o of current) {
    const price = o.metrics.vehicle_price ?? o.vehicle_price;
    if (o.finance_type !== "cash" || price == null) continue;
    if (!cash || price < cash.price) cash = { offerId: o.id, dealer: label(o), price, lastSeenAt: o.freshness.last_seen_at };
  }

  const candidates: { route: "pcp" | "pch"; r: RouteCost }[] = [];
  if (pcp) candidates.push({ route: "pcp", r: pcp });
  if (pch) candidates.push({ route: "pch", r: pch });
  candidates.sort((a, b) => a.r.monthly - b.r.monthly);
  const best = candidates[0] ?? null;

  return {
    trueCost: trueCostOf(car),
    routes: car?.deal_summary?.routes ?? {},
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

/** The brief's hard requirements as short ticks for a card. */
export function briefTicks(c: SnapshotCar): { label: string; ok: boolean | null }[] {
  const tri = (v?: string) => (v === "standard" || v === "pack" || v === "option" ? true : v === "none" ? false : null);
  return [
    { label: "heat pump", ok: tri(c.heat_pump) },
    { label: "cabin socket", ok: tri(c.internal_v2l) },
    { label: "seats", ok: c.seats == null ? null : c.seats >= 4 },
  ];
}

export const IONIQ5_WIDTH_MM = 1890;

export const ROUTE_LABEL: Record<Route, string> = { pcp: "PCP", pch: "lease", cash: "buy outright", used: "buy used" };
export const ROUTES: Route[] = ["cash", "pcp", "pch", "used"];
