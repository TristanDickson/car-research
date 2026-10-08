// One fact for every way of paying for a car: a sighting.
//
// A sighting is a price one source showed for one subject, over the span of
// days it stayed the same. The subject is a derivative (an offer on a car) or,
// for a used car, the model and registration year the listing belongs to. Four
// routes: cash (an outright price), pcp, pch (a lease), used (an asking price);
// sources are a dimension of their own, so the same derivative and route can
// be read source by source, and over time.
//
// Everything here is pure. `cost` puts one sighting on the common footing of
// dealMath (every payment discounted at the savings rate, the car's expected
// end value credited back, spread over the months) with the residual the used
// market gave *as of a date*, so a sighting from June is costed on what June's
// used stock said, and today's on today's; `series` groups costed sightings by
// subject, route and source; `current` picks the best per route and source as
// of today. The pipeline exports the sightings (sightings.json, used_spans.json)
// and knows nothing of the reader's term or rate: lib/recompute.ts runs this
// whenever the snapshot or the reader's basis changes and stores the results.
import type { Route } from "../types";
import { cashMetrics, pchMetrics, pcpMetrics, usedRoute, type Basis, type DealFields, type Metrics, type Residuals } from "./dealMath";
import { pchOverHorizon, pcpOverHorizon, type AtHorizon } from "./horizon";

export const ROUTES: Route[] = ["cash", "pcp", "pch", "used"];
export const MIN_EVIDENCE = 3;

export interface Sighting {
  /** The offer key, or the used listing key. */
  key: string;
  route: Route;
  /** A source id (the site, not the provider that read it). */
  source: string;
  /** "make/model" catalogue slugs. */
  model: string;
  /** The derivative, where the sighting names one. */
  car_id: string | null;
  /** ISO dates: first seen in this state, last confirmed in it (to >= from). */
  from: string;
  to: string;
  present: boolean;
  /** The price-bearing fields: an offer payload, or {price, year, mileage, vrm}. */
  deal: DealFields;
  seller: string | null;
  /** Offers: what the source implied at the time (live, lead, derived, ...). */
  status?: string | null;
  /** The key's latest state, present and confirmed within the stale window: still on
   * offer today though last confirmed earlier (markCurrent). */
  current?: boolean;
}

/** Flag each key's latest state as current when it is present and was confirmed within `staleDays` of today. */
export function markCurrent(sightings: Sighting[], today: string, staleDays: number): Sighting[] {
  const latest = new Map<string, Sighting>();
  for (const s of sightings) {
    const cur = latest.get(s.key);
    if (!cur || s.from > cur.from || (s.from === cur.from && s.to > cur.to)) latest.set(s.key, s);
  }
  const cutoff = addDays(today, -staleDays);
  return sightings.map((s) => (latest.get(s.key) === s && s.present && s.to.slice(0, 10) >= cutoff ? { ...s, current: true } : s));
}

/** Was the sighting live on `iso`: within its span, or current and the day is after it. */
export const liveOn = (s: Sighting, iso: string): boolean => s.from.slice(0, 10) <= iso && (iso <= s.to.slice(0, 10) || !!s.current);

/** What a series is about: the derivative, or the model for used stock. */
export const subject = (s: Sighting): string => (s.route !== "used" && s.car_id ? s.car_id : `model:${s.model}`);

/** Whole years in a number of months, at least one: the registration-year offset for a residual. */
export const yearsOf = (months: number): number => Math.max(1, Math.round(months / 12));

const DAY = 86_400_000;
export const toMs = (iso: string): number => Date.parse(`${iso.slice(0, 10)}T00:00:00Z`);
export const toIso = (ms: number): string => new Date(ms).toISOString().slice(0, 10);
export const addDays = (iso: string, days: number): string => toIso(toMs(iso) + days * DAY);
export const daysBetween = (a: string, b: string): number => Math.round((toMs(b) - toMs(a)) / DAY);
export const yearOf = (iso: string): number => Number(iso.slice(0, 4));

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

