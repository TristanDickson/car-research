// One filter set for every page: make, model, variant text, model year. It lives
// in the URL (?make=Hyundai&model=Kona&q=ultimate&year=2026) so a filtered view is
// a link, and moving between pages keeps it.
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

import { carName } from "./format";
import type { SnapshotCar, SnapshotOffer, SnapshotSpec } from "./types";

export interface Filters {
  make: string;
  model: string;
  q: string;
  year: string;
}

export const EMPTY: Filters = { make: "", model: "", q: "", year: "" };
const KEYS: (keyof Filters)[] = ["make", "model", "q", "year"];

export function filtersFrom(params: URLSearchParams | null): Filters {
  const f = { ...EMPTY };
  for (const k of KEYS) f[k] = params?.get(k) ?? "";
  return f;
}

export function isEmpty(f: Filters): boolean {
  return KEYS.every((k) => !f[k]);
}

export function useFilters(): [Filters, (patch: Partial<Filters>) => void] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const filters = useMemo(() => filtersFrom(params), [params]);
  const set = useCallback(
    (patch: Partial<Filters>) => {
      const next = new URLSearchParams(params?.toString() ?? "");
      for (const [k, v] of Object.entries(patch)) {
        if (v) next.set(k, v);
        else next.delete(k);
      }
      if ("make" in patch && patch.make !== filters.make) next.delete("model");
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, router, pathname, filters.make],
  );
  return [filters, set];
}

/** Filter-friendly link: keeps the current filters on a different page. */
export function withFilters(href: string, f: Filters): string {
  const p = new URLSearchParams();
  for (const k of KEYS) if (f[k]) p.set(k, f[k]);
  const qs = p.toString();
  return qs ? `${href}${href.includes("?") ? "&" : "?"}${qs}` : href;
}

const norm = (s: string | null | undefined) => (s ?? "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

/** 'Kona Electric' matches 'kona' and 'kona electric'; 'PV5 Passenger' matches 'pv5'. */
function modelMatches(model: string | null | undefined, wanted: string): boolean {
  if (!wanted) return true;
  const a = norm(model), b = norm(wanted);
  return a === b || a.startsWith(b + " ") || b.startsWith(a + " ") || a.split(" ")[0] === b.split(" ")[0];
}

export function carMatches(c: SnapshotCar, f: Filters): boolean {
  if (f.make && norm(c.make) !== norm(f.make)) return false;
  if (!modelMatches(c.model, f.model)) return false;
  if (f.year && String(c.model_year ?? "") !== f.year) return false;
  if (f.q) {
    const hay = norm(`${carName(c)} ${(c.packs ?? []).join(" ")} ${c.notes ?? ""}`);
    if (!hay.includes(norm(f.q))) return false;
  }
  return true;
}

export function specMatches(s: SnapshotSpec, f: Filters): boolean {
  if (f.make && norm(s.make) !== norm(f.make)) return false;
  if (!modelMatches(s.model, f.model)) return false;
  if (f.year && !(s.version_date ?? s.model_year_hint ?? "").startsWith(f.year)) return false;
  if (f.q) {
    const hay = norm(`${s.variant} ${s.trim} ${s.engine ?? ""} ${s.powertrain ?? ""} ${s.cap_id ?? ""}`);
    if (!hay.includes(norm(f.q))) return false;
  }
  return true;
}

export function offerMatches(o: SnapshotOffer, car: SnapshotCar | undefined, f: Filters): boolean {
  if (!car) return isEmpty(f);
  if (f.make && norm(car.make) !== norm(f.make)) return false;
  if (!modelMatches(car.model, f.model)) return false;
  if (f.year && String(car.model_year ?? "") !== f.year) return false;
  if (f.q) {
    const hay = norm(`${carName(car)} ${(car.packs ?? []).join(" ")} ${o.dealer ?? ""} ${o.source ?? ""} ${o.notes ?? ""}`);
    if (!hay.includes(norm(f.q))) return false;
  }
  return true;
}

export interface FilterOptions {
  makes: string[];
  models: string[];
  years: string[];
}

/** Choices for the bar, from whatever the page has loaded. Models narrow to the chosen make. */
export function filterOptions(cars: SnapshotCar[], specs: SnapshotSpec[], f: Filters): FilterOptions {
  const makes = new Set<string>();
  const models = new Set<string>();
  const years = new Set<string>();
  for (const c of cars) {
    makes.add(c.make);
    if (!f.make || norm(c.make) === norm(f.make)) models.add(c.model);
    if (c.model_year) years.add(String(c.model_year));
  }
  for (const s of specs) {
    makes.add(s.make);
    if (!f.make || norm(s.make) === norm(f.make)) models.add(s.model);
    const y = (s.version_date ?? s.model_year_hint ?? "").slice(0, 4);
    if (y) years.add(y);
  }
  // Collapse 'Kona' / 'Kona Electric' style duplicates onto the first word's longest form.
  const byHead = new Map<string, string>();
  for (const m of models) {
    const head = norm(m).split(" ")[0];
    const cur = byHead.get(head);
    if (!cur || m.length > cur.length) byHead.set(head, m);
  }
  return {
    makes: Array.from(makes).sort(),
    models: Array.from(byHead.values()).sort(),
    years: Array.from(years).sort().reverse(),
  };
}
