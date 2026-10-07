"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import type { BriefFilter } from "@/lib/brief";
import { allCars, cycleFacet, EMPTY_QUERY, FIXED_FACETS, FLAG_GROUPS, isNarrowed, RANGES, SORTS, withQuery, type FacetState, type Query, type QueryOptions, type Range, type RangeKey } from "@/lib/query";

const VIEWS = [
  { href: "/", label: "Cards" },
  { href: "/cars", label: "Table" },
  { href: "/specs", label: "Specs grid" },
];

interface Props {
  query: Query;
  set: (patch: Partial<Query>) => void;
  options: QueryOptions;
  flagLabels: Record<string, string>;
  count: string;
  /** How many generated cars 'Every EV' would add. */
  nAuto: number;
}

const sel = "rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100";
const seg = (on: boolean) => `px-2.5 py-1 ${on ? "bg-gray-700 text-gray-100" : "text-gray-400 hover:text-gray-100"}`;

const STATE_LABEL: Record<FacetState, string> = { off: "", standard: "standard", listed: "std or option", hide: "hidden" };
const STATE_CLASS: Record<FacetState, string> = {
  off: "border-gray-700 text-gray-300 hover:border-gray-500",
  standard: "border-emerald-500 bg-emerald-950/40 text-emerald-200",
  listed: "border-sky-500 bg-sky-950/40 text-sky-200",
  hide: "border-rose-500 bg-rose-950/40 text-rose-200 line-through",
};

/**
 * The one search for every car view. The top row narrows (scope, make,
 * model, text, year), judges (the brief), orders (sort) and switches view;
 * the panel below it holds every facet as a tri-state chip (standard → std or
 * option → hidden, all of them combined with 'all' or 'any') and a min/max for
 * every number a car carries. The whole state is the URL.
 */
