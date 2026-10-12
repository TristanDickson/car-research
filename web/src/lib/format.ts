export function gbp(n: number | null | undefined, digits = 0): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `£${n.toLocaleString("en-GB", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

export function pct(x: number | null | undefined, digits = 1): string {
  if (x == null || !Number.isFinite(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

export function num(n: number | null | undefined, digits = 0, unit = ""): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${n.toLocaleString("en-GB", { maximumFractionDigits: digits })}${unit}`;
}

export function dateLabel(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

/** A car's name: make, model, trim. What tells look-alikes apart goes under it (`nameDetail`), not in it. */
export function carName(c: { make: string; model: string; trim: string }): string {
  return `${c.make} ${c.model} ${c.trim}`;
}

/** The name plus what tells it apart, for sorting and searching. */
export function sortName(c: { make: string; model: string; trim: string; name_note?: string }): string {
  return c.name_note ? `${carName(c)} ${c.name_note}` : carName(c);
}

/** The grey line under a car's name: its packs, then what tells it apart from cars with the same name
 * (the snapshot's `name_note`), leaving out a bracket that only repeats a pack already listed. */
export function nameDetail(c: { packs?: string[] | null; name_note?: string }): string {
  const packs = c.packs ?? [];
  const listed = new Set(packs.map((p) => p.toLowerCase()));
  const note = (c.name_note ?? "").split(" · ").filter((part) => part && !listed.has(part.replace(/^\[|\]$/g, "").toLowerCase()));
  return [packs.join(" + "), ...note].filter(Boolean).join(" · ");
}
