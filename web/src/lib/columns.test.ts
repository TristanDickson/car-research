import { describe, expect, it } from "vitest";

import { arrange, isShown, move, NO_PREFS, toggle } from "./columns";

const cols = [{ key: "car", pinned: true }, { key: "true" }, { key: "seats" }, { key: "width" }, { key: "turn", hidden: true }];
const keys = (xs: { key: string }[]) => xs.map((c) => c.key);

describe("the reader's columns", () => {
  it("defaults: the pinned column first, then the default order; a hidden-by-default column is off", () => {
    expect(keys(arrange(cols, NO_PREFS))).toEqual(["car", "true", "seats", "width", "turn"]);
    expect(cols.filter((c) => isShown(c, NO_PREFS)).map((c) => c.key)).toEqual(["car", "true", "seats", "width"]);
  });

  it("moves a column among the unpinned ones and keeps the pinned one first", () => {
    let p = move(cols, NO_PREFS, "width", -1);
    p = move(cols, p, "width", -1);
    expect(keys(arrange(cols, p))).toEqual(["car", "width", "true", "seats", "turn"]);
    expect(move(cols, p, "width", -1)).toBe(p);   // already first of the movable ones
    expect(move(cols, p, "car", 1)).toBe(p);      // the pinned one does not move
  });

  it("turns columns on and off; the pinned one stays on; a new column joins after the reader's order", () => {
    let p = toggle(cols, NO_PREFS, "turn");
    p = toggle(cols, p, "seats");
    p = toggle(cols, p, "car");
    expect(cols.filter((c) => isShown(c, p)).map((c) => c.key)).toEqual(["car", "true", "width", "turn"]);
    const more = [...cols, { key: "boot" }];
    expect(keys(arrange(more, { ...p, order: ["turn", "true"] }))).toEqual(["car", "turn", "true", "seats", "width", "boot"]);
  });

  it("a column turned on joins the end of the shown ones; moving steps over hidden columns", () => {
    const many = [{ key: "car", pinned: true }, { key: "a" }, { key: "x", hidden: true }, { key: "y", hidden: true }, { key: "b" }, { key: "z", hidden: true }];
    const shownKeys = (p: typeof NO_PREFS) => arrange(many, p).filter((c) => isShown(c, p)).map((c) => c.key);
    let p = toggle(many, NO_PREFS, "z");
    expect(shownKeys(p)).toEqual(["car", "a", "b", "z"]);
    p = move(many, p, "z", -1);
    expect(shownKeys(p)).toEqual(["car", "a", "z", "b"]);
    p = move(many, p, "b", -1);
    p = move(many, p, "b", -1);
    expect(shownKeys(p)).toEqual(["car", "b", "a", "z"]);
    expect(move(many, p, "x", -1)).toBe(p);   // a hidden column has no place to move from
  });
});
