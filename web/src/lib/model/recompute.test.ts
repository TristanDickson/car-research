import { describe, expect, it } from "vitest";
import { computeAll } from "./recompute";
import type { SnapshotUsedSpan } from "../types";

const today = "2026-10-11";
const basis = { term_months: 37, savings_rate_apr: 0.04, residual_pct_of_list: 0.45, residual_at_months: 36 };
const used = (key: string, used_key: string | null, price: number): SnapshotUsedSpan => ({
  key, source: "cinch", model: "hyundai/kona-electric", car_id: null, used_key, year: 2023, price, mileage: 20000, vrm: key, town: null,
  from: "2026-10-01", to: today, present: true,
});

describe("the buy-used route", () => {
  it("counts a used car as a car only when it is the same trim and battery", () => {
    const r = computeAll({
      sightings: [],
      usedSpans: [used("u1", "hyundai/kona-electric|ultimate|65", 21000), used("u2", "hyundai/kona-electric|advance|65", 15000), used("u3", null, 9000)],
      cars: [{ id: "ultimate", model_key: "hyundai/kona-electric", used_key: "hyundai/kona-electric|ultimate|65" },
             { id: "nline", model_key: "hyundai/kona-electric", used_key: "hyundai/kona-electric|n line|65" }],
      basis, today, staleDays: 14,
    });
    const byId = new Map(r.cars.map((c) => [c.id, c]));
    expect(byId.get("ultimate")!.routes.used!.cinch.headline).toBe(21000);   // not the cheaper Advance, nor the unnamed one
    expect(byId.get("nline")?.routes.used).toBeUndefined();                    // no used N Line on sale
    expect(byId.get("nline")!.stock!.count).toBe(3);                           // the model's stock still stands as evidence
  });
});