function median(sorted: number[]): number {
  const n = sorted.length;
  return n % 2 ? sorted[(n - 1) / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
}

/** The used examples listed on a day, one row per car: a site that prints no
 * registration still prints the mileage, and the same mileage as a registered
 * listing is the same car. */
export function liveCars(spans: Sighting[], iso: string): { car: string; price: number; s: Sighting }[] {
  const live = spans.filter((s) => s.present && liveOn(s, iso) && num(s.deal.price) != null);
  const plateByMileage = new Map<number, string>();
  for (const s of live) {
    const vrm = s.deal.vrm as string | undefined, mi = num(s.deal.mileage);
    if (vrm && mi != null && !plateByMileage.has(mi)) plateByMileage.set(mi, vrm);
  }
  const best = new Map<string, { car: string; price: number; s: Sighting }>();
  for (const s of live) {
    const mi = num(s.deal.mileage);
    const car = (s.deal.vrm as string | undefined) || (mi != null ? plateByMileage.get(mi) : undefined) || `mi:${mi ?? s.key}`;
    const price = s.deal.price as number;
    const cur = best.get(car);
    if (!cur || price < cur.price) best.set(car, { car, price, s });
  }
  return Array.from(best.values());
}

export type ResidualAt = (model: string, year: number, iso: string) => [median: number, n: number] | null;

/** (model, registration year, date) → the median asking price and count of the
 * model's used examples of that year on sale that day, or null below MIN_EVIDENCE. */
export function residualAt(used: Sighting[]): ResidualAt {
  const by = new Map<string, Sighting[]>();
  for (const s of used) {
    if (s.present && num(s.deal.year) && num(s.deal.price)) {
      const k = `${s.model}|${s.deal.year}`;
      const list = by.get(k);
      if (list) list.push(s);
      else by.set(k, [s]);
    }
  }
  const cache = new Map<string, [number, number] | null>();
  return (model, year, iso) => {
    const ck = `${model}|${year}|${iso}`;
    const hit = cache.get(ck);
    if (hit !== undefined) return hit;
    const prices = liveCars(by.get(`${model}|${year}`) ?? [], iso).map((c) => c.price).sort((a, b) => a - b);
    const out: [number, number] | null = prices.length >= MIN_EVIDENCE ? [Math.round(median(prices)), prices.length] : null;
    cache.set(ck, out);
    return out;
  };
}

export type FloorGfvAt = (carId: string | null, iso: string) => number | null;

/** (car, date) → the highest GFV any lender guaranteed for the car that day: the floor a cash buyer could count on. */
export function floorGfvAt(offers: Sighting[]): FloorGfvAt {
  const by = new Map<string, Sighting[]>();
  for (const s of offers) {
    if (s.route === "pcp" && s.present && s.car_id && num(s.deal.gfv)) {
      const list = by.get(s.car_id);
      if (list) list.push(s);
      else by.set(s.car_id, [s]);
    }
  }
  return (carId, iso) => {
    let best: number | null = null;
    for (const s of by.get(carId ?? "") ?? []) {
      if (liveOn(s, iso)) best = Math.max(best ?? -Infinity, s.deal.gfv as number);
    }
    return best;
  };
}

/** The deal as the source printed it, for the small print beside the comparable figure. */
export interface PrintedTerms {
  /** Everything paid over the agreement if handed back (PCP), the rentals and fees (lease), the price (cash, used). */
  paid: number | null;
  deposit?: number | null;
  monthly?: number | null;
  payments?: number | null;
  gfv?: number | null;
  apr?: number | null;
  contribution?: number | null;
  initial?: number | null;
  rentals?: number | null;
  term_months?: number | null;
  mileage?: number | null;
  year?: number | null;
  price?: number | null;
  derived?: boolean;
}

export function printedTerms(route: Route, deal: DealFields, m: Metrics | null): PrintedTerms {
  const n = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
  switch (route) {
    case "pcp": return { paid: m?.paid_if_handed_back ?? null, deposit: m?.customer_deposit ?? n(deal.customer_deposit), monthly: m?.monthly_payment ?? n(deal.monthly_payment),
                         payments: m?.num_payments ?? n(deal.num_payments), gfv: m?.gfv ?? n(deal.gfv), apr: n(deal.apr), contribution: m?.manufacturer_contribution ?? n(deal.manufacturer_contribution),
                         term_months: m?.term_months ?? n(deal.term_months), mileage: n(deal.annual_mileage), derived: (m?.derived_fields?.length ?? 0) > 0 };
    case "pch": return { paid: m?.total_cost ?? null, initial: m?.initial_rental ?? n(deal.initial_rental), monthly: m?.monthly_rental ?? n(deal.monthly_rental),
                         rentals: m?.num_rentals ?? n(deal.num_rentals), term_months: m?.term_months ?? n(deal.term_months), mileage: n(deal.annual_mileage) };
    case "cash": return { paid: n(deal.vehicle_price), price: n(deal.vehicle_price) };
    case "used": return { paid: n(deal.price), price: n(deal.price), year: n(deal.year), mileage: n(deal.mileage) };
  }
}

export interface Costed {
  s: Sighting;
  /** The date the residual evidence was read. */
  as_of: string;
  /** What the source printed: a price, or a monthly. */
  headline: number | null;
  /** The ranking figure: over the reader's horizon, or over the deal's own term (basis.compare_over). */
  true_monthly: number | null;
  true_monthly_floor: number | null;
  pv_cost: number | null;
  horizon_months: number;
  at_horizon: AtHorizon;
  /** The deal as agreed: its own term and the figure over it. */
  own_true_monthly: number | null;
  own_horizon_months: number;
  end_value: number | null;
  residual_source: string | null;
  /** The full normalisation of an offer (null for a used listing), for the table. */
  metrics: Metrics | null;
  terms: PrintedTerms;
}

function residualsFor(s: Sighting, months: number, asOf: string, residual: ResidualAt): Residuals | null {
  if (!s.car_id) return null;
  const ev = residual(s.model, yearOf(asOf) - yearsOf(months), asOf);
  return ev ? { [s.car_id]: { value: ev[0], source: "used-market", n: ev[1] } } : null;
}

/** One sighting on the common footing, with the used market read as of `asOf`. */
export function cost(s: Sighting, basis: Basis, residual: ResidualAt, floorGfv: FloorGfvAt, asOf: string): Costed | null {
  const H = Math.max(1, Math.trunc(basis.term_months || 37));
  const overHorizon = basis.compare_over !== "own";
  if (s.route === "used") {
    const price = num(s.deal.price), year = num(s.deal.year);
    if (!price) return null;
    const ev = year ? residual(s.model, year - yearsOf(H), asOf) : null;
    const m = usedRoute(price, year ? yearOf(asOf) - year : null, basis, ev ? ev[0] : null);
    return { s, as_of: asOf, headline: price, true_monthly: m.true_monthly, true_monthly_floor: null, pv_cost: m.pv_cost,
             horizon_months: H, at_horizon: "sold", own_true_monthly: m.true_monthly, own_horizon_months: H,
             end_value: m.expected_value_at_end, residual_source: m.residual_source, metrics: null, terms: printedTerms("used", s.deal, null) };
  }
  const d: DealFields = { ...s.deal, id: s.key, car_id: s.car_id, finance_type: s.route, status: (s.deal.status as string | undefined) ?? s.status ?? "live" };
  let m: Metrics;
  let headline: number | null;
  let own: { tm: number | null; floor: number | null; pv: number | null; months: number };
  let hz: { tm: number | null; floor: number | null; pv: number | null; months: number; kind: AtHorizon; end: number | null; src: string | null };
  try {
    if (s.route === "pcp") {
      const n = num(d.num_payments);
      const floor = floorGfv(s.car_id, asOf);
      m = pcpMetrics(d, null, basis, n != null ? residualsFor(s, n + 1, asOf, residual) : null, floor);
      if (m.skipped || m.true_monthly == null || n == null) return null;
      headline = m.monthly_payment ?? null;
      own = { tm: m.true_monthly, floor: m.true_monthly_floor ?? null, pv: m.pv_cost ?? null, months: n + 1 };
      if (H === n + 1) hz = { ...own, kind: "as_agreed", end: m.expected_value_at_end ?? null, src: m.residual_source ?? null };
      else {
        const h = pcpOverHorizon(d, H, basis, residualsFor(s, H, asOf, residual), floor, m.apr_implied ?? null);
        if (!h) return null;
        hz = { tm: h.true_monthly, floor: h.true_monthly_floor, pv: h.pv_cost, months: h.horizon_months, kind: h.at_horizon, end: h.expected_value_at_end, src: h.residual_source };
      }
    } else if (s.route === "pch") {
      m = pchMetrics(d, basis);
      if (m.skipped || m.true_monthly == null) return null;
      headline = m.effective_monthly ?? num(d.monthly_rental);
      own = { tm: m.true_monthly, floor: m.true_monthly_floor ?? null, pv: m.pv_cost ?? null, months: m.term_months ?? H };
      const h = pchOverHorizon(m.initial_rental ?? 0, m.fees ?? 0, m.num_rentals ?? 0, m.monthly_rental ?? 0, own.months, own.tm, H, basis);
      hz = { tm: h.true_monthly, floor: h.true_monthly_floor, pv: h.pv_cost, months: h.horizon_months, kind: h.at_horizon, end: null, src: null };
    } else if (s.route === "cash") {
      m = cashMetrics(d, basis, floorGfv(s.car_id, asOf), residualsFor(s, H, asOf, residual));
      if (m.skipped || m.true_monthly == null) return null;
      headline = num(d.vehicle_price);
      own = { tm: m.true_monthly, floor: m.true_monthly_floor ?? null, pv: m.pv_cost ?? null, months: H };
      hz = { ...own, kind: "sold", end: m.expected_value_at_end ?? null, src: m.residual_source ?? null };
    } else return null;
  } catch {
    return null;   // a payload the maths cannot cost is dropped, not fatal
  }
  const pick = overHorizon ? hz : { ...own, kind: (s.route === "cash" ? "sold" : "as_agreed") as AtHorizon, end: m.expected_value_at_end ?? null, src: m.residual_source ?? null };
  return { s, as_of: asOf, headline, true_monthly: pick.tm, true_monthly_floor: pick.floor, pv_cost: pick.pv, horizon_months: pick.months,
           at_horizon: pick.kind, own_true_monthly: own.tm, own_horizon_months: own.months, end_value: pick.end, residual_source: pick.src, metrics: m,
           terms: printedTerms(s.route, d, m) };
}

/** Every present sighting costed, each as of its own first day (history) or as of one date (`asOf`, for what things cost today). */
export function costAll(sightings: Sighting[], basis: Basis, asOf?: string): Costed[] {
  const residual = residualAt(sightings.filter((s) => s.route === "used"));
  const floor = floorGfvAt(sightings.filter((s) => s.route !== "used"));
  const out: Costed[] = [];
  for (const s of sightings) {
    if (!s.present) continue;
    const c = cost(s, basis, residual, floor, asOf ?? s.from.slice(0, 10));
    if (c) out.push(c);
  }
  return out;
}

/** One sighting as a series point or a current figure. */
export interface Point {
  from: string;
  to: string;
  key: string;
  seller: string | null;
  headline: number | null;
  true_monthly: number | null;
  true_monthly_floor: number | null;
  residual_source: string | null;
  end_value: number | null;
  horizon_months: number;
  at_horizon: AtHorizon;
  own_true_monthly: number | null;
  own_horizon_months: number;
  terms: PrintedTerms;
  /** Used stock only: how many examples were on sale when this one was the cheapest. */
  n?: number;
}

export function point(c: Costed): Point {
  return { from: c.s.from.slice(0, 10), to: c.s.to.slice(0, 10), key: c.s.key, seller: c.s.seller ?? null, headline: c.headline,
           true_monthly: c.true_monthly, true_monthly_floor: c.true_monthly_floor, residual_source: c.residual_source, end_value: c.end_value,
           horizon_months: c.horizon_months, at_horizon: c.at_horizon, own_true_monthly: c.own_true_monthly, own_horizon_months: c.own_horizon_months,
           terms: c.terms };
}

/** For a crowd of overlapping sightings (a model's used stock), the cheapest true monthly on each day the set changes, as flat steps. */
export function bestSteps(cs: Costed[]): Point[] {
  const bounds = Array.from(new Set(cs.flatMap((c) => [c.s.from.slice(0, 10), c.s.to.slice(0, 10)]))).sort();
  const steps: Point[] = [];
  bounds.forEach((d, i) => {
    const live = cs.filter((c) => c.s.from.slice(0, 10) <= d && d <= c.s.to.slice(0, 10) && c.true_monthly != null);
    if (!live.length) return;
    let best = live[0];
    for (const c of live) if ((c.true_monthly as number) < (best.true_monthly as number)) best = c;
    const to = i + 1 < bounds.length ? bounds[i + 1] : d;
    const last = steps[steps.length - 1];
    if (last && last.key === best.s.key && last.true_monthly === best.true_monthly) { last.to = to; return; }
    steps.push({ ...point(best), from: d, to, n: live.length });
  });
  return steps;
}

/** key → the days it was seen gone, for the gaps in a line. */
export function goneDates(sightings: Sighting[]): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const s of sightings) {
    if (s.present) continue;
    const list = out.get(s.key);
    if (list) list.push(s.from.slice(0, 10));
    else out.set(s.key, [s.from.slice(0, 10)]);
  }
  for (const v of out.values()) v.sort();
  return out;
}

