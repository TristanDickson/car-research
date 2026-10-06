import { describe, expect, it } from "vitest";

import { ageDays, ageLabel, isStale } from "./freshness";
import type { Freshness } from "./types";

const now = new Date("2026-10-20T12:00:00Z");
const f = (over: Partial<Freshness>): Freshness => ({
  state: "live", stale: false, age_days: 0, first_seen_at: "2026-10-05", last_seen_at: "2026-10-05",
  last_checked_at: "2026-10-05", observations: 1, present: true, history: [], ...over,
});

describe("freshness", () => {
  it("ages from the last sighting, not from the snapshot", () => {
    expect(ageDays("2026-10-05", now)).toBe(15);
    expect(ageDays("2026-10-20T08:00:00Z", now)).toBe(0);
    expect(ageDays(null, now)).toBeNull();
    expect(ageLabel("2026-10-19", now)).toBe("1 day ago");
  });
  it("only active offers can be stale", () => {
    expect(isStale(f({ last_seen_at: "2026-10-05" }), 14, now)).toBe(true);
    expect(isStale(f({ last_seen_at: "2026-10-10" }), 14, now)).toBe(false);
    expect(isStale(f({ state: "expired", last_seen_at: "2026-09-01" }), 14, now)).toBe(false);
    expect(isStale(f({ state: "gone", last_seen_at: "2026-09-01" }), 14, now)).toBe(false);
  });
});
