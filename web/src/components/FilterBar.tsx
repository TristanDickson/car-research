"use client";

import { EMPTY, filterOptions, isEmpty, useFilters } from "@/lib/filters";
import type { SnapshotCar, SnapshotSpec } from "@/lib/types";

/**
 * The shared make / model / variant / year bar. One row above the content it
 * scopes; the state is in the URL so it carries across pages and into links.
 */
export function FilterBar({ cars, specs = [], count, extra }: { cars: SnapshotCar[]; specs?: SnapshotSpec[]; count?: string; extra?: React.ReactNode }) {
  const [f, set] = useFilters();
  const opts = filterOptions(cars, specs, f);
  // A value that arrived in the URL ("?model=Kona") stays visible even when the
  // loaded data words it differently ("Kona Electric").
  const withCurrent = (list: string[], cur: string) => (cur && !list.includes(cur) ? [cur, ...list] : list);
  const makes = withCurrent(opts.makes, f.make), models = withCurrent(opts.models, f.model), years = withCurrent(opts.years, f.year);
  const sel = "rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100";
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
      <select aria-label="Make" value={f.make} onChange={(e) => set({ make: e.target.value })} className={sel}>
        <option value="">All makes</option>
        {makes.map((m) => <option key={m} value={m}>{m}</option>)}
      </select>
      <select aria-label="Model" value={f.model} onChange={(e) => set({ model: e.target.value })} className={sel}>
        <option value="">All models</option>
        {models.map((m) => <option key={m} value={m}>{m}</option>)}
      </select>
      <input
        aria-label="Variant or text"
        value={f.q}
        onChange={(e) => set({ q: e.target.value })}
        placeholder="Variant, trim, pack, dealer…"
        className={`${sel} w-56`}
      />
      <select aria-label="Model year" value={f.year} onChange={(e) => set({ year: e.target.value })} className={sel}>
        <option value="">Any year</option>
        {years.map((y) => <option key={y} value={y}>{y}</option>)}
      </select>
      {extra}
      {!isEmpty(f) && (
        <button onClick={() => set({ ...EMPTY })} className="text-gray-400 hover:text-gray-100">clear</button>
      )}
      {count && <span className="text-gray-500">{count}</span>}
    </div>
  );
}
