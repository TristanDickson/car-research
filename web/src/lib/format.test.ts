import { describe, expect, it } from "vitest";

import { carName, nameDetail, sortName } from "./format";

const ioniq3 = { make: "Hyundai", model: "Ioniq 3", trim: "Ultimate 61kWh", packs: ["EV Pack"], name_note: "[EV Pack] · £31,195" };

describe("a car's name", () => {
  it("is make, model and trim; what tells look-alikes apart is not in it", () => {
    expect(carName(ioniq3)).toBe("Hyundai Ioniq 3 Ultimate 61kWh");
  });

  it("puts packs and the look-alike note on the line under it, without repeating a pack", () => {
    expect(nameDetail(ioniq3)).toBe("EV Pack · £31,195");
    expect(nameDetail({ packs: [], name_note: "price list Jul 2026" })).toBe("price list Jul 2026");
    expect(nameDetail({ packs: ["Tech Pack", "Zen Pack"] })).toBe("Tech Pack + Zen Pack");
    expect(nameDetail({})).toBe("");
  });

  it("sorts and searches with the note, so look-alikes keep a stable order", () => {
    expect(sortName(ioniq3)).toBe("Hyundai Ioniq 3 Ultimate 61kWh [EV Pack] · £31,195");
    expect(sortName({ make: "Kia", model: "EV3", trim: "Air" })).toBe("Kia EV3 Air");
  });
});