export function QueryBar({ query: f, set, options, flagLabels, count, nAuto }: Props) {
  const pathname = usePathname() ?? "/";
  const [open, setOpen] = useState(isNarrowed(f) && (Object.keys(f.facets).length > 0 || Object.keys(f.ranges).length > 0));
  const withCurrent = (list: string[], cur: string) => (cur && !list.includes(cur) ? [cur, ...list] : list);
  const makes = withCurrent(options.makes, f.make), models = withCurrent(options.models, f.model), years = withCurrent(options.years, f.year);
  const active = Object.keys(f.facets).length + Object.keys(f.ranges).length;

  const grouped = new Map<string, { token: string; label: string; twoState?: boolean }[]>();
  for (const fx of FIXED_FACETS) grouped.set(fx.group, [...(grouped.get(fx.group) ?? []), fx]);
  const placed = new Set<string>();
  for (const [group, keys] of Object.entries(FLAG_GROUPS)) {
    for (const k of keys) {
      if (!flagLabels[k]) continue;
      placed.add(k);
      grouped.set(group, [...(grouped.get(group) ?? []), { token: `flag:${k}`, label: flagLabels[k] }]);
    }
  }
  for (const [k, label] of Object.entries(flagLabels)) {
    if (!placed.has(k)) grouped.set("Other equipment", [...(grouped.get("Other equipment") ?? []), { token: `flag:${k}`, label }]);
  }
  const order = ["The brief", "Can be had by", "Comfort", "Driving", "Other equipment", "Provenance"];
  const groups = [...grouped.entries()].sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]));

  const setRange = (key: RangeKey, i: 0 | 1, v: string) => {
    const cur: Range = f.ranges[key] ?? [null, null];
    const next: Range = [cur[0], cur[1]];
    next[i] = v === "" ? null : Number(v);
    const ranges = { ...f.ranges };
    if (next[0] == null && next[1] == null) delete ranges[key];
    else ranges[key] = next;
    set({ ranges });
  };

  return (
    <div className="mb-4 space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="View" className="flex overflow-hidden rounded border border-gray-700 bg-gray-900">
          {VIEWS.map((v) => (
            <Link key={v.href} href={withQuery(v.href, f)} className={seg(pathname.replace(/\/+$/, "") === v.href.replace(/\/+$/, "") || (v.href === "/" && pathname === "/"))}>
              {v.label}
            </Link>
          ))}
        </div>
        {nAuto > 0 && (
          <div role="group" aria-label="Scope" className="flex overflow-hidden rounded border border-gray-700 bg-gray-900">
            <button type="button" className={seg(!allCars(f))} onClick={() => set({ scope: "" })} title="The trims curated by hand">Shortlist</button>
            <button type="button" className={seg(allCars(f))} onClick={() => set({ scope: "all" })} title={`Every EV on sale: ${nAuto} more derivatives`}>Every EV</button>
          </div>
        )}
        <select aria-label="Make" value={f.make} onChange={(e) => set({ make: e.target.value })} className={sel}>
          <option value="">All makes</option>
          {makes.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <select aria-label="Model" value={f.model} onChange={(e) => set({ model: e.target.value })} className={sel}>
          <option value="">All models</option>
          {models.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <input aria-label="Search text" value={f.q} onChange={(e) => set({ q: e.target.value })} placeholder="Trim, variant, pack…" className={`${sel} w-44`} />
        <select aria-label="Model year" value={f.year} onChange={(e) => set({ year: e.target.value })} className={sel}>
          <option value="">Any year</option>
          {years.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <select aria-label="Brief" value={f.brief} onChange={(e) => set({ brief: e.target.value as BriefFilter })} className={sel} title="Your hard requirements (Requirements page)">
          <option value="pass">meets the brief, confirmed</option>
          <option value="pass-or-unknown">meets it or not yet confirmed</option>
          <option value="all">any car</option>
        </select>
        <select aria-label="Sort" value={f.sort || "true"} onChange={(e) => set({ sort: e.target.value === "true" ? "" : e.target.value })} className={sel}>
          {SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
        </select>
        <button type="button" onClick={() => setOpen((o) => !o)} className={`rounded border px-2.5 py-1 ${active ? "border-sky-600 text-sky-200" : "border-gray-700 text-gray-300 hover:text-gray-100"}`}>
          {open ? "Hide filters" : "Filters"}{active ? ` · ${active}` : ""}
        </button>
        {isNarrowed(f) && (
          <button type="button" onClick={() => set({ ...EMPTY_QUERY, scope: f.scope, sort: f.sort })} className="text-gray-400 hover:text-gray-100">clear</button>
        )}
        <span className="text-gray-500">{count}</span>
      </div>

      {open && (
        <div className="rounded-lg border border-gray-800 bg-gray-900 p-3">
          <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-gray-400">
            <span>Click a chip: <span className="text-emerald-200">standard</span> → <span className="text-sky-200">standard or option</span> → <span className="text-rose-200">hidden</span> → off.</span>
            <span className="flex items-center gap-1">
              Wanted chips must
              <span className="flex overflow-hidden rounded border border-gray-700">
                <button type="button" className={seg(f.mode === "all")} onClick={() => set({ mode: "all" })}>all hold</button>
                <button type="button" className={seg(f.mode === "any")} onClick={() => set({ mode: "any" })}>any hold</button>
              </span>
            </span>
          </div>
          <div className="grid gap-4 lg:grid-cols-[1fr_minmax(16rem,22rem)]">
            <div className="space-y-3">
              {groups.map(([group, facets]) => (
                <div key={group}>
                  <div className="mb-1 text-xs uppercase tracking-wide text-gray-500">{group}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {facets.map((fx) => {
                      const state = f.facets[fx.token] ?? "off";
                      return (
                        <button key={fx.token} type="button" onClick={() => set(cycleFacet(f, fx.token, fx.twoState))}
                          className={`rounded border px-2 py-0.5 text-xs ${STATE_CLASS[state]}`}
                          title={state === "off" ? "Click to require it" : state === "standard" ? "Standard only; click for standard or option" : state === "listed" ? "Standard or option; click to hide cars that have it" : "Hidden; click to reset"}>
                          {fx.label}{state !== "off" && !fx.twoState ? <span className="ml-1 opacity-70">· {STATE_LABEL[state]}</span> : state === "hide" ? <span className="ml-1 opacity-70">· hidden</span> : null}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
            <div>
              <div className="mb-1 text-xs uppercase tracking-wide text-gray-500">Between</div>
              <div className="grid grid-cols-[auto_1fr_1fr] items-center gap-x-2 gap-y-1 text-xs">
                {RANGES.map((r) => {
                  const cur = f.ranges[r.key] ?? [null, null];
                  return (
                    <div key={r.key} className="contents">
                      <span className="text-gray-400">{r.label}{r.unit ? ` (${r.unit})` : ""}</span>
                      <input type="number" step={r.step} value={cur[0] ?? ""} placeholder="min" onChange={(e) => setRange(r.key, 0, e.target.value)} className="w-full rounded border border-gray-800 bg-gray-950 px-1.5 py-0.5 text-right text-gray-100" />
                      <input type="number" step={r.step} value={cur[1] ?? ""} placeholder="max" onChange={(e) => setRange(r.key, 1, e.target.value)} className="w-full rounded border border-gray-800 bg-gray-950 px-1.5 py-0.5 text-right text-gray-100" />
                    </div>
                  );
                })}
              </div>
              <p className="mt-2 text-xs text-gray-500">A car that carries no value for a bound is left out of that range.</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
