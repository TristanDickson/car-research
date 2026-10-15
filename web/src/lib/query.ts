// One query for every car view (cards, table, specs grid), bolthole-style:
//
//   text, make, model, year                 narrowing
//   ranges   key → [min, max]               numeric bounds on car fields and costs
//   facets   token → standard | listed | hide   tri-state chips over every equipment
//            flag, the routes a car can be had by, and whether a car is hand-curated
//   any      the wanted chips marked 'or'   every other wanted chip must hold, and at least one of these
//   keepUnknown                             a car no source has a value for passes a bound or chip
//                                           (otherwise it is left out, and the bar counts how many)
//   firm                                    true costs leave out the figures resting on few used cars
//   sort
//
// It lives in the URL so a view is a link and moving between views keeps it. A
// saved search is this query with a name (lib/db.ts settings); the default one is
// what a search view opens on when the app loads. Evaluation is pure:
// `matches(car, ctx, query)` where ctx carries what the car record does not (its costs).
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo } from "react";

import type { CarCosts } from "./costs";
import { FIELD_BY_KEY, RANGE_FIELDS, show } from "./fields";
import { carName, sortName } from "./format";
import type { SnapshotCar } from "./types";

export type FacetState = "off" | "standard" | "listed" | "hide";

/** A range bound's key is a field key (lib/fields.ts): every number and amount a car carries or costs. */
export type RangeKey = string;
export type Range = [number | null, number | null];

export interface Query {
  q: string;
  make: string;
  model: string;
  year: string;
  ranges: Record<RangeKey, Range>;
  /** Equipment that must be standard (`standard`), standard or an option (`listed`), or absent (`hide`). */
  facets: Record<string, FacetState>;
  /** Wanted chips marked 'or': at least one must hold, beside every wanted chip not marked, which must all hold. */
  any: string[];
  /** Keep a car whose value for a bounded field or a required chip no source gives. */
  keepUnknown: boolean;
  /** Cost each car on its figures that rest on enough used cars, leaving out those marked "few cars". */
  firm: boolean;
  sort: string;
}

export const EMPTY_QUERY: Query = { q: "", make: "", model: "", year: "", ranges: {}, facets: {}, any: [], keepUnknown: false, firm: false, sort: "" };

const wantedState = (s: FacetState | undefined) => s === "standard" || s === "listed";

/** The non-equipment facets. Equipment facets are `flag:<key>` for every canonical flag the snapshot names. */
export const FIXED_FACETS: { token: string; label: string; group: string; twoState?: boolean }[] = [
  { token: "route:cash", label: "Cash price", group: "Can be had by", twoState: true },
  { token: "route:pcp", label: "PCP", group: "Can be had by", twoState: true },
  { token: "route:pch", label: "Lease", group: "Can be had by", twoState: true },
  { token: "route:used", label: "Used example", group: "Can be had by", twoState: true },
  { token: "priced", label: "Any current price", group: "Can be had by", twoState: true },
  { token: "on_sale", label: "On sale now", group: "Can be had by", twoState: true },
  { token: "curated", label: "Hand-curated", group: "Provenance", twoState: true },
];

/** Equipment flags grouped for the panel; anything the snapshot names that is not listed lands in 'Other'. */
export const FLAG_GROUPS: Record<string, string[]> = {
  Essentials: ["heat_pump", "v2l_internal", "v2l_external", "v2l_any"],
  Comfort: ["heated_front_seats", "heated_rear_seats", "ventilated_seats", "heated_steering_wheel", "memory_seats", "electric_seats", "glass_roof", "wireless_charging", "keyless", "digital_key", "rear_privacy_glass"],
  Driving: ["adaptive_cruise", "blind_spot", "camera_360", "hud", "led_headlights", "matrix_led", "powered_tailgate", "powered_sliding_doors", "tow_prep"],
};

