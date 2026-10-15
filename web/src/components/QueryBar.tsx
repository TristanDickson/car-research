"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type InputHTMLAttributes } from "react";

import { useSaveSearch, useSearches } from "@/lib/hooks";
import { GROUPS, RANGE_FIELDS } from "@/lib/fields";
import { canonical, cycleFacet, describeQuery, EMPTY_QUERY, FIXED_FACETS, FLAG_GROUPS, isNarrowed, loaded, serializeQuery, SORTS, toggleAny, withQuery, type FacetState, type Query, type QueryOptions, type Range, type RangeKey } from "@/lib/query";

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
  /** Cars left out only for want of a value (useCarQuery); the bar offers to keep them. */
  unknownHidden?: number;
  /** Cars shown whose true cost rests on few used cars (useCarQuery); the bar offers to leave those figures out. */
  thinShown?: number;
}

/** What the reader types is applied once they pause, so a search is not rerun at every key. */
const TYPING_MS = 350;

/** A text box over one query value that commits after a pause or on leaving it, and follows the query when it
 * changes from elsewhere (a saved search loaded, 'clear'). */
function DraftInput({ value, commit, ...rest }: { value: string; commit: (v: string) => void } & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange">) {
  const [draft, setDraft] = useState(value);
  const [held, setHeld] = useState(value);
  const [sent, setSent] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  if (held !== value) {
    setHeld(value);
    // Our own commit coming back leaves whatever was typed since; any other change replaces the draft.
    if (value !== sent) setDraft(value);
    setSent(null);
  }
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const flush = (v: string) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    if (v !== value) {
      setSent(v);
      commit(v);
    }
  };
  return (
    <input {...rest} value={draft}
      onChange={(e) => {
        const v = e.target.value;
        setDraft(v);
        if (timer.current) clearTimeout(timer.current);
        timer.current = setTimeout(() => flush(v), TYPING_MS);
      }}
      onBlur={() => flush(draft)}
      onKeyDown={(e) => { if (e.key === "Enter") flush(draft); }} />
  );
}

/** The saved search last loaded in this app load: the name the save prompt offers. */
let lastLoaded: string | null = null;

/** The bounds the panel always offers; any other number is added from the picker below them. */
const COMMON_RANGES = ["true", "cash", "monthly", "list", "range", "battery", "dc", "seats", "width", "length", "boot", "wheels"];
/** Bounds added in this app load and not yet set, so a cleared one does not vanish under the cursor. */
let addedRanges: string[] = [];

const sel = "rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100";
const seg = (on: boolean) => `px-2.5 py-1 ${on ? "bg-gray-700 text-gray-100" : "text-gray-400 hover:text-gray-100"}`;

const STATE_LABEL: Record<FacetState, string> = { off: "", standard: "standard", listed: "std, pack or option", hide: "hidden" };
const STATE_CLASS: Record<FacetState, string> = {
  off: "border-gray-700 text-gray-300 hover:border-gray-500",
  standard: "border-emerald-500 bg-emerald-950/40 text-emerald-200",
  listed: "border-sky-500 bg-sky-950/40 text-sky-200",
  hide: "border-rose-500 bg-rose-950/40 text-rose-200 line-through",
};

/**
 * The one search for every car view. The top row loads or saves a named search,
 * narrows (make, model, text, year), orders (sort) and switches view; the panel
 * below it holds every facet as a tri-state chip (standard → standard, pack or
 * option → hidden, all of them combined with 'all' or 'any') and a min/max for
 * every number a car carries. The whole state is the URL.
 */