/** An offer's price holds from one sighting to the next that confirmed or changed
 * it, unless it was seen gone in between (the archive's captures are sparse). */
export function held(points: Point[], gone: Map<string, string[]>): Point[] {
  const byKey = new Map<string, Point[]>();
  for (const p of points) {
    const list = byKey.get(p.key);
    if (list) list.push(p);
    else byKey.set(p.key, [p]);
  }
  for (const [key, ps] of byKey) {
    ps.sort((a, b) => a.from.localeCompare(b.from));
    for (let i = 0; i + 1 < ps.length; i++) {
      const a = ps[i], b = ps[i + 1];
      if (a.to < b.from && !(gone.get(key) ?? []).some((g) => a.to < g && g <= b.from)) a.to = b.from;
    }
  }
  return points.sort((a, b) => a.from.localeCompare(b.from) || a.key.localeCompare(b.key));
}

export interface SeriesRow {
  id: string;
  subject: string;
  car_id: string | null;
  model: string;
  route: Route;
  source: string;
  points: Point[];
}

/** Costed sightings grouped by subject, route and source: an offer's sightings as
 * flat spans held to the next sighting; a model's used stock as the cheapest example day by day. */
export function series(costed: Costed[], gone: Map<string, string[]> = new Map()): SeriesRow[] {
  const groups = new Map<string, Costed[]>();
  for (const c of costed) {
    const k = `${subject(c.s)}|${c.s.route}|${c.s.source}`;
    const list = groups.get(k);
    if (list) list.push(c);
    else groups.set(k, [c]);
  }
  const out: SeriesRow[] = [];
  for (const [id, cs] of Array.from(groups.entries()).sort((a, b) => a[0].localeCompare(b[0]))) {
    cs.sort((a, b) => a.s.from.localeCompare(b.s.from) || a.s.key.localeCompare(b.s.key));
    const first = cs[0].s;
    const route = first.route;
    const points = route === "used" ? bestSteps(cs) : held(cs.map(point), gone);
    out.push({ id, subject: subject(first), car_id: route !== "used" ? first.car_id : null, model: first.model, route, source: first.source, points });
  }
  return out;
}

