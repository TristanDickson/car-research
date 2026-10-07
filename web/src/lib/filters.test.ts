import { describe, expect, it } from "vitest";

import { carMatches, filterOptions, filtersFrom, inScope, isEmpty, offerMatches, withFilters } from "./filters";
import type { SnapshotCar, SnapshotOffer } from "./types";

const car = (id: string, extra: Partial<SnapshotCar> = {}): SnapshotCar =>
  ({ id, make: "Kia", model: "EV3", trim: id, model_year: 2026, picks: [], specs: [], spec_check: { rows: [], disagreements: 0 },
     deal_summary: { offers: 0, current_offers: 0, best_cash_price: null, best_cash_offer_id: null, best_cash_age_days: null, best_pcp_monthly: null,
                     best_pcp_offer_id: null, best_pcp_age_days: null, best_pch_effective_monthly: null, best_pch_offer_id: null, best_pch_age_days: null },
     ...extra }) as SnapshotCar;

const hand = car("kia-ev3-gtline-s");
const gen = car("carwow-cap:106391", { auto: true, trim: "Air · 150kW 58.3kWh Auto", make: "Kia", model: "EV3" });
const bmw = car("carwow-cap:1", { auto: true, make: "BMW", model: "i4", trim: "Sport · 250kW eDrive40 83.9kWh Auto" });

describe("scope", () => {
  it("defaults to the hand-curated shortlist; ?scope=all adds the generated cars", () => {
    const def = filtersFrom(new URLSearchParams(""));
    expect(def.scope).toBe("");
    expect(inScope(hand, def)).toBe(true);
    expect(inScope(gen, def)).toBe(false);
    const all = filtersFrom(new URLSearchParams("scope=all"));
    expect(inScope(gen, all)).toBe(true);
    expect(filtersFrom(new URLSearchParams("scope=bogus")).scope).toBe("");
  });

  it("is not a narrowing: isEmpty ignores it and links carry it", () => {
    const all = filtersFrom(new URLSearchParams("scope=all"));
    expect(isEmpty(all)).toBe(true);
    expect(withFilters("/cars", all)).toBe("/cars?scope=all");
    expect(carMatches(bmw, { ...all, make: "BMW" })).toBe(true);
    expect(carMatches(bmw, { ...all, scope: "", make: "BMW" })).toBe(false);
  });

  it("offers follow their car's scope, and the option lists only show what is in view", () => {
    const o = { id: "x", car_id: gen.id, finance_type: "cash" } as unknown as SnapshotOffer;
    expect(offerMatches(o, gen, filtersFrom(null))).toBe(false);
    expect(offerMatches(o, gen, filtersFrom(new URLSearchParams("scope=all")))).toBe(true);
    expect(filterOptions([hand, gen, bmw], [], filtersFrom(null)).makes).toEqual(["Kia"]);
    expect(filterOptions([hand, gen, bmw], [], filtersFrom(new URLSearchParams("scope=all"))).makes).toEqual(["BMW", "Kia"]);
  });
});
