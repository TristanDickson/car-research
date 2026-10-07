// What a car really costs, from the current offers captured for it. Used by
// the Pick cards and the Compare page; the full table stays on /offers.
import { isCurrent } from "./freshness";
import type { SnapshotCar, SnapshotOffer } from "./types";

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
  route: "pcp" | "pch" | "cash";
  offerId: string;
  dealer: string | null;
  /** Present cost at the savings rate, expected end value credited back, spread over the agreement. */
  monthly: number;
  /** The same with the car worth only its GFV at the end. */
  floor: number | null;
  lastSeenAt: string | null;
}

export interface CarCosts {
  /** Cheapest current offer on one footing across cash, PCP and lease (model/deal_math.py). */
  trueCost: TrueCost | null;
  /** Cheapest current monthly route, if any. */
  monthly: number | null;
  monthlyRoute: "pcp" | "pch" | null;
  threeYear: number | null;
  pcp: RouteCost | null;
  pch: RouteCost | null;
  cash: CashCost | null;
  /** Cash price minus the best PCP's GFV: three-year cost if it is worth at least the floor. */
  cashThreeYearAtFloor: number | null;
}

function label(o: SnapshotOffer): string | null {
  return o.dealer ?? o.source ?? null;
}

export function carCosts(offers: SnapshotOffer[], staleDays: number, now: Date = new Date()): CarCosts {
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

  let trueCost: TrueCost | null = null;
  for (const o of current) {
    const m = o.metrics;
    if (m.true_monthly == null || (o.finance_type !== "pcp" && o.finance_type !== "pch" && o.finance_type !== "cash")) continue;
    if (!trueCost || m.true_monthly < trueCost.monthly) {
      trueCost = { route: o.finance_type, offerId: o.id, dealer: label(o), monthly: m.true_monthly, floor: m.true_monthly_floor ?? null, lastSeenAt: o.freshness.last_seen_at };
    }
  }

  const candidates: { route: "pcp" | "pch"; r: RouteCost }[] = [];
  if (pcp) candidates.push({ route: "pcp", r: pcp });
  if (pch) candidates.push({ route: "pch", r: pch });
  candidates.sort((a, b) => a.r.monthly - b.r.monthly);
  const best = candidates[0] ?? null;

  return {
    trueCost,
    monthly: best ? best.r.monthly : null,
    monthlyRoute: best ? best.route : null,
    threeYear: best ? best.r.threeYear : null,
    pcp,
    pch,
    cash,
    cashThreeYearAtFloor: cash && pcp?.gfv != null ? cash.price - pcp.gfv : null,
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

export const ROUTE_LABEL: Record<"pcp" | "pch" | "cash", string> = { pcp: "PCP", pch: "lease", cash: "buy outright" };
