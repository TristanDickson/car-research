// One query for every car view (cards, table, specs grid), bolthole-style:
//
//   text, make, model, year, scope          narrowing
//   ranges   key → [min, max]               numeric bounds on car fields and costs
//   facets   token → standard | listed | hide   tri-state chips over every equipment
//            flag, the routes a car can be had by, and a few booleans
//   mode     all | any                      how the 'standard'/'listed' chips combine
//   brief    pass | pass-or-unknown | all   the reader's hard rules (lib/brief.ts)
//   sort
//
// It lives in the URL so a view is a link and moving between views keeps it.
// Evaluation is pure: `matches(car, ctx, query)` where ctx carries what the
// car record does not (its brief verdict, its costs).
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

import type { Brief, BriefFilter } from "./brief";
import type { CarCosts } from "./costs";
import { carName } from "./format";
import type { SnapshotCar } from "./types";

export type FacetState = "off" | "standard" | "listed" | "hide";
export type Mode = "all" | "any";

export const RANGE_KEYS = ["true", "cash", "monthly", "list", "range", "battery", "seats", "width", "length", "boot", "power", "dc", "year"] as const;
export type RangeKey = (typeof RANGE_KEYS)[number];
export type Range = [number | null, number | null];

export const RANGES: { key: RangeKey; label: string; unit: string; step?: number }[] = [
  { key: "true", label: "True £/month", unit: "£", step: 10 },
  { key: "cash", label: "Cash price", unit: "£", step: 500 },
  { key: "monthly", label: "Pay monthly", unit: "£", step: 10 },
  { key: "list", label: "List price", unit: "£", step: 500 },
  { key: "range", label: "WLTP range", unit: "mi", step: 10 },
  { key: "battery", label: "Battery", unit: "kWh" },
  { key: "seats", label: "Seats", unit: "" },
  { key: "width", label: "Width", unit: "mm", step: 10 },
  { key: "length", label: "Length", unit: "mm", step: 10 },
  { key: "boot", label: "Boot", unit: "L", step: 10 },
  { key: "power", label: "Power", unit: "hp", step: 10 },
  { key: "dc", label: "DC charge (peak, else 10–80% avg)", unit: "kW", step: 10 },
  { key: "year", label: "Model year", unit: "" },
];

export interface Query {
  scope: "" | "all";
  q: string;
  make: string;
  model: string;
  year: string;
  ranges: Partial<Record<RangeKey, Range>>;
  /** Equipment that must be standard (`standard`), standard or an option (`listed`), or absent (`hide`). */
  facets: Record<string, FacetState>;
  mode: Mode;
  brief: BriefFilter;
  sort: string;
}

export const EMPTY_QUERY: Query = { scope: "", q: "", make: "", model: "", year: "", ranges: {}, facets: {}, mode: "all", brief: "pass-or-unknown", sort: "" };

/** The non-equipment facets. Equipment facets are `flag:<key>` for every canonical flag the snapshot names. */
export const FIXED_FACETS: { token: string; label: string; group: string; twoState?: boolean }[] = [
  { token: "route:cash", label: "Cash price", group: "Can be had by", twoState: true },
  { token: "route:pcp", label: "PCP", group: "Can be had by", twoState: true },
  { token: "route:pch", label: "Lease", group: "Can be had by", twoState: true },
  { token: "route:used", label: "Used example", group: "Can be had by", twoState: true },
  { token: "priced", label: "Any current price", group: "Can be had by", twoState: true },
  { token: "curated", label: "Hand-curated", group: "Provenance", twoState: true },
  { token: "starred", label: "On my shortlist", group: "Provenance", twoState: true },
  { token: "packs", label: "Needs a pack for the brief", group: "Provenance", twoState: true },
];

/** Equipment flags grouped for the panel; anything the snapshot names that is not listed lands in 'Other'. */
export const FLAG_GROUPS: Record<string, string[]> = {
  "The brief": ["heat_pump", "v2l_internal", "v2l_external", "v2l_any"],
  Comfort: ["heated_front_seats", "heated_rear_seats", "ventilated_seats", "heated_steering_wheel", "memory_seats", "electric_seats", "glass_roof", "wireless_charging", "keyless", "digital_key", "rear_privacy_glass"],
  Driving: ["adaptive_cruise", "blind_spot", "camera_360", "hud", "led_headlights", "matrix_led", "powered_tailgate", "powered_sliding_doors", "tow_prep"],
};

const KEYS: (keyof Query)[] = ["scope", "q", "make", "model", "year", "mode", "brief", "sort"];