export function QueryBar({ query: f, set, options, flagLabels, count, unknownHidden = 0, thinShown = 0 }: Props) {
  const pathname = usePathname() ?? "/";
  const searches = useSearches();
  const save = useSaveSearch();
  const list = searches.data?.searches ?? [];
  const here = serializeQuery(f);
  const match = list.find((x) => canonical(x.query) === here);
  const load = (id: string) => {
    const hit = list.find((x) => x.id === id);
    if (!hit) return;
    lastLoaded = hit.name;
    set({ ...EMPTY_QUERY, ...loaded(hit.query) });
  };
  const saveAs = () => {
    const name = window.prompt(`Name this search\n${describeQuery(f, flagLabels)}`, lastLoaded ?? "");
    if (!name?.trim()) return;
    const clash = list.find((x) => x.name.trim().toLowerCase() === name.trim().toLowerCase());
    if (clash && !window.confirm(`Replace the saved search “${clash.name}”?`)) return;
    lastLoaded = name.trim();
    save.mutate({ name, query: here });
  };
  const [open, setOpen] = useState(false);
  const [added, setAdded] = useState<string[]>(addedRanges);
  const offered = new Set([...COMMON_RANGES, ...added, ...Object.keys(f.ranges)]);
  const bounds = RANGE_FIELDS.filter((r) => offered.has(r.key));
  const addRange = (key: string) => {
    addedRanges = [...addedRanges, key];
    setAdded(addedRanges);
  };
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
  const order = ["Essentials", "Can be had by", "Comfort", "Driving", "Other equipment", "Provenance"];
  const groups = [...grouped.entries()].sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]));

  const setRange = (key: RangeKey, i: 0 | 1, v: string) => {
    const cur: Range = f.ranges[key] ?? [null, null];
    const next: Range = [cur[0], cur[1]];
    const n = Number(v.replace(/[£,\s]/g, ""));
    next[i] = v.trim() === "" || !Number.isFinite(n) ? null : n;
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
        <span className="flex items-center gap-1">
          <select aria-label="Saved search" value={match?.id ?? ""} onChange={(e) => load(e.target.value)} className={`${sel} max-w-[14rem]`} title={describeQuery(f, flagLabels)}>
            {!match && <option value="">Unsaved search</option>}
            {list.map((x) => <option key={x.id} value={x.id}>{x.name}{x.id === searches.data?.default_id ? " · default" : ""}</option>)}
          </select>
          {!match && (
            <button type="button" onClick={saveAs} className="rounded border border-gray-700 px-2 py-1 text-gray-300 hover:text-gray-100" title="Save this search under a name">Save…</button>
          )}
          <Link href="/settings" className="px-1 text-xs text-gray-500 hover:text-gray-200" title="Rename, delete or pick the default search">manage</Link>
        </span>
        <select aria-label="Make" value={f.make} onChange={(e) => set({ make: e.target.value })} className={sel}>
          <option value="">All makes</option>
          {makes.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <select aria-label="Model" value={f.model} onChange={(e) => set({ model: e.target.value })} className={sel}>
          <option value="">All models</option>
          {models.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <DraftInput aria-label="Search text" value={f.q} commit={(v) => set({ q: v })} placeholder="Trim, variant, pack…" className={`${sel} w-44`} />
        <select aria-label="Model year" value={f.year} onChange={(e) => set({ year: e.target.value })} className={sel}>
          <option value="">Any year</option>
          {years.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <select aria-label="Sort" value={f.sort || "true"} onChange={(e) => set({ sort: e.target.value === "true" ? "" : e.target.value })} className={sel}>
          {SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
        </select>
        <button type="button" onClick={() => setOpen((o) => !o)} className={`rounded border px-2.5 py-1 ${active ? "border-sky-600 text-sky-200" : "border-gray-700 text-gray-300 hover:text-gray-100"}`}>
          {open ? "Hide filters" : "Filters"}{active ? ` · ${active}` : ""}
        </button>
        {isNarrowed(f) && (
          <button type="button" onClick={() => set({ ...EMPTY_QUERY, sort: f.sort })} className="text-gray-400 hover:text-gray-100" title="Every car">clear</button>
        )}
        <span className="text-gray-500">{count}</span>
        {f.keepUnknown ? (
          <button type="button" onClick={() => set({ keepUnknown: false })} className="text-xs text-amber-300 underline" title="Cars no source gives a value for are kept">
            unknown values kept · leave them out
          </button>
        ) : unknownHidden > 0 ? (
          <button type="button" onClick={() => set({ keepUnknown: true })} className="text-xs text-amber-300 underline" title="Left out only because no source gives the value this search bounds or requires">
            +{unknownHidden} with an unknown value · keep them
          </button>
        ) : null}
        {f.firm ? (
          <button type="button" onClick={() => set({ firm: false })} className="text-xs text-amber-300 underline"
            title="Each car is costed on its cheapest figure whose end value rests on at least 10 used cars">
            figures on few or no used cars left out · show them
          </button>
        ) : thinShown > 0 ? (
          <button type="button" onClick={() => set({ firm: true })} className="text-xs text-amber-300 underline"
            title="Cost each car on its cheapest figure whose end value rests on at least 10 used cars; a car with none drops out of a search on price">
            {thinShown} priced on few or no used cars · leave those figures out
          </button>
        ) : null}
      </div>
      {!open && isNarrowed(f) && <p className="text-xs text-gray-500">{describeQuery(f, flagLabels)}</p>}

      {open && (
        <div className="rounded-lg border border-gray-800 bg-gray-900 p-3">
          <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-gray-400">
            <span>Click a chip: <span className="text-emerald-200">standard</span> → <span className="text-sky-200">standard, pack or option</span> → <span className="text-rose-200">hidden</span> → off. A wanted chip&apos;s <b className="font-medium text-gray-300">and</b> means it must hold; of the chips switched to <b className="font-medium text-amber-200">or</b>, at least one must. A car no source has a value for is left out unless you keep unknown values.</span>
          </div>
          <div className="grid gap-4 lg:grid-cols-[1fr_minmax(22rem,28rem)]">
            <div className="space-y-3">
              {groups.map(([group, facets]) => (
                <div key={group}>
                  <div className="mb-1 text-xs uppercase tracking-wide text-gray-500">{group}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {facets.map((fx) => {
                      const state = f.facets[fx.token] ?? "off";
                      const wanted = state === "standard" || state === "listed";
                      const or = wanted && f.any.includes(fx.token);
                      return (
                        <span key={fx.token} className="inline-flex">
                          <button type="button" onClick={() => set(cycleFacet(f, fx.token, fx.twoState))}
                            className={`border px-2 py-0.5 text-xs ${wanted ? "rounded-l" : "rounded"} ${STATE_CLASS[state]}`}
                            title={state === "off" ? "Click to require it" : state === "standard" ? "Standard only; click for standard, pack or option" : state === "listed" ? "Standard, pack or option; click to hide cars that have it" : "Hidden; click to reset"}>
                            {fx.label}{state !== "off" && !fx.twoState ? <span className="ml-1 opacity-70">· {STATE_LABEL[state]}</span> : state === "hide" ? <span className="ml-1 opacity-70">· hidden</span> : null}
                          </button>
                          {wanted && (
                            <button type="button" onClick={() => set(toggleAny(f, fx.token))}
                              className={`rounded-r border border-l-0 px-1.5 py-0.5 text-[11px] ${or ? "border-amber-500 bg-amber-950/40 text-amber-200" : `${STATE_CLASS[state]} opacity-80`}`}
                              title={or ? "One of the 'or' chips must hold; click to make this one required" : "Required; click to make it one of the 'or' chips, of which at least one must hold"}>
                              {or ? "or" : "and"}
                            </button>
                          )}
                        </span>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
            <div>
              <div className="mb-1 text-xs uppercase tracking-wide text-gray-500">Between</div>
              <div className="grid grid-cols-[minmax(0,1fr)_6.5rem_6.5rem] items-center gap-x-2 gap-y-1 text-xs">
                {bounds.map((r) => {
                  const cur = f.ranges[r.key] ?? [null, null];
                  const box = "w-full rounded border border-gray-800 bg-gray-950 px-1.5 py-0.5 text-right text-sm tabular-nums text-gray-100";
                  return (
                    <div key={r.key} className="contents">
                      <span className="leading-tight text-gray-400">{r.label}{r.kind === "money" ? " (£)" : r.unit ? ` (${r.unit})` : ""}</span>
                      <DraftInput inputMode="decimal" value={cur[0] == null ? "" : String(cur[0])} placeholder="min" aria-label={`${r.label}, at least`} commit={(v) => setRange(r.key, 0, v)} className={box} />
                      <DraftInput inputMode="decimal" value={cur[1] == null ? "" : String(cur[1])} placeholder="max" aria-label={`${r.label}, at most`} commit={(v) => setRange(r.key, 1, v)} className={box} />
                    </div>
                  );
                })}
              </div>
              <select aria-label="Bound another number" value="" onChange={(e) => e.target.value && addRange(e.target.value)} className={`${sel} mt-2 w-full text-xs`}>
                <option value="">Bound another number…</option>
                {GROUPS.map((g) => {
                  const more = RANGE_FIELDS.filter((r) => r.group === g && !offered.has(r.key));
                  return more.length ? (
                    <optgroup key={g} label={g}>
                      {more.map((r) => <option key={r.key} value={r.key}>{r.label}{r.unit ? ` (${r.unit})` : ""}</option>)}
                    </optgroup>
                  ) : null;
                })}
              </select>
              <p className="mt-2 text-xs text-gray-500">A car that carries no value for a bound is left out of that range.</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
