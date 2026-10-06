// Tiny scale helpers: nice ticks and date ticks, nothing more.
const DAY = 86_400_000;

export function niceTicks(min: number, max: number, count = 4): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) {
    const pad = Math.abs(min) * 0.05 || 1;
    min -= pad; max += pad;
  }
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const lo = Math.ceil(min / step) * step;
  const out: number[] = [];
  for (let v = lo; v <= max + 1e-9; v += step) out.push(Number(v.toFixed(10)));
  return out;
}

/** Date ticks at day / week / month spacing depending on the span. */
export function dateTicks(min: number, max: number, count = 5): number[] {
  const span = max - min;
  if (span <= 0) return [min];
  const candidates = [DAY, 2 * DAY, 7 * DAY, 14 * DAY, 30 * DAY, 61 * DAY, 91 * DAY, 182 * DAY, 365 * DAY];
  const step = candidates.find((s) => span / s <= count) ?? 365 * DAY;
  const out: number[] = [];
  for (let t = Math.ceil(min / step) * step; t <= max; t += step) out.push(t);
  if (!out.length) out.push(min);
  return out;
}

export function shortDate(ms: number, span: number): string {
  const d = new Date(ms);
  if (span > 300 * DAY) return d.toLocaleDateString("en-GB", { month: "short", year: "2-digit", timeZone: "UTC" });
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}

export function longDate(ms: number): string {
  return new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}
