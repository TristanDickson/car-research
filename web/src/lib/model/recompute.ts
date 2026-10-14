// Everything the pages read about prices, computed in one pass from the facts
// the pipeline exported, under the reader's basis, as of today.
//
// Pure: spans and cars in, results out. lib/db.ts runs it whenever the snapshot,
// the basis or the day changes and stores the results in IndexedDB; the pages
// read the stored rows and never cost anything themselves.
import type { Route, SnapshotCar, SnapshotSighting, SnapshotUsedSpan } from "../types";
import { breakEvens, type BreakEven } from "./breakeven";
import type { Basis } from "./dealMath";
import { offersFrom, toSighting } from "./offers";
import { bestByRoute, costAll, current, floorGfvAt, goneDates, markCurrent, residualAt, residualSeries, series, trend, trimScale, usedStock, type CurrentPoint, type ResidualRow, type SeriesRow, type Sighting, type Trend, type UsedStock } from "./sightings";

/** What a car costs today, every route and source, with the movement of its best cash price and its model's used stock. */
export interface CarCostRow {
  id: string;
  model: string;
  /** route → source → the cheapest current sighting; the used route is the same trim and battery's. */
  routes: Partial<Record<Route, Record<string, CurrentPoint>>>;
  /** The same as `routes`, leaving out the figures whose end value rests on few used cars (current, firm). */
  firm_routes?: Partial<Record<Route, Record<string, CurrentPoint>>>;
  /** route → the cheapest source's figure. */
  best: Partial<Record<Route, CurrentPoint>>;
  trend: Trend | null;
  stock: UsedStock | null;
  /** This car's list price over its model's median: what scales the model's used median to this trim (1 when unknown). */
  trim_scale: number;
  /** Where its cheapest PCP and lease overtake its cheapest cash price: the savings rate, and the resale price. */
  breakeven: BreakEven[];
  /** listing key → every current used listing of this car's trim and battery, costed: the used table's own figure per car. */
  used_listings: Record<string, UsedListingCost>;
}

export interface UsedListingCost {
  true_monthly: number | null;
  end_value: number | null;
  evidence_n: number | null;
}

export interface ComputeInput {
  sightings: SnapshotSighting[];
  usedSpans: SnapshotUsedSpan[];
  cars: Pick<SnapshotCar, "id" | "model_key" | "used_key" | "list_price_gbp" | "on_sale">[];
  basis: Basis;
  /** ISO date: the wall clock, for ages and staleness. */
  today: string;
  staleDays: number;
}

export interface ComputeResult {
  cars: CarCostRow[];
  series: SeriesRow[];
  residuals: ResidualRow[];
  offers: ReturnType<typeof offersFrom>;
  stats: { sightings: number; costed: number; ms: number };
}

export function usedToSighting(u: SnapshotUsedSpan): Sighting {
  return { key: u.key, route: "used", source: u.source, model: u.model, car_id: u.car_id, used_key: u.used_key ?? null, from: u.from, to: u.to, present: u.present,
           deal: { price: u.price, year: u.year, mileage: u.mileage, vrm: u.vrm }, seller: u.town, ...(u.vehicle_state === "New" ? { new_car: true } : {}) };
}

export function computeAll(input: ComputeInput): ComputeResult {
  const t0 = Date.now();
  // A key's latest state holds until seen gone or stale, so a price confirmed last night is today's.
  const all = markCurrent([...input.sightings.filter((s) => s.route === "cash" || s.route === "pcp" || s.route === "pch").map(toSighting),
                           ...input.usedSpans.map(usedToSighting)], input.today, input.staleDays);
  const used = all.filter((s) => s.route === "used");
  const trim = trimScale(input.cars);
  const history = costAll(all, input.basis, undefined, trim);
  const now = costAll(all, input.basis, input.today, trim);
  const rows = series(history, goneDates(all));
  const cur = current(now, input.today);
  const firm = current(now, input.today, true);
  const residual = residualAt(used), floor = floorGfvAt(all.filter((s) => s.route !== "used"));
  const currentByKey = new Map(all.filter((s) => s.current).map((s) => [s.key, s]));
  const usedByTrim = new Map<string, Record<string, UsedListingCost>>();
  for (const c of now) {
    if (c.s.route !== "used" || !c.s.current || !c.s.used_key) continue;
    const listings = usedByTrim.get(c.s.used_key) ?? {};
    listings[c.s.key] = { true_monthly: c.true_monthly, end_value: c.end_value, evidence_n: c.evidence_n };
    usedByTrim.set(c.s.used_key, listings);
  }
  const cashSeries = new Map<string, SeriesRow[]>();
  for (const r of rows) {
    if (r.route !== "cash") continue;
    const list = cashSeries.get(r.subject);
    if (list) list.push(r);
    else cashSeries.set(r.subject, [r]);
  }
  const stockByModel = new Map<string, UsedStock>();
  const cars: CarCostRow[] = [];
  for (const c of input.cars) {
    const model = c.model_key ?? "";
    // A used car counts as this car only when it is the same trim and battery; the model's whole stock stays the residual evidence.
    const routes = { ...(cur.get(c.id) ?? {}), ...(c.used_key ? cur.get(`used:${c.used_key}`) ?? {} : {}) };
    const firmRoutes = { ...(firm.get(c.id) ?? {}), ...(c.used_key ? firm.get(`used:${c.used_key}`) ?? {} : {}) };
    let stock = stockByModel.get(model);
    if (stock === undefined && model) {
      stock = usedStock(model, used, input.today, input.basis);
      stockByModel.set(model, stock);
    }
    const tr = trend(cashSeries.get(c.id) ?? [], input.today);
    if (!Object.keys(routes).length && !tr && !(stock && stock.count)) continue;
    const best = bestByRoute(routes);
    const sighting = (p: CurrentPoint | undefined) => (p ? currentByKey.get(p.key) : undefined);
    const finance = { pcp: sighting(best.pcp), pch: sighting(best.pch) };
    const breakeven = breakEvens(sighting(best.cash) ?? null, finance, input.basis, residual, floor, input.today, trim);
    cars.push({ id: c.id, model, routes, firm_routes: firmRoutes, best, trend: tr, stock: stock && stock.count ? stock : null, trim_scale: trim(c.id), breakeven,
                used_listings: (c.used_key && usedByTrim.get(c.used_key)) || {} });
  }
  const offers = offersFrom(input.sightings, input.basis, input.today, input.staleDays, residual, trim);
  return { cars, series: rows, residuals: residualSeries(used, input.today), offers,
           stats: { sightings: all.length, costed: history.length, ms: Date.now() - t0 } };
}