export interface ResidualRow {
  id: string;
  model: string;
  year: number;
  points: { date: string; median: number; n: number }[];
}

/** What the used market said a model's cars of each registration year were worth, month by month. */
export function residualSeries(used: Sighting[], today: string): ResidualRow[] {
  const residual = residualAt(used);
  const keys = new Map<string, [string, number]>();
  let start: string | null = null;
  for (const s of used) {
    if (!(s.present && num(s.deal.year) && num(s.deal.price))) continue;
    keys.set(`${s.model}|${s.deal.year}`, [s.model, s.deal.year as number]);
    const f = s.from.slice(0, 10);
    if (start == null || f < start) start = f;
  }
  if (!keys.size || start == null) return [];
  const dates: string[] = [];
  let d = new Date(Date.UTC(yearOf(start), Number(start.slice(5, 7)) - 1, 1));
  while (toIso(d.getTime()) <= today) {
    dates.push(toIso(d.getTime()));
    d = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1));
  }
  if (!dates.length || dates[dates.length - 1] !== today) dates.push(today);
  const out: ResidualRow[] = [];
  for (const [model, year] of Array.from(keys.values()).sort((a, b) => a[0].localeCompare(b[0]) || a[1] - b[1])) {
    const pts = dates.flatMap((date) => { const ev = residual(model, year, date); return ev ? [{ date, median: ev[0], n: ev[1] }] : []; });
    if (pts.length) out.push({ id: `${model}|${year}`, model, year, points: pts });
  }
  return out;
}

