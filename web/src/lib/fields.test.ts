import { describe, expect, it } from "vitest";

import { FIELD_BY_KEY, FIELDS, flagFields, RANGE_FIELDS, show, triOf } from "./fields";
import type { SnapshotCar } from "./types";

describe("the field list", () => {
  it("names each field once and keeps every range key a saved search may already use", () => {
    expect(new Set(FIELDS.map((x) => x.key)).size).toBe(FIELDS.length);
    for (const k of ["true", "cash", "monthly", "list", "range", "battery", "seats", "width", "length", "turn", "boot", "power", "dc", "year"]) {
      expect(RANGE_FIELDS.some((x) => x.key === k), k).toBe(true);
    }
  });

  it("reads a value off the car and shows it with its unit", () => {
    const c = { id: "c", make: "Hyundai", model: "Inster", trim: "02", picks: [], width_mm: 1610, wheel_in: 17, list_price_gbp: 25000, grant_gbp: 1500 } as unknown as SnapshotCar;
    const w = FIELD_BY_KEY.get("width")!;
    expect(show(w, w.value(c, null))).toBe("1,610 mm");
    expect(show(FIELD_BY_KEY.get("wheels")!, 17)).toBe("17 in");
    const net = FIELD_BY_KEY.get("net")!;
    expect(show(net, net.value(c, null))).toBe("£23,500");
    expect(show(FIELD_BY_KEY.get("roof_rails")!, false)).toBe("no");
    expect(show(w, null)).toBe("—");
    expect(show(FIELD_BY_KEY.get("year")!, 2026)).toBe("2026");
  });

  it("makes a tri-state column of every flag the snapshot names, with the pack it comes in", () => {
    const [hp] = flagFields({ heat_pump: "Heat pump" });
    const c = { flags: { heat_pump: "pack" }, packs_required: { heat_pump: "Heat Pump Pack" } } as unknown as SnapshotCar;
    expect(hp.key).toBe("flag:heat_pump");
    expect(triOf(hp.value(c, null))).toBe("pack");
    expect(hp.pack?.(c)).toBe("Heat Pump Pack");
    expect(triOf(undefined)).toBe("unknown");
  });
});
