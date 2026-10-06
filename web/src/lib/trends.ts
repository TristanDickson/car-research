// Price history as series the charts can draw.
//
// Every offer carries its sighting history: one row per distinct price, with the
// span [observed_at, confirmed_at] it was seen over. A line for an offer is its
// spans joined end to end; a 'gone' row breaks the line. "Best cash on day d" is
// the minimum over the spans that cover d.
import type { ObservationPoint, SnapshotOffer } from "./types";

export interface Pt {
  t: number;
  v: number;
}

export interface Series {
  id: string;
  label: string;
  /** Runs of connected points; a break between runs is a gap in the sightings. */
  segments: Pt[][];
  /** Stable colour slot: assigned by sorted id, never by rank. */
  slot: number;
}

export type Metric = "vehicle_price" | "monthly_payment" | "monthly_rental";

const DAY = 86_400_000;

export function toMs(iso: string): number {
  return new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso).getTime();
}

export function dayStart(ms: number): number {
  return Math.floor(ms / DAY) * DAY;
}

function value(h: ObservationPoint, metric: Metric): number | null {
  const v = h[metric];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** A span's end: the last confirmation, else its own sighting. */
export function spanEnd(h: ObservationPoint): number {
  return toMs(h.confirmed_at ?? h.observed_at);
}

/** One series per offer: spans joined into a step line, broken at a 'gone'. */
export function offerSeries(offers: SnapshotOffer[], metric: Metric, label: (o: SnapshotOffer) => string): Series[] {
  const sorted = [...offers].sort((a, b) => a.id.localeCompare(b.id));
  const out: Series[] = [];
  sorted.forEach((o, slot) => {
    const segments: Pt[][] = [];
    let run: Pt[] = [];
    const hist = [...o.freshness.history].sort((a, b) => toMs(a.observed_at) - toMs(b.observed_at));
    for (const h of hist) {
      const v = h.present ? value(h, metric) : null;
      if (v == null) {
        if (run.length) segments.push(run);
        run = [];
        continue;
      }
      const start = toMs(h.observed_at);
      const end = spanEnd(h);
      if (run.length) run.push({ t: start, v: run[run.length - 1].v }); // hold the old price up to this sighting
      run.push({ t: start, v });
      if (end > start) run.push({ t: end, v });
    }
    if (run.length) segments.push(run);
    if (segments.length) out.push({ id: o.id, label: label(o), segments, slot });
  });
  return out;
}

export interface DailyPoint extends Pt {
  offerId: string;
}

/**
 * The best (lowest) value seen on each day, over the spans that cover that day.
 * A current offer's span is extended to `until` (today) so a price confirmed
 * last night still counts today.
 */
export function dailyBest(offers: SnapshotOffer[], metric: Metric, until: number = Date.now(),
                          filter: (o: SnapshotOffer) => boolean = () => true): DailyPoint[] {
  type Span = { from: number; to: number; v: number; offerId: string };
  const spans: Span[] = [];
  for (const o of offers) {
    if (!filter(o)) continue;
    const hist = o.freshness.history;
    hist.forEach((h, i) => {
      const v = h.present ? value(h, metric) : null;
      if (v == null) return;
      const from = dayStart(toMs(h.observed_at));
      const last = i === hist.length - 1;
      const to = dayStart(last && o.freshness.present ? Math.max(spanEnd(h), until) : spanEnd(h));
      spans.push({ from, to, v, offerId: o.id });
    });
  }
  if (!spans.length) return [];
  const first = Math.min(...spans.map((s) => s.from));
  const lastDay = Math.min(dayStart(until), Math.max(...spans.map((s) => s.to)));
  const out: DailyPoint[] = [];
  for (let d = first; d <= lastDay; d += DAY) {
    let best: Span | null = null;
    for (const s of spans) if (s.from <= d && d <= s.to && (!best || s.v < best.v)) best = s;
    if (best) out.push({ t: d, v: best.v, offerId: best.offerId });
  }
  return out;
}

export interface Movement {
  now: number;
  nowSince: number;      // first day of the current run at this value
  daysAtNow: number;
  firstValue: number;
  firstAt: number;
  deltaSinceFirst: number;
  /** Value `window` days ago if we have it, else null. */
  thenValue: number | null;
  deltaSinceThen: number | null;
  points: number;
}

/** How the daily-best series has moved: since first seen, and over a window of days. */
export function movement(points: DailyPoint[], windowDays = 30): Movement | null {
  if (!points.length) return null;
  const last = points[points.length - 1];
  let i = points.length - 1;
  while (i > 0 && points[i - 1].v === last.v && points[i].t - points[i - 1].t === DAY) i--;
  const nowSince = points[i].t;
  const thenT = last.t - windowDays * DAY;
  const then = points.find((p) => p.t >= thenT);
  const thenValue = then && then.t !== last.t && points[0].t <= thenT ? then.v : null;
  return {
    now: last.v,
    nowSince,
    daysAtNow: Math.round((last.t - nowSince) / DAY) + 1,
    firstValue: points[0].v,
    firstAt: points[0].t,
    deltaSinceFirst: last.v - points[0].v,
    thenValue,
    deltaSinceThen: thenValue == null ? null : last.v - thenValue,
    points: points.length,
  };
}

/** Discount against list, as a fraction (0.2 = 20% off), per day. */
export function discountSeries(daily: DailyPoint[], listPrice: number | null | undefined): Pt[] {
  if (!listPrice) return [];
  return daily.map((p) => ({ t: p.t, v: 1 - p.v / listPrice }));
}

/** Keep the last `days` days of a series (all of it when days is null). */
export function lastDays<T extends Pt>(points: T[], days: number | null, until: number = Date.now()): T[] {
  if (days == null) return points;
  const from = dayStart(until) - days * DAY;
  return points.filter((p) => p.t >= from);
}
