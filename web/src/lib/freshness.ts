import type { Freshness, OfferState, SnapshotOffer } from "./types";

export const ACTIVE_STATES: ReadonlySet<OfferState> = new Set(["live", "lead", "derived", "illustrative"]);

const DAY = 86_400_000;

/** Calendar days (UTC) since an ISO date/datetime, as of `now`: yesterday evening is 1, not 0. */
export function ageDays(iso: string | null | undefined, now: Date = new Date()): number | null {
  if (!iso) return null;
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) return null;
  return Math.max(0, Math.floor(now.getTime() / DAY) - Math.floor(d.getTime() / DAY));
}

/** The snapshot's own stale flag is relative to generated_at; recompute from the
 * last sighting so an un-refreshed deploy still tells the truth days later. */
export function isStale(f: Freshness, staleDays: number, now: Date = new Date()): boolean {
  if (!ACTIVE_STATES.has(f.state)) return false;
  const age = ageDays(f.last_seen_at, now);
  return age != null && age > staleDays;
}

export function isCurrent(o: SnapshotOffer, staleDays: number, now: Date = new Date()): boolean {
  return ACTIVE_STATES.has(o.freshness.state) && !isStale(o.freshness, staleDays, now);
}

export function ageLabel(iso: string | null | undefined, now: Date = new Date()): string {
  const a = ageDays(iso, now);
  if (a == null) return "never";
  if (a === 0) return "today";
  if (a === 1) return "1 day ago";
  return `${a} days ago`;
}