export function parseQuery(params: URLSearchParams | null): Query {
  const f: Query = { ...EMPTY_QUERY, ranges: {}, facets: {} };
  if (!params) return f;
  f.scope = params.get("scope") === "all" ? "all" : "";
  for (const k of ["q", "make", "model", "year", "sort"] as const) f[k] = params.get(k) ?? "";
  f.mode = params.get("mode") === "any" ? "any" : "all";
  const b = params.get("brief");
  f.brief = b === "pass" || b === "all" || b === "pass-or-unknown" ? b : "pass-or-unknown";
  for (const key of RANGE_KEYS) {
    const v = params.get(`r.${key}`);
    if (!v) continue;
    const [lo, hi] = v.split("-", 2);
    const n = (s: string | undefined) => (s === undefined || s === "" ? null : Number.isFinite(Number(s)) ? Number(s) : null);
    const r: Range = [n(lo), n(hi)];
    if (r[0] != null || r[1] != null) f.ranges[key] = r;
  }
  for (const state of ["standard", "listed", "hide"] as const) {
    for (const tok of (params.get(state) ?? "").split(",").filter(Boolean)) f.facets[tok] = state;
  }
  return f;
}

export function serializeQuery(f: Query): string {
  const p = new URLSearchParams();
  if (f.scope) p.set("scope", f.scope);
  for (const k of ["q", "make", "model", "year", "sort"] as const) if (f[k]) p.set(k, f[k]);
  if (f.mode !== "all") p.set("mode", f.mode);
  if (f.brief !== EMPTY_QUERY.brief) p.set("brief", f.brief);
  for (const key of RANGE_KEYS) {
    const r = f.ranges[key];
    if (r && (r[0] != null || r[1] != null)) p.set(`r.${key}`, `${r[0] ?? ""}-${r[1] ?? ""}`);
  }
  for (const state of ["standard", "listed", "hide"] as const) {
    const toks = Object.entries(f.facets).filter(([, s]) => s === state).map(([t]) => t).sort();
    if (toks.length) p.set(state, toks.join(","));
  }
  return p.toString();
}

/** No narrowing beyond the scope and the default brief. */
export function isNarrowed(f: Query): boolean {
  return !!(f.q || f.make || f.model || f.year || Object.keys(f.ranges).length || Object.keys(f.facets).length || f.brief !== EMPTY_QUERY.brief);
}

export const allCars = (f: Query) => f.scope === "all";

export function useQuery(): [Query, (patch: Partial<Query>) => void] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const query = useMemo(() => parseQuery(params), [params]);
  const set = useCallback(
    (patch: Partial<Query>) => {
      const next: Query = { ...query, ...patch };
      if ("make" in patch && patch.make !== query.make) next.model = "";
      const qs = serializeQuery(next);
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, router, pathname, query], // eslint-disable-line react-hooks/exhaustive-deps
  );
  return [query, set];
}

/** The same query on another view. */
export function withQuery(href: string, f: Query): string {
  const qs = serializeQuery(f);
  return qs ? `${href}${href.includes("?") ? "&" : "?"}${qs}` : href;
}

/** Cycle a facet: off → standard → listed → hide → off; a two-state facet skips 'listed'. */
export function cycleFacet(f: Query, token: string, twoState = false): Partial<Query> {
  const cur = f.facets[token] ?? "off";
  const order: FacetState[] = twoState ? ["off", "standard", "hide"] : ["off", "standard", "listed", "hide"];
  const next = order[(order.indexOf(cur) + 1) % order.length];
  const facets = { ...f.facets };
  if (next === "off") delete facets[token];
  else facets[token] = next;
  return { facets };
}

