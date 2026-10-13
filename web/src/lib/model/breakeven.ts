// Where the choice between buying outright and financing turns, for one car.
//
// Two figures per finance route (the car's cheapest current PCP, its cheapest
// current lease) against its cheapest current cash price: the savings rate at
// which they cost the same, and what the car would have to sell for at the end
// for them to cost the same under the reader's own rate. Both re-cost the same
// current sightings with the one cost function (`cost`), so they follow the
// reader's basis and move with each night's prices. Pure.
import type { Basis } from "./dealMath";
import { cost, MIN_EVIDENCE, NO_SCALE, type FloorGfvAt, type ResidualAt, type Sighting, type TrimScale } from "./sightings";

/** The highest savings rate searched: a deal that is cheaper at every rate up to it is cheaper at any rate a saver earns. */
export const MAX_RATE = 0.3;

export interface BreakEven {
  route: "pcp" | "pch";
  /** The offers compared. */
  key: string;
  cash_key: string;
  /** The savings rate a year at which finance and cash cost the same; null when one is cheaper at every rate up to MAX_RATE. */
  rate: number | null;
  /** Which is cheaper at rates below `rate`, or at every rate when it is null. */
  cheaper_below: "cash" | "finance";
  /** What the car sells for at the end for the two to cost the same, at the reader's rate; null when one is cheaper whatever it sells for. */
  resale: number | null;
  /** Which is cheaper when the car sells for more than `resale`, or whatever it sells for when it is null. */
  cheaper_above: "cash" | "finance";
  /** What the cash figure expects the car to sell for. */
  expected: number | null;
}

/** cash minus finance true monthly under `basis` with these residuals; null when either cannot be costed. */
function gap(cash: Sighting, fin: Sighting, basis: Basis, residual: ResidualAt, floor: FloorGfvAt, asOf: string, trim: TrimScale): number | null {
  const c = cost(cash, basis, residual, floor, asOf, trim), f = cost(fin, basis, residual, floor, asOf, trim);
  return c?.true_monthly != null && f?.true_monthly != null ? c.true_monthly - f.true_monthly : null;
}

/** The rate at which cash and finance cost the same, by bisection: the gap moves one way as the rate rises
 * (cash's money costs more; finance's later payments cost less). */
function rateBreakEven(cash: Sighting, fin: Sighting, basis: Basis, residual: ResidualAt, floor: FloorGfvAt, asOf: string, trim: TrimScale):
    { rate: number | null; cheaper_below: "cash" | "finance" } | null {
  const at = (r: number) => gap(cash, fin, { ...basis, savings_rate_apr: r }, residual, floor, asOf, trim);
  let lo = 0, hi = MAX_RATE;
  const gLo = at(lo), gHi = at(hi);
  if (gLo == null || gHi == null) return null;
  const below = gLo <= 0 ? "cash" : "finance";
  if (gLo === 0 || Math.sign(gLo) === Math.sign(gHi)) return { rate: gLo === 0 ? 0 : null, cheaper_below: below };
  for (let i = 0; i < 14; i++) {
    const mid = (lo + hi) / 2, g = at(mid);
    if (g == null) return null;
    if (Math.sign(g) === Math.sign(gLo)) lo = mid;
    else hi = mid;
  }
  return { rate: (lo + hi) / 2, cheaper_below: below };
}

/** The end value at which cash and finance cost the same. The gap is linear in the end value, with one kink at a
 * PCP's GFV (above it the equity comes back on both routes alike), so three points find it exactly. */
function resaleBreakEven(cash: Sighting, fin: Sighting, basis: Basis, floor: FloorGfvAt, asOf: string):
    { resale: number | null; cheaper_above: "cash" | "finance" } | null {
  const price = typeof cash.deal.vehicle_price === "number" ? cash.deal.vehicle_price : null;
  if (!price) return null;
  const at = (v: number) => gap(cash, fin, basis, () => [v, MIN_EVIDENCE], floor, asOf, NO_SCALE);
  const gfv = fin.route === "pcp" && typeof fin.deal.gfv === "number" ? fin.deal.gfv : null;
  const xs = Array.from(new Set([1, ...(gfv && gfv > 1 && gfv < price ? [gfv] : []), price])).sort((a, b) => a - b);
  const gs = xs.map(at);
  if (gs.some((g) => g == null)) return null;
  const g = gs as number[];
  const above = g[g.length - 1] <= 0 ? "cash" : "finance";
  for (let i = 0; i + 1 < xs.length; i++) {
    if (g[i] === 0) return { resale: xs[i], cheaper_above: above };
    if (Math.sign(g[i]) !== Math.sign(g[i + 1]) && g[i + 1] !== 0) {
      return { resale: xs[i] + ((xs[i + 1] - xs[i]) * g[i]) / (g[i] - g[i + 1]), cheaper_above: above };
    }
  }
  return { resale: null, cheaper_above: above };
}

/** Each finance route against the car's cheapest cash price, as of `asOf`. */
export function breakEvens(cash: Sighting | null, finance: Partial<Record<"pcp" | "pch", Sighting>>, basis: Basis, residual: ResidualAt,
                           floor: FloorGfvAt, asOf: string, trim: TrimScale = NO_SCALE): BreakEven[] {
  if (!cash) return [];
  const expected = cost(cash, basis, residual, floor, asOf, trim)?.end_value ?? null;
  const out: BreakEven[] = [];
  for (const route of ["pcp", "pch"] as const) {
    const fin = finance[route];
    if (!fin) continue;
    const r = rateBreakEven(cash, fin, basis, residual, floor, asOf, trim);
    const v = resaleBreakEven(cash, fin, basis, floor, asOf);
    if (!r || !v) continue;
    out.push({ route, key: fin.key, cash_key: cash.key, ...r, ...v, expected });
  }
  return out;
}