export interface CurrentPoint extends Point {
  source: string;
  age_days: number;
}
/** subject → route → source → the cheapest sighting still current. */
export type Current = Map<string, Partial<Record<Route, Record<string, CurrentPoint>>>>;

/** The cheapest sighting still current (last confirmed within `staleDays`) per subject, route and source, costed as of today. */
export function current(costedToday: Costed[], today: string, staleDays: number): Current {
  const cutoff = addDays(today, -staleDays);
  const out: Current = new Map();
  for (const c of costedToday) {
    const s = c.s;
    if (s.to.slice(0, 10) < cutoff || c.true_monthly == null) continue;
    let routes = out.get(subject(s));
    if (!routes) { routes = {}; out.set(subject(s), routes); }
    const slot = (routes[s.route] ??= {});
    const cur = slot[s.source];
    if (!cur || (c.true_monthly as number) < (cur.true_monthly as number)) {
      slot[s.source] = { ...point(c), source: s.source, age_days: daysBetween(s.to.slice(0, 10), today) };
    }
  }
  return out;
}

/** route → the cheapest source's figure. */
export function bestByRoute(routes: Partial<Record<Route, Record<string, CurrentPoint>>>): Partial<Record<Route, CurrentPoint>> {
  const out: Partial<Record<Route, CurrentPoint>> = {};
  for (const [route, bySrc] of Object.entries(routes) as [Route, Record<string, CurrentPoint>][]) {
    for (const p of Object.values(bySrc)) if (!out[route] || (p.true_monthly as number) < (out[route]!.true_monthly as number)) out[route] = p;
  }
  return out;
}