export function parseQuery(params: URLSearchParams | null): Query {
  const f: Query = { ...EMPTY_QUERY, ranges: {}, facets: {}, any: [] };
  if (!params) return f;
  for (const k of ["q", "make", "model", "year", "sort"] as const) f[k] = params.get(k) ?? "";
  f.keepUnknown = params.get("unknown") === "keep";
  f.firm = params.get("figures") === "firm";
  for (const { key } of RANGE_FIELDS) {
    const v = params.get(`r.${key}`);
    if (!v) continue;
    // '-500-' is a negative minimum: split at the dash that follows a digit or the start.
    const m = /^(-?[\d.]*)-(-?[\d.]*)$/.exec(v);
    if (!m) continue;
    const [lo, hi] = [m[1], m[2]];
    const n = (s: string | undefined) => (s === undefined || s === "" ? null : Number.isFinite(Number(s)) ? Number(s) : null);
    const r: Range = [n(lo), n(hi)];
    if (r[0] != null || r[1] != null) f.ranges[key] = r;
  }
  for (const state of ["standard", "listed", "hide"] as const) {
    for (const tok of (params.get(state) ?? "").split(",").filter(Boolean)) f.facets[tok] = state;
  }
  // An older link's mode=any put every wanted chip in the 'or' group.
  const any = params.get("mode") === "any" ? Object.keys(f.facets) : (params.get("any") ?? "").split(",");
  f.any = [...new Set(any.filter((t) => wantedState(f.facets[t])))].sort();
  return f;
}

export function serializeQuery(f: Query): string {
  const p = new URLSearchParams();
  for (const k of ["q", "make", "model", "year", "sort"] as const) if (f[k]) p.set(k, f[k]);
  if (f.keepUnknown) p.set("unknown", "keep");
  if (f.firm) p.set("figures", "firm");
  for (const { key } of RANGE_FIELDS) {
    const r = f.ranges[key];
    if (r && (r[0] != null || r[1] != null)) p.set(`r.${key}`, `${r[0] ?? ""}-${r[1] ?? ""}`);
  }
  for (const state of ["standard", "listed", "hide"] as const) {
    const toks = Object.entries(f.facets).filter(([, s]) => s === state).map(([t]) => t).sort();
    if (toks.length) p.set(state, toks.join(","));
  }
  const any = [...new Set(f.any.filter((t) => wantedState(f.facets[t])))].sort();
  if (any.length) p.set("any", any.join(","));
  return p.toString();
}

/** A query string in its one canonical spelling (key order, encoding), so two spellings of a search compare equal. */
export const canonical = (qs: string): string => serializeQuery(parseQuery(new URLSearchParams(qs)));

/** Anything narrowed at all. */
export function isNarrowed(f: Query): boolean {
  return !!(f.q || f.make || f.model || f.year || Object.keys(f.ranges).length || Object.keys(f.facets).length);
}

// The search a view opens on when its URL carries none: the last one used in this
// app load, else the reader's default saved search (set by the search views once
// the saved searches are read). Module state, so it follows the reader across views
// and starts again from the default on a reload.
let current: string | null = null;

/** The query in the URL, or the one a view should open on; `ready` is false until that is known. */
export function useQuery(defaultQs?: string | null): [Query, (patch: Partial<Query>) => void, boolean] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = params?.toString() ?? "";
  const known = defaultQs !== undefined;   // the saved searches have been read
  const effective = raw || (current ?? (known ? defaultQs ?? "" : null));
  const query = useMemo(() => parseQuery(new URLSearchParams(effective ?? "")), [effective]);
  useEffect(() => {
    if (effective === null) return;
    current = effective;
    if (!raw && effective) router.replace(`${pathname}?${effective}`, { scroll: false });
  }, [effective, raw, pathname, router]);
  const set = useCallback(
    (patch: Partial<Query>) => {
      const next: Query = { ...query, ...patch };
      if ("make" in patch && !("model" in patch) && patch.make !== query.make) next.model = "";
      const qs = serializeQuery(next);
      current = qs;
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname, query],
  );
  return [query, set, effective !== null];
}

/** Replace the whole query with a saved one. */
export const loaded = (qs: string): Partial<Query> => parseQuery(new URLSearchParams(qs));

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
  return { facets, any: wantedState(next) ? f.any : f.any.filter((t) => t !== token) };
}

/** Mark a wanted chip 'or' (one of the group must hold) or back to 'and' (it must hold). */
export function toggleAny(f: Query, token: string): Partial<Query> {
  return { any: f.any.includes(token) ? f.any.filter((t) => t !== token) : [...f.any, token].sort() };
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
  costs: CarCosts;
}

