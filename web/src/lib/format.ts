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

export function carName(c: { make: string; model: string; trim: string }): string {
  return `${c.make} ${c.model} ${c.trim}`;
}
