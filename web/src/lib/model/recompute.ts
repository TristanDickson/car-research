// Everything the pages read about prices, computed in one pass from the facts
// the pipeline exported, under the reader's basis, as of today.
//
// Pure: spans and cars in, results out. lib/db.ts runs it whenever the snapshot,
// the basis or the day changes and stores the results in IndexedDB; the pages
// read the stored rows and never cost anything themselves.
import type { Route, SnapshotCar, SnapshotSighting, SnapshotUsedSpan } from "../types";
import type { Basis } from "./dealMath";
import { offersFrom, toSighting } from "./offers";
import { bestByRoute, costAll, current, goneDates, markCurrent, residualAt, residualSeries, series, trend, usedStock, type CurrentPoint, type ResidualRow, type SeriesRow, type Sighting, type Trend, type UsedStock } from "./sightings";

/** What a car costs today, every route and source, with the movement of its best cash price and its model's used stock. */
export interface CarCostRow {
  id: string;
  model: string;
  /** route → source → the cheapest current sighting; the used route is the model's. */
  routes: Partial<Record<Route, Record<string, CurrentPoint>>>;
  /** route → the cheapest source's figure. */
  best: Partial<Record<Route, CurrentPoint>>;
  trend: Trend | null;
  stock: UsedStock | null;
}

export interface ComputeInput {
  sightings: SnapshotSighting[];
  usedSpans: SnapshotUsedSpan[];
  cars: Pick<SnapshotCar, "id" | "model_key">[];
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
  return { key: u.key, route: "used", source: u.source, model: u.model, car_id: u.car_id, from: u.from, to: u.to, present: u.present,
           deal: { price: u.price, year: u.year, mileage: u.mileage, vrm: u.vrm }, seller: u.town };
}

export function computeAll(input: ComputeInput): ComputeResult {
  const t0 = Date.now();
  // A key's latest state holds until seen gone or stale, so a price confirmed last night is today's.
  const all = markCurrent([...input.sightings.filter((s) => s.route === "cash" || s.route === "pcp" || s.route === "pch").map(toSighting),
                           ...input.usedSpans.map(usedToSighting)], input.today, input.staleDays);
  const used = all.filter((s) => s.route === "used");
  const history = costAll(all, input.basis);
  const now = costAll(all, input.basis, input.today);
  const rows = series(history, goneDates(all));
  const cur = current(now, input.today, input.staleDays);
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
    const routes = { ...(cur.get(c.id) ?? {}), ...(cur.get(`model:${model}`) ?? {}) };
    let stock = stockByModel.get(model);
    if (stock === undefined && model) {
      stock = usedStock(model, used, input.today, input.basis);
      stockByModel.set(model, stock);
    }
    const tr = trend(cashSeries.get(c.id) ?? [], input.today);
    if (!Object.keys(routes).length && !tr && !(stock && stock.count)) continue;
    cars.push({ id: c.id, model, routes, best: bestByRoute(routes), trend: tr, stock: stock && stock.count ? stock : null });
  }
  const offers = offersFrom(input.sightings, input.basis, input.today, input.staleDays, residualAt(used));
  return { cars, series: rows, residuals: residualSeries(used, input.today), offers,
           stats: { sightings: all.length, costed: history.length, ms: Date.now() - t0 } };
}
