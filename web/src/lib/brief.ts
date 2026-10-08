// The brief, evaluated in the browser against the requirements the reader
// keeps in this browser (lib/db.ts settings). Mirrors pipeline/services/
// snapshot.evaluate_hard, which still checks the seed's copy at export for the
// markdown table; the app never reads that result.
import type { RequirementRule, SnapshotCar } from "./types";

export type BriefStatus = "pass" | "fail" | "unknown";

export interface Brief {
  status: BriefStatus;
  /** Rule ids that fail outright. */
  failures: string[];
  /** Rule ids the car carries no value for (a generated car mostly). */
  unknown: string[];
  /** The same two lists as short labels, for display. */
  failedLabels: string[];
  unknownLabels: string[];
  /** Every car-level rule with its verdict, for the card ticks and the table. */
  rules: { id: string; label: string; ok: boolean | null }[];
}

const UNKNOWN = new Set<unknown>([null, undefined, "", "unknown"]);

/** One rule against one car: true, false, or null when the car does not say. */
export function checkRule(rule: RequirementRule, car: SnapshotCar): boolean | null {
  if (!rule.field) return null;
  const value = (car as unknown as Record<string, unknown>)[rule.field];
  if (UNKNOWN.has(value)) return null;
  const want = rule.value;
  switch (rule.op) {
    case "==": return value === want;
    case "!=": return value !== want;
    case "in": return Array.isArray(want) ? want.includes(value) : false;
    case "not in": return Array.isArray(want) ? !want.includes(value) : false;
    case ">=": return typeof value === "number" && typeof want === "number" ? value >= want : null;
    case "<=": return typeof value === "number" && typeof want === "number" ? value <= want : null;
    case ">": return typeof value === "number" && typeof want === "number" ? value > want : null;
    case "<": return typeof value === "number" && typeof want === "number" ? value < want : null;
    default: return null;
  }
}

/** Rules that apply to the car itself (not to a deal) and are switched on. */
export function carRules(rules: RequirementRule[] | undefined): RequirementRule[] {
  return (rules ?? []).filter((r) => r.applies_to !== "deal" && r.enabled !== false && r.field);
}

export function evaluateBrief(rules: RequirementRule[] | undefined, car: SnapshotCar): Brief {
  const out: Brief = { status: "pass", failures: [], unknown: [], failedLabels: [], unknownLabels: [], rules: [] };
  for (const r of carRules(rules)) {
    const ok = checkRule(r, car);
    const label = r.short ?? r.label;
    out.rules.push({ id: r.id, label, ok });
    if (ok === false) { out.failures.push(r.id); out.failedLabels.push(label); }
    else if (ok === null) { out.unknown.push(r.id); out.unknownLabels.push(label); }
  }
  out.status = out.failures.length ? "fail" : out.unknown.length ? "unknown" : "pass";
  return out;
}

/** A pack the brief leans on: a rule the car meets only through a named pack. */
export interface BriefPack {
  field: string;
  label: string;
  pack: string;
  price: number | null;
}

/** The packs a car needs to meet the switched-on rules it passes via 'pack', with their prices where known. */
export function briefPacks(rules: RequirementRule[] | undefined, car: SnapshotCar): BriefPack[] {
  const out: BriefPack[] = [];
  const seen = new Set<string>();
  for (const r of carRules(rules)) {
    const field = r.field as string;
    const value = (car as unknown as Record<string, unknown>)[field];
    const pack = car.packs_required?.[field];
    if (value !== "pack" || !pack || seen.has(pack) || checkRule(r, car) !== true) continue;
    seen.add(pack);
    out.push({ field, label: r.short ?? r.label, pack, price: car.pack_prices_gbp?.[pack] ?? null });
  }
  return out;
}

/** The filter the Pick and Cars pages offer over the brief. */
export type BriefFilter = "pass" | "pass-or-unknown" | "all";

export function briefAllows(filter: BriefFilter, b: Brief): boolean {
  if (filter === "all") return true;
  if (filter === "pass") return b.status === "pass";
  return b.status !== "fail";
}

export const BRIEF_LABEL: Record<BriefStatus, string> = { pass: "meets the brief", fail: "fails the brief", unknown: "not confirmed" };