export type Measure = "headline" | "true_monthly";

/** The cheapest `measure` any point showed on `day`. */
export function bestOn(points: Point[], day: string, measure: Measure = "headline"): number | null {
  let best: number | null = null;
  for (const p of points) {
    const v = p[measure];
    if (v != null && p.from <= day && day <= p.to && (best == null || v < best)) best = v;
  }
  return best;
}

export interface Trend {
  now: number;
  then: number | null;
  delta: number | null;
  window_days: number;
  first_at: string;
  days_at_now: number;
  spark: [string, number][];
}

/** A card's worth of movement for one subject and route across its sources: the
 * cheapest figure now, `window` days ago, how long it has held, and a short sparkline over `days`. */
export function trend(rows: SeriesRow[], today: string, measure: Measure = "headline", days = 90, window = 30, spark = 12): Trend | null {
  const points = rows.flatMap((r) => r.points);
  if (!points.length) return null;
  let first = points[0].from, lastTo = points[0].to;
  for (const p of points) { if (p.from < first) first = p.from; if (p.to > lastTo) lastTo = p.to; }
  const now = bestOn(points, today, measure) ?? bestOn(points, lastTo, measure);
  if (now == null) return null;
  const then = bestOn(points, addDays(today, -window), measure);
  let heldDays = 0;
  while (heldDays < 3650 && bestOn(points, addDays(today, -(heldDays + 1)), measure) === now) heldDays++;
  const span = Math.max(1, Math.min(days, daysBetween(first, today)));
  const step = Math.max(1, Math.floor(span / Math.max(1, spark - 1)));
  const pts: [string, number][] = [];
  for (let i = 0; i <= span; i += step) {
    const d = addDays(today, -(span - i));
    const v = bestOn(points, d, measure);
    if (v != null) pts.push([d, v]);
  }
  if (!pts.length || pts[pts.length - 1][0] !== today) pts.push([today, now]);
  return { now, then, delta: then != null ? now - then : null, window_days: window, first_at: first, days_at_now: heldDays, spark: pts };
}

