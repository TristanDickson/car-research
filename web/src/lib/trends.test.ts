import { describe, expect, it } from "vitest";

import { dailyBest, discountSeries, lastDays, movement, offerSeries } from "./trends";
import type { SnapshotOffer } from "./types";

const DAY = 86_400_000;
const T = (d: string) => new Date(`${d}T00:00:00Z`).getTime();

function offer(id: string, history: { observed_at: string; confirmed_at?: string; present?: boolean; vehicle_price?: number }[],
               present = true): SnapshotOffer {
  return {
    id, offer_key: id, car_id: "car", finance_type: "cash", status: "lead", source: id, captured_at: "2026-10-06", metrics: {},
    freshness: {
      state: "lead", stale: false, age_days: 0, first_seen_at: history[0].observed_at, last_seen_at: null, last_checked_at: "",
      observations: history.length, present,
      history: history.map((h) => ({ source: "x", present: true, ...h, confirmed_at: h.confirmed_at ?? null })),
    },
  } as unknown as SnapshotOffer;
}

describe("offerSeries", () => {
  it("joins spans into a step line and breaks at a gone", () => {
    const o = offer("a", [
      { observed_at: "2026-09-01", confirmed_at: "2026-09-10", vehicle_price: 100 },
      { observed_at: "2026-09-12", confirmed_at: "2026-09-20", vehicle_price: 90 },
      { observed_at: "2026-09-25", present: false },
      { observed_at: "2026-10-01", vehicle_price: 95 },
    ]);
    const [s] = offerSeries([o], "vehicle_price", (x) => x.id);
    expect(s.segments.length).toBe(2);
    expect(s.segments[0].map((p) => [p.t, p.v])).toEqual([
      [T("2026-09-01"), 100], [T("2026-09-10"), 100], [T("2026-09-12"), 100], [T("2026-09-12"), 90], [T("2026-09-20"), 90],
    ]);
    expect(s.segments[1]).toEqual([{ t: T("2026-10-01"), v: 95 }]);
  });
});

describe("dailyBest", () => {
  const a = offer("a", [{ observed_at: "2026-09-01", confirmed_at: "2026-09-03", vehicle_price: 100 }], false);
  const b = offer("b", [{ observed_at: "2026-09-02", confirmed_at: "2026-09-02", vehicle_price: 90 }]);
  it("takes the lowest covering span per day and extends a current offer to today", () => {
    const pts = dailyBest([a, b], "vehicle_price", T("2026-09-05"));
    expect(pts.map((p) => [new Date(p.t).toISOString().slice(0, 10), p.v, p.offerId])).toEqual([
      ["2026-09-01", 100, "a"], ["2026-09-02", 90, "b"], ["2026-09-03", 90, "b"], ["2026-09-04", 90, "b"], ["2026-09-05", 90, "b"],
    ]);
  });
  it("movement reports the current run, the first value and the windowed delta", () => {
    const pts = dailyBest([a, b], "vehicle_price", T("2026-09-05"));
    const m = movement(pts, 2)!;
    expect(m.now).toBe(90);
    expect(m.daysAtNow).toBe(4);
    expect(m.firstValue).toBe(100);
    expect(m.deltaSinceFirst).toBe(-10);
    expect(m.thenValue).toBe(90);
    expect(movement(pts, 30)!.thenValue).toBeNull();
  });
  it("discount and window helpers", () => {
    const pts = dailyBest([a, b], "vehicle_price", T("2026-09-05"));
    expect(discountSeries(pts, 200)[0].v).toBeCloseTo(0.5);
    expect(lastDays(pts, 1, T("2026-09-05")).length).toBe(2);
    expect(lastDays(pts, null).length).toBe(5);
    expect(pts[1].t - pts[0].t).toBe(DAY);
  });
});
