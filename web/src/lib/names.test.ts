import { describe, expect, it } from "vitest";

import { nameNotes, withNameNotes } from "./names";

const base = { make: "BMW", model: "iX1", trim: "xLine · 150kW eDrive20 65kWh Auto", seats: 5 };

describe("look-alike notes", () => {
  it("say only what is needed to tell cars with the same name apart, the price last", () => {
    const cars = [
      { ...base, id: "a", cap_name: "150kW eDrive20 xLine 65kWh 5dr Auto", version_date: "2025-03-01", list_price_gbp: 49065 },
      { ...base, id: "b", cap_name: "150kW eDrive20 xLine 65kWh 5dr Auto [22kWCh]", version_date: "2026-07-23", list_price_gbp: 39945 },
      { ...base, id: "c", cap_name: "150kW eDrive20 xLine 65kWh 5dr Auto", version_date: "2026-07-23", list_price_gbp: 39065 },
      { ...base, id: "d", trim: "M Sport · 150kW eDrive20 65kWh Auto" },
    ];
    expect(Object.fromEntries(nameNotes(cars))).toEqual({
      a: "price list Mar 2025", b: "[22kWCh] · price list Jul 2026", c: "price list Jul 2026",
    });
  });

  it("use the price only when nothing else separates them, and the CAP id when even that agrees", () => {
    const sameMonth = [{ ...base, id: "p", version_date: "2026-07-23", list_price_gbp: 39065 }, { ...base, id: "q", version_date: "2026-07-23", list_price_gbp: 41815 }];
    expect(Object.fromEntries(nameNotes(sameMonth))).toEqual({ p: "£39,065", q: "£41,815" });
    const twins = [{ ...base, id: "x", cap_id: "1" }, { ...base, id: "y", cap_id: "2" }];
    expect(Object.fromEntries(nameNotes(twins))).toEqual({ x: "CAP 1", y: "CAP 2" });
  });

  it("replace whatever note the data carried", () => {
    const [lone] = withNameNotes([{ ...base, id: "z", name_note: "£31,195 from an old build" }]);
    expect(lone.name_note).toBeUndefined();
  });
});