export interface UsedStock {
  model: string;
  /** Distinct cars on sale today (a car on two sites counts once). */
  count: number;
  /** Live listings per site, before folding duplicates. */
  sources: Record<string, number>;
  by_year: Record<string, { n: number; median: number; min: number }>;
  /** What examples registered term-years ago ask today, when there are enough of them. */
  residual: { value: number; n: number; year: number } | null;
  cheapest: { key: string; price: number; year: number | null; mileage: number | null; source: string; seller: string | null } | null;
}

/** A model's used stock as of today: the evidence behind every end value, and the cheapest example. */
export function usedStock(model: string, spans: Sighting[], today: string, basis: Basis): UsedStock {
  const mine = spans.filter((s) => s.model === model);
  const live = liveCars(mine, today);
  const sources: Record<string, number> = {};
  for (const s of mine) if (s.present && liveOn(s, today) && num(s.deal.price) != null) sources[s.source] = (sources[s.source] ?? 0) + 1;
  const byYear: Record<string, { n: number; median: number; min: number }> = {};
  const years = Array.from(new Set(live.map((c) => num(c.s.deal.year)).filter((y): y is number => y != null))).sort();
  for (const y of years) {
    const prices = live.filter((c) => c.s.deal.year === y).map((c) => c.price).sort((a, b) => a - b);
    byYear[String(y)] = { n: prices.length, median: Math.round(median(prices)), min: prices[0] };
  }
  const targetYear = yearOf(today) - yearsOf(basis.term_months || 37);
  const ev = byYear[String(targetYear)];
  const cheapest = live.length ? live.reduce((a, b) => (b.price < a.price ? b : a)) : null;
  return {
    model, count: live.length, sources, by_year: byYear,
    residual: ev && ev.n >= MIN_EVIDENCE ? { value: ev.median, n: ev.n, year: targetYear } : null,
    cheapest: cheapest ? { key: cheapest.s.key, price: cheapest.price, year: num(cheapest.s.deal.year), mileage: num(cheapest.s.deal.mileage), source: cheapest.s.source, seller: cheapest.s.seller } : null,
  };
}
