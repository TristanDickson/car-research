import { describe, expect, it } from "vitest";

import { changeRank, filterChanges, orderChanges, sourceName, sumCounts } from "./resolverChanges";
import type { ResolverChange } from "./types";

const ch = (source: string, outcome: ResolverChange["outcome"], records = 1, label = "x"): ResolverChange => ({
  source, model: null, outcome, status: "placed", label, today: [], car: null, others: [], others_count: 0,
  version: null, why: null, decided_by: [], records, key: `${source}:${label}`,
});

describe("resolver changes", () => {
  it("ranks price losses and moves, then used ones, then the rest", () => {
    expect(changeRank(ch("leaseloco", "moved"))).toBe(0);
    expect(changeRank(ch("carwow_used", "lost"))).toBe(1);
    expect(changeRank(ch("leaseloco", "newly placed"))).toBe(2);
    expect(changeRank(ch("evdb", "moved"))).toBe(2);
  });
  it("orders losses before moves, then bigger groups", () => {
    const out = orderChanges([ch("evdb", "moved"), ch("carwow_used", "moved", 5), ch("leaseloco", "moved", 2), ch("leaseloco", "lost", 1), ch("leaseloco", "moved", 9)]);
    expect(out.map((c) => `${c.source}:${c.outcome}:${c.records}`)).toEqual([
      "leaseloco:lost:1", "leaseloco:moved:9", "leaseloco:moved:2", "carwow_used:moved:5", "evdb:moved:1",
    ]);
  });
  it("filters by source and outcome", () => {
    const rows = [ch("a", "lost"), ch("a", "moved"), ch("b", "moved")];
    expect(filterChanges(rows, "all", "all")).toHaveLength(3);
    expect(filterChanges(rows, "a", "moved")).toHaveLength(1);
    expect(filterChanges(rows, "all", "moved")).toHaveLength(2);
  });
  it("sums counts and names sources in plain words", () => {
    expect(sumCounts([{ same: 2, lost: 1 }, { same: 3 }])).toEqual({ same: 5, lost: 1 });
    expect(sourceName("evdb")).toBe("EV Database");
    expect(sourceName("something_new")).toBe("something_new");
  });
});