function rangeValue(key: RangeKey, c: SnapshotCar, ctx: CarContext): number | null {
  const v = FIELD_BY_KEY.get(key)?.value(c, ctx.costs);
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** Does the car have the facet, and if so how: 'standard', 'option' (listed as an option or in a pack),
 * 'listed' (standard or an option, the source does not say which), or null. */
export function facetValue(token: string, c: SnapshotCar, ctx: CarContext): "standard" | "option" | "listed" | null {
  if (token.startsWith("flag:")) {
    const v = c.flags?.[token.slice(5)];
    return v === "standard" ? "standard" : v === "option" || v === "pack" ? "option" : v === "listed" ? "listed" : null;
  }
  if (token.startsWith("route:")) return ctx.costs.byRoute[token.slice(6) as keyof CarCosts["byRoute"]] ? "standard" : null;
  switch (token) {
    case "priced": return ctx.costs.trueCost ? "standard" : null;
    case "curated": return c.auto ? null : "standard";
    case "on_sale": return c.on_sale ? "standard" : null;
  }
  return null;
}

/** Does any source say whether the car has it ('none' is an answer; no value is not)? Asked for it as standard,
 * 'standard or an option' is not an answer either. */
function facetKnown(token: string, c: SnapshotCar, state: FacetState): boolean {
  if (!token.startsWith("flag:")) return true;
  const v = c.flags?.[token.slice(5)];
  return v != null && !(state === "standard" && v === "listed");
}

function facetHolds(state: FacetState, value: "standard" | "option" | "listed" | null): boolean {
  if (state === "standard") return value === "standard";
  if (state === "listed") return value !== null;
  return true;
}

export function matches(c: SnapshotCar, ctx: CarContext, f: Query): boolean {
  if (f.make && norm(c.make) !== norm(f.make)) return false;
  if (!modelMatches(c.model, f.model)) return false;
  if (f.year && String(c.model_year ?? "") !== f.year) return false;
  if (f.q) {
    const hay = norm([sortName(c), c.variant, (c.packs ?? []).join(" "), c.notes, c.body, c.drive, c.segment, c.platform, c.battery_chemistry, c.charge_port, c.cap_name].filter(Boolean).join(" "));
    if (!hay.includes(norm(f.q))) return false;
  }
  for (const [key, r] of Object.entries(f.ranges)) {
    const v = rangeValue(key, c, ctx);
    if (v == null) {
      if (f.keepUnknown) continue;
      return false;
    }
    if (r[0] != null && v < r[0]) return false;
    if (r[1] != null && v > r[1]) return false;
  }
  for (const [tok, s] of Object.entries(f.facets)) {
    if (s === "hide" && facetValue(tok, c, ctx) !== null) return false;
  }
  const holds = ([tok, s]: [string, FacetState]) => facetHolds(s, facetValue(tok, c, ctx)) || (f.keepUnknown && !facetKnown(tok, c, s));
  const wanted = Object.entries(f.facets).filter(([, s]) => wantedState(s));
  if (!wanted.filter(([t]) => !f.any.includes(t)).every(holds)) return false;
  const anyOf = wanted.filter(([t]) => f.any.includes(t));
  return !anyOf.length || anyOf.some(holds);
}

export interface QueryOptions {
  makes: string[];
  models: string[];
  years: string[];
}

/** Choices for the bar; models narrow to the chosen make. */
export function queryOptions(cars: SnapshotCar[], f: Query): QueryOptions {
  const makes = new Set<string>(), models = new Set<string>(), years = new Set<string>();
  for (const c of cars) {
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
    case "fell": return ctx.costs.trend?.delta ?? null;
    case "range": return c.wltp_range_mi == null ? null : -c.wltp_range_mi;
    case "seats": return c.seats == null ? null : -c.seats;
    case "name": return sortName(c);
    default: return k.trueCost?.monthly ?? null;
  }
}

export function compareBy(sort: string, ctxOf: (c: SnapshotCar) => CarContext) {
  return (a: SnapshotCar, b: SnapshotCar): number => {
    const ka = sortKey(sort, a, ctxOf(a)), kb = sortKey(sort, b, ctxOf(b));
    if (ka == null && kb == null) return sortName(a).localeCompare(sortName(b));
    if (ka == null) return 1;
    if (kb == null) return -1;
    return typeof ka === "number" && typeof kb === "number" ? ka - kb : String(ka).localeCompare(String(kb));
  };
}

// ---------------------------------------------------------------- packs and words

/** The car field packs_required names a flag under (the car record keeps its own names for three). */
const PACK_FIELD: Record<string, string> = { v2l_internal: "internal_v2l", v2l_external: "external_v2l" };

export interface SearchPack {
  flag: string;
  pack: string;
  price: number | null;
}

/** The packs a car needs to have the equipment the search asks for: a wanted chip the car meets only through a pack. */
export function searchPacks(f: Query, c: SnapshotCar): SearchPack[] {
  const out: SearchPack[] = [];
  const seen = new Set<string>();
  for (const [tok, state] of Object.entries(f.facets)) {
    if (!tok.startsWith("flag:") || state !== "listed") continue;
    const flag = tok.slice(5);
    if (c.flags?.[flag] !== "pack") continue;
    const pack = c.packs_required?.[PACK_FIELD[flag] ?? flag] ?? c.packs_required?.[flag];
    if (!pack || seen.has(`${pack}|${flag}`)) continue;
    seen.add(`${pack}|${flag}`);
    out.push({ flag, pack, price: c.pack_prices_gbp?.[pack] ?? null });
  }
  return out;
}

/** Every pack the car's equipment leans on, with what each one brings: 'Tech Pack' → [cabin socket, digital key]. */
export function carPacks(c: SnapshotCar): { pack: string; price: number | null; flags: string[] }[] {
  const by = new Map<string, string[]>();
  const fieldToFlag: Record<string, string> = Object.fromEntries(Object.entries(PACK_FIELD).map(([k, v]) => [v, k]));
  for (const [field, pack] of Object.entries(c.packs_required ?? {})) {
    if (!pack) continue;
    const flag = fieldToFlag[field] ?? field;
    if (flag === "v2l_any") continue;
    by.set(pack, [...(by.get(pack) ?? []), flag]);
  }
  return [...by.entries()].map(([pack, flags]) => ({ pack, price: c.pack_prices_gbp?.[pack] ?? null, flags }));
}

const STATE_WORDS: Record<FacetState, string> = { off: "", standard: "standard", listed: "standard, pack or option", hide: "not" };

/** A search in a line of words: 'Heat pump: standard, pack or option · Seats ≥ 4 · sorted by name'. */
export function describeQuery(f: Query, flagLabels: Record<string, string>): string {
  const parts: string[] = [];
  if (f.make) parts.push(f.model ? `${f.make} ${f.model}` : f.make);
  else if (f.model) parts.push(f.model);
  if (f.year) parts.push(`model year ${f.year}`);
  if (f.q) parts.push(`“${f.q}”`);
  const fixed = Object.fromEntries(FIXED_FACETS.map((x) => [x.token, x.label]));
  const all: string[] = [], anyOf: string[] = [];
  for (const [tok, state] of Object.entries(f.facets)) {
    const label = tok.startsWith("flag:") ? flagLabels[tok.slice(5)] ?? tok.slice(5).replaceAll("_", " ") : fixed[tok] ?? tok;
    if (state === "hide") {
      parts.push(`not ${label.toLowerCase()}`);
      continue;
    }
    const words = FIXED_FACETS.some((x) => x.token === tok && x.twoState) ? label : `${label}: ${STATE_WORDS[state]}`;
    (f.any.includes(tok) ? anyOf : all).push(words);
  }
  if (all.length) parts.push(all.join(" · "));
  if (anyOf.length) parts.push(anyOf.length === 1 ? anyOf[0] : `one of (${anyOf.join(" or ")})`);
  if (f.firm) parts.push("figures on few or no used cars left out");
  for (const r of RANGE_FIELDS) {
    const b = f.ranges[r.key];
    if (!b) continue;
    const v = (n: number) => show(r, n);
    if (b[0] != null && b[1] != null) parts.push(`${r.label} ${v(b[0])}–${v(b[1])}`);
    else if (b[0] != null) parts.push(`${r.label} ≥ ${v(b[0])}`);
    else if (b[1] != null) parts.push(`${r.label} ≤ ${v(b[1])}`);
  }
  const sort = SORTS.find((x) => x.key === (f.sort || "true"));
  if (f.sort && sort) parts.push(`sorted by ${sort.label}`);
  return parts.length ? parts.join(" · ") : "every car";
}
