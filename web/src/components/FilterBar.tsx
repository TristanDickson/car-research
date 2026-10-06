"use client";

import { allCars, EMPTY, filterOptions, isEmpty, useFilters } from "@/lib/filters";
import type { SnapshotCar, SnapshotSpec } from "@/lib/types";

/**
 * The shared scope / make / model / variant / year bar. One row above the
 * content it scopes; the state is in the URL so it carries across pages and
 * into links. Scope: the hand-curated shortlist, or every EV on sale (the
 * generated cars too). Pages that do not list cars (Specs) hide the scope.
 */
export function FilterBar({ cars, specs = [], count, extra, scope = true }: { cars: SnapshotCar[]; specs?: SnapshotSpec[]; count?: string; extra?: React.ReactNode; scope?: boolean }) {
  const [f, set] = useFilters();
  const opts = filterOptions(cars, specs, f);
  const nAuto = cars.filter((c) => c.auto).length;
  // A value that arrived in the URL ("?model=Kona") stays visible even when the
  // loaded data words it differently ("Kona Electric").
  const withCurrent = (list: string[], cur: string) => (cur && !list.includes(cur) ? [cur, ...list] : list);
  const makes = withCurrent(opts.makes, f.make), models = withCurrent(opts.models, f.model), years = withCurrent(opts.years, f.year);
  const sel = "rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100";
  const seg = (on: boolean) => `px-2.5 py-1 ${on ? "bg-gray-700 text-gray-100" : "text-gray-400 hover:text-gray-100"}`;
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
      {scope && nAuto > 0 && (
        <div role="group" aria-label="Scope" className="flex overflow-hidden rounded border border-gray-700 bg-gray-900">
          <button type="button" className={seg(!allCars(f))} onClick={() => set({ scope: "" })} title="The trims curated by hand in data/seed/cars.json">
            Shortlist
          </button>
          <button type="button" className={seg(allCars(f))} onClick={() => set({ scope: "all" })} title={`Every EV on sale: ${nAuto} more derivatives generated from Carwow's catalogue`}>
            Every EV
          </button>
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
        <button onClick={() => set({ ...EMPTY, scope: f.scope })} className="text-gray-400 hover:text-gray-100">clear</button>
      )}
      {count && <span className="text-gray-500">{count}</span>}
    </div>
  );
}
