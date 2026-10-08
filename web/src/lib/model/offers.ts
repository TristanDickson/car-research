// An offer, derived from its spans: the latest state the source showed, how
// fresh it is, and its normalisation under the reader's basis. What
// offers.json used to carry, computed here from sightings.json instead.
import type { FinanceType, Freshness, ObservationPoint, OfferState, SnapshotOffer, SnapshotSighting } from "../types";
import { compute, type Basis, type DealFields, type Residuals } from "./dealMath";
import { cost, floorGfvAt, residualAt, yearOf, yearsOf, type ResidualAt, type Sighting } from "./sightings";

export const ACTIVE_STATUSES: ReadonlySet<string> = new Set(["live", "lead", "derived", "illustrative"]);
const HISTORY_FIELDS = ["monthly_payment", "vehicle_price", "apr", "gfv", "initial_rental", "monthly_rental"] as const;

const DAY = 86_400_000;
const days = (a: string, b: string) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / DAY);

/** The spans of one offer, oldest first, as its freshness block. */
export function freshness(spans: SnapshotSighting[], today: string, staleDays: number): Freshness {
  const latest = spans[spans.length - 1];
  const seen = spans.filter((s) => s.present);
  const lastSeen = seen.length ? seen.map((s) => s.to).sort().pop()! : null;
  const age = lastSeen ? days(lastSeen, today) : null;
  const validTo = latest.deal.valid_to as string | undefined;
  const state: OfferState = !latest.present ? "gone" : validTo && validTo < today ? "expired" : (latest.status as OfferState);
  const history: ObservationPoint[] = spans.map((s) => {
    const h: ObservationPoint = { observed_at: s.from, confirmed_at: s.to, present: s.present, source: s.provider };
    for (const k of HISTORY_FIELDS) if (typeof s.deal[k] === "number") (h as unknown as Record<string, unknown>)[k] = s.deal[k];
    return h;
  });
  return {
    state, stale: ACTIVE_STATUSES.has(state) && age != null && age > staleDays, age_days: age,
    first_seen_at: spans[0].from, last_seen_at: lastSeen, last_checked_at: latest.to, observations: spans.length, present: latest.present, history,
  };
}

/** A span as the cost model's sighting. */
export function toSighting(s: SnapshotSighting): Sighting {
  return { key: s.key, route: s.route as Sighting["route"], source: s.source, model: s.model, car_id: s.car_id, from: s.from, to: s.to,
           present: s.present, deal: s.deal as DealFields, seller: s.seller, status: s.status };
}

/** One row per offer key: the latest span's payload, its freshness, metrics and the
 * comparable figure, as of today. `residual` is the used market (read over spans
 * already marked current). */
export function offersFrom(spans: SnapshotSighting[], basis: Basis, today: string, staleDays: number, residual?: ResidualAt): SnapshotOffer[] {
  const byKey = new Map<string, SnapshotSighting[]>();
  for (const s of spans) {
    const list = byKey.get(s.key);
    if (list) list.push(s);
    else byKey.set(s.key, [s]);
  }
  const H = Math.max(1, Math.trunc(basis.term_months || 37));
  const res = residual ?? residualAt([]);
  const latest: { key: string; s: SnapshotSighting; f: Freshness }[] = [];
  for (const [key, list] of byKey) {
    list.sort((a, b) => a.from.localeCompare(b.from) || a.to.localeCompare(b.to));
    latest.push({ key, s: list[list.length - 1], f: freshness(list, today, staleDays) });
  }
  // The benchmark and the floor come from what is on offer now, not from what has gone.
  const deals: DealFields[] = latest.map(({ key, s, f }) => ({ ...(s.deal as DealFields), id: key, car_id: s.car_id, finance_type: s.route, status: s.status,
                                                               vehicle_price: f.state === "gone" && s.route === "cash" ? null : (s.deal.vehicle_price as number | null | undefined) }));
  const residuals: Residuals = {};
  for (const { s } of latest) {
    if (s.car_id && !(s.car_id in residuals)) {
      const ev = res(s.model, yearOf(today) - yearsOf(H), today);
      if (ev) residuals[s.car_id] = { value: ev[0], source: "used-market", n: ev[1] };
    }
  }
  const metrics = compute(deals, basis, residuals);
  const floor = floorGfvAt(latest.filter(({ s, f }) => s.present && !f.stale).map(({ s }) => ({ ...toSighting(s), current: true })));
  return latest.map(({ key, s, f }, i) => {
    const m = { ...metrics[i] } as Record<string, unknown>;
    for (const k of ["id", "car_id", "finance_type", "status"]) delete m[k];
    const costed = s.present && s.route !== "campaign" ? cost({ ...toSighting(s), current: !f.stale }, basis, res, floor, today) : null;
    return {
      ...(s.deal as Record<string, unknown>), id: key, car_id: s.car_id, provider: s.provider, finance_type: s.route as FinanceType, status: s.status,
      captured_at: (s.deal.captured_at as string | undefined) ?? s.from, freshness: f, metrics: m,
      comparable: costed ? { true_monthly: costed.true_monthly, horizon_months: costed.horizon_months, at_horizon: costed.at_horizon,
                             own_true_monthly: costed.own_true_monthly, own_horizon_months: costed.own_horizon_months, end_value: costed.end_value } : null,
    } as SnapshotOffer;
  });
}