const norm = (s: string | null | undefined) => (s ?? "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

/** 'Kona Electric' matches 'kona' and 'kona electric'; 'PV5 Passenger' matches 'pv5'. */
function modelMatches(model: string | null | undefined, wanted: string): boolean {
  if (!wanted) return true;
  const a = norm(model), b = norm(wanted);
  return a === b || a.startsWith(b + " ") || b.startsWith(a + " ") || a.split(" ")[0] === b.split(" ")[0];
}

/** What the car record does not carry but a query may ask about. */
export interface CarContext {
  brief: Brief;
  costs: CarCosts;
  starred: boolean;
}

function rangeValue(key: RangeKey, c: SnapshotCar, ctx: CarContext): number | null | undefined {
  switch (key) {
    case "true": return ctx.costs.trueCost?.monthly ?? null;
    case "cash": return ctx.costs.cash?.price ?? null;
    case "monthly": return ctx.costs.monthly;
    case "list": return c.list_price_gbp;
    case "range": return c.wltp_range_mi;
    case "battery": return c.battery_kwh;
    case "seats": return c.seats;
    case "width": return c.width_mm;
    case "length": return c.length_mm;
    case "boot": return c.boot_l;
    case "power": return c.power_hp;
    case "dc": return c.dc_peak_kw ?? c.dc_avg_kw;
    case "year": return c.model_year;
  }
}

/** Does the car have the facet, and if so how: 'standard', 'option' (listed as an option or in a pack), or null. */
export function facetValue(token: string, c: SnapshotCar, ctx: CarContext): "standard" | "option" | null {
  if (token.startsWith("flag:")) {
    const v = c.flags?.[token.slice(5)];
    return v === "standard" ? "standard" : v === "option" ? "option" : null;
  }
  if (token.startsWith("route:")) return ctx.costs.byRoute[token.slice(6) as keyof CarCosts["byRoute"]] ? "standard" : null;
  switch (token) {
    case "priced": return ctx.costs.trueCost ? "standard" : null;
    case "curated": return c.auto ? null : "standard";
    case "starred": return ctx.starred ? "standard" : null;
    case "packs": return c.packs_required && Object.keys(c.packs_required).length ? "standard" : null;
  }
  return null;
}

function facetHolds(state: FacetState, value: "standard" | "option" | null): boolean {
  if (state === "standard") return value === "standard";
  if (state === "listed") return value !== null;
  return true;
}

export function matches(c: SnapshotCar, ctx: CarContext, f: Query): boolean {
  if (!allCars(f) && c.auto) return false;
  if (f.make && norm(c.make) !== norm(f.make)) return false;
  if (!modelMatches(c.model, f.model)) return false;
  if (f.year && String(c.model_year ?? "") !== f.year) return false;
  if (f.q) {
    const hay = norm(`${carName(c)} ${c.variant ?? ""} ${(c.packs ?? []).join(" ")} ${c.notes ?? ""} ${c.body ?? ""}`);
    if (!hay.includes(norm(f.q))) return false;
  }
  if (f.brief === "pass" && ctx.brief.status !== "pass") return false;
  if (f.brief === "pass-or-unknown" && ctx.brief.status === "fail") return false;
  for (const [key, r] of Object.entries(f.ranges) as [RangeKey, Range][]) {
    const v = rangeValue(key, c, ctx);
    if (v == null) return false;
    if (r[0] != null && v < r[0]) return false;
    if (r[1] != null && v > r[1]) return false;
  }
  const wanted = Object.entries(f.facets).filter(([, s]) => s === "standard" || s === "listed");
  for (const [tok, s] of Object.entries(f.facets)) {
    if (s === "hide" && facetValue(tok, c, ctx) !== null) return false;
  }
  if (wanted.length) {
    const holds = wanted.map(([tok, s]) => facetHolds(s, facetValue(tok, c, ctx)));
    if (f.mode === "all" ? !holds.every(Boolean) : !holds.some(Boolean)) return false;
  }
  return true;
}

export interface QueryOptions {
  makes: string[];
  models: string[];
  years: string[];
}

/** Choices for the bar, within the scope; models narrow to the chosen make. */
export function queryOptions(cars: SnapshotCar[], f: Query): QueryOptions {
  const makes = new Set<string>(), models = new Set<string>(), years = new Set<string>();
  for (const c of cars) {
    if (!allCars(f) && c.auto) continue;
    makes.add(c.make);
    if (!f.make || norm(c.make) === norm(f.make)) models.add(c.model);
    if (c.model_year) years.add(String(c.model_year));
  }
  const byHead = new Map<string, string>();
  for (const m of models) {
    const head = norm(m).split(" ")[0];
    const cur = byHead.get(head);
    if (!cur || m.length > cur.length) byHead.set(head, m);
  }
  return { makes: Array.from(makes).sort(), models: Array.from(byHead.values()).sort(), years: Array.from(years).sort().reverse() };
}

export type SortKey = "true" | "monthly" | "threeYear" | "cash" | "fell" | "range" | "seats" | "name";
export const SORTS: { key: SortKey; label: string }[] = [
  { key: "true", label: "cheapest true cost per month" },
  { key: "monthly", label: "cheapest to pay monthly" },
  { key: "threeYear", label: "cheapest over the agreement" },
  { key: "cash", label: "cheapest to buy" },
  { key: "fell", label: "biggest price fall, 30 days" },
  { key: "range", label: "longest range" },
  { key: "seats", label: "most seats" },
  { key: "name", label: "name" },
];

export function sortKey(sort: string, c: SnapshotCar, ctx: CarContext): number | string | null {
  const k = ctx.costs;
  switch (sort as SortKey) {
    case "monthly": return k.monthly;
    case "threeYear": return k.threeYear;
    case "cash": return k.cash?.price ?? null;
    case "fell": return c.deal_summary.trend?.delta ?? null;
    case "range": return c.wltp_range_mi == null ? null : -c.wltp_range_mi;
    case "seats": return c.seats == null ? null : -c.seats;
    case "name": return carName(c);
    default: return k.trueCost?.monthly ?? null;
  }
}

export function compareBy(sort: string, ctxOf: (c: SnapshotCar) => CarContext) {
  return (a: SnapshotCar, b: SnapshotCar): number => {
    const ka = sortKey(sort, a, ctxOf(a)), kb = sortKey(sort, b, ctxOf(b));
    if (ka == null && kb == null) return carName(a).localeCompare(carName(b));
    if (ka == null) return 1;
    if (kb == null) return -1;
    return typeof ka === "number" && typeof kb === "number" ? ka - kb : String(ka).localeCompare(String(kb));
  };
}
