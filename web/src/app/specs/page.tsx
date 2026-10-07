"use client";

/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import { QueryBar } from "@/components/QueryBar";
import { Badge, Empty, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { gbp, num } from "@/lib/format";
import { useSpecs } from "@/lib/hooks";
import { useCarQuery } from "@/lib/useCarQuery";
import type { FlagState, SnapshotCar, SnapshotSpec } from "@/lib/types";

export default function SpecsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <Specs />
    </Suspense>
  );
}

const NUMBERS: { key: string; label: string; fmt: (v: number | string | null | undefined) => string }[] = [
  { key: "battery_kwh", label: "Battery", fmt: (v) => (typeof v === "number" ? `${num(v, 1)} kWh` : "—") },
  { key: "wltp_range_mi", label: "WLTP range", fmt: (v) => (typeof v === "number" ? `${num(v)} mi` : "—") },
  { key: "efficiency_mi_kwh", label: "Efficiency", fmt: (v) => (typeof v === "number" ? `${num(v, 1)} mi/kWh` : "—") },
  { key: "power_bhp", label: "Power", fmt: (v) => (typeof v === "number" ? `${num(v)} bhp` : "—") },
  { key: "top_speed_mph", label: "Top speed", fmt: (v) => (typeof v === "number" ? `${num(v)} mph` : "—") },
  { key: "zero_to_62_s", label: "0–62 mph", fmt: (v) => (typeof v === "number" ? `${num(v, 1)} s` : "—") },
  { key: "zero_to_60_s", label: "0–60 mph", fmt: (v) => (typeof v === "number" ? `${num(v, 1)} s` : "—") },
  { key: "dc_peak_kw", label: "DC peak", fmt: (v) => (typeof v === "number" ? `${num(v)} kW` : "—") },
  { key: "dc_10_80_min", label: "DC 10–80%", fmt: (v) => (typeof v === "number" ? `${num(v)} min` : "—") },
  { key: "ac_kw", label: "AC onboard", fmt: (v) => (typeof v === "number" ? `${num(v)} kW` : "—") },
  { key: "seats", label: "Seats", fmt: (v) => (typeof v === "number" ? String(v) : "—") },
  { key: "boot_l", label: "Boot", fmt: (v) => (typeof v === "number" ? `${num(v)} L` : "—") },
  { key: "boot_max_l", label: "Boot, seats down", fmt: (v) => (typeof v === "number" ? `${num(v)} L` : "—") },
  { key: "length_mm", label: "Length", fmt: (v) => (typeof v === "number" ? `${num(v)} mm` : "—") },
  { key: "width_mm", label: "Width", fmt: (v) => (typeof v === "number" ? `${num(v)} mm` : "—") },
  { key: "height_mm", label: "Height", fmt: (v) => (typeof v === "number" ? `${num(v)} mm` : "—") },
  { key: "wheelbase_m", label: "Wheelbase", fmt: (v) => (typeof v === "number" ? `${num(v, 2)} m` : "—") },
  { key: "turning_circle_m", label: "Turning circle", fmt: (v) => (typeof v === "number" ? `${num(v, 1)} m` : "—") },
  { key: "insurance_group", label: "Insurance group", fmt: (v) => (v == null || v === "" ? "—" : String(v)) },
];

/** Columns per page: the grid is read sideways, so this is a page, not a cap. */
const PAGE = 40;

function Cell({ state }: { state: FlagState | "n/a" }) {
  if (state === "standard") return <span className="text-emerald-300">✓</span>;
  if (state === "option") return <span className="text-amber-300">opt</span>;
  return <span className="text-gray-600">–</span>;
}

function stateOf(s: SnapshotSpec, item: string): FlagState {
  if (s.features.includes(item)) return "standard";
  if (s.options.includes(item)) return "option";
  return null;
}

/**
 * The dense view: one column per derivative the search admits, every number
 * and every piece of equipment the spec sources list. The columns follow the
 * same search and order as the cards and the table; a car with no spec row
 * (a deals-page stub) is counted but has no column.
 */
function Specs() {
  const { query, set, cars, rows, options, flagLabels, loading, error } = useCarQuery();
  const specs = useSpecs();
  const [onlyDiff, setOnlyDiff] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [needle, setNeedle] = useState("");
  const [page, setPage] = useState(0);
  const nAuto = useMemo(() => (cars ?? []).filter((c) => c.auto).length, [cars]);

  // One spec column per car in the result set, in the result's order.
  const columns = useMemo(() => {
    const byCar = new Map<string, SnapshotSpec[]>();
    for (const s of specs.data ?? []) if (s.car_id) byCar.set(s.car_id, [...(byCar.get(s.car_id) ?? []), s]);
    const out: { car: SnapshotCar; spec: SnapshotSpec }[] = [];
    for (const c of rows) for (const s of byCar.get(c.id) ?? []) out.push({ car: c, spec: s });
    return out;
  }, [specs.data, rows]);
  const pages = Math.max(1, Math.ceil(columns.length / PAGE));
  const current = Math.min(page, pages - 1);
  const cols = useMemo(() => columns.slice(current * PAGE, current * PAGE + PAGE), [columns, current]);
  const flagKeys = Object.keys(flagLabels);

  const items = useMemo(() => {
    const all = new Map<string, number>();
    for (const { spec: s } of cols) for (const it of [...s.features, ...s.options]) all.set(it, (all.get(it) ?? 0) + 1);
    let list = Array.from(all.keys()).sort((a, b) => a.localeCompare(b));
    if (needle.trim()) list = list.filter((i) => i.toLowerCase().includes(needle.trim().toLowerCase()));
    if (onlyDiff && cols.length > 1) list = list.filter((i) => new Set(cols.map(({ spec }) => stateOf(spec, i))).size > 1);
    return list;
  }, [cols, needle, onlyDiff]);

  const flagRows = useMemo(
    () => flagKeys.filter((k) => !onlyDiff || cols.length < 2 || new Set(cols.map(({ spec }) => spec.flags?.[k] ?? null)).size > 1),
    [flagKeys, cols, onlyDiff],
  );

  // A scrollbar above the grid, in step with the grid's own, so sideways reading never needs the page bottom.
  const topRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const [gridWidth, setGridWidth] = useState(0);
  useEffect(() => {
    const g = gridRef.current;
    if (!g) return;
    const measure = () => setGridWidth(g.scrollWidth);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(g);
    return () => ro.disconnect();
  }, [cols, items, flagRows, showAll]);
  const sync = (from: HTMLDivElement | null, to: HTMLDivElement | null) => {
    if (from && to && Math.abs(from.scrollLeft - to.scrollLeft) > 1) to.scrollLeft = from.scrollLeft;
  };

  if (error) return <ErrorNote error={error} />;
  if (specs.error) return <ErrorNote error={specs.error} />;
  if (loading || !cars || !specs.data) return <Loading />;

  const th = "sticky left-0 z-10 bg-gray-900 py-1 pr-3 text-left font-normal text-gray-400";
  const noSpec = rows.length - new Set(columns.map((c) => c.car.id)).size;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Specs"
        subtitle="Every derivative the search admits, side by side: the numbers and every piece of equipment its spec source lists. ✓ is standard, opt is an option, – is not listed. The canonical flags are the same ones the brief and the filters use."
      />
      <QueryBar query={query} set={set} options={options} flagLabels={flagLabels} nAuto={nAuto}
        count={`${columns.length} columns for ${rows.length} cars${noSpec ? ` (${noSpec} without a spec row)` : ""}`} />
      {cols.length === 0 ? (
        <Empty>No spec rows for this search. Widen it, or switch to Every EV.</Empty>
      ) : (
        <div className="rounded-lg border border-gray-800 bg-gray-900">
          <div className="flex flex-wrap items-center gap-3 border-b border-gray-800 px-3 py-2 text-sm">
            <span className="text-gray-400">Columns {current * PAGE + 1}–{Math.min(columns.length, (current + 1) * PAGE)} of {columns.length}</span>
            {pages > 1 && (
              <span className="flex items-center gap-1">
                <button onClick={() => setPage(Math.max(0, current - 1))} disabled={current === 0} className="rounded border border-gray-700 px-2 py-0.5 disabled:opacity-40">← prev</button>
                <button onClick={() => setPage(Math.min(pages - 1, current + 1))} disabled={current >= pages - 1} className="rounded border border-gray-700 px-2 py-0.5 disabled:opacity-40">next →</button>
              </span>
            )}
            <label className="flex items-center gap-1"><input type="checkbox" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} /> only differences</label>
            <input value={needle} onChange={(e) => setNeedle(e.target.value)} placeholder="search equipment" className="rounded border border-gray-700 bg-gray-950 px-2 py-0.5 text-xs text-gray-100" />
          </div>
          <div ref={topRef} onScroll={() => sync(topRef.current, gridRef.current)} className="overflow-x-auto overflow-y-hidden" style={{ height: 14 }} aria-hidden>
            <div style={{ width: gridWidth, height: 1 }} />
          </div>
          <div ref={gridRef} onScroll={() => sync(gridRef.current, topRef.current)} className="max-h-[75vh] overflow-auto p-3">
            <table className="min-w-full text-sm">
              <thead className="sticky top-0 z-20 bg-gray-900">
                <tr className="align-bottom">
                  <th className={`${th} w-56 z-30`}>Variant</th>
                  {cols.map(({ car, spec: s }) => (
                    <th key={s.spec_key} className="min-w-[9rem] px-2 pb-2 text-left font-normal">
                      {s.image_url && <img src={s.image_url} alt="" className="mb-1 h-14 w-32 rounded object-cover" loading="lazy" />}
                      <Link href={`/cars/view?id=${encodeURIComponent(car.id)}`} className="font-medium text-gray-100 hover:underline">{s.make} {s.model}</Link>
                      <div className="text-gray-300">{s.trim}{s.seats ? ` · ${s.seats} seats` : ""}</div>
                      <div className="text-xs text-gray-500">{s.engine ?? s.powertrain}</div>
                      <div className="mt-1 flex flex-wrap gap-1">
                        <Badge tone="muted" title={s.source}>{s.provider === "carwow_specs" ? "Carwow" : "Kia UK"}</Badge>
                        {(s.version_date ?? s.model_year_hint) && <Badge tone="muted" title="derivative version">{(s.version_date ?? s.model_year_hint)!.slice(0, 7)}</Badge>}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr><td colSpan={cols.length + 1} className="pt-2 text-xs uppercase tracking-wide text-gray-500">Price</td></tr>
                <tr className="border-t border-gray-800">
                  <th className={th}>RRP</th>
                  {cols.map(({ spec: s }) => <td key={s.spec_key} className="px-2 py-1 tabular-nums">{gbp(s.rrp)}</td>)}
                </tr>
                <tr className="border-t border-gray-800">
                  <th className={th}>Carwow price</th>
                  {cols.map(({ spec: s }) => <td key={s.spec_key} className="px-2 py-1 tabular-nums">{gbp(s.carwow_price)}</td>)}
                </tr>
                <tr><td colSpan={cols.length + 1} className="pt-3 text-xs uppercase tracking-wide text-gray-500">Numbers</td></tr>
                {NUMBERS.filter((n) => cols.some(({ spec: s }) => s.numbers?.[n.key] != null && s.numbers?.[n.key] !== "")).map((n) => (
                  <tr key={n.key} className="border-t border-gray-800">
                    <th className={th}>{n.label}</th>
                    {cols.map(({ spec: s }) => <td key={s.spec_key} className="px-2 py-1 tabular-nums">{n.fmt(s.numbers?.[n.key])}</td>)}
                  </tr>
                ))}
                <tr><td colSpan={cols.length + 1} className="pt-3 text-xs uppercase tracking-wide text-gray-500">Equipment that matters (canonical flags)</td></tr>
                {flagRows.map((k) => (
                  <tr key={k} className="border-t border-gray-800">
                    <th className={th}>{flagLabels[k]}</th>
                    {cols.map(({ spec: s }) => <td key={s.spec_key} className="px-2 py-1"><Cell state={s.flags?.[k] ?? null} /></td>)}
                  </tr>
                ))}
                <tr>
                  <td colSpan={cols.length + 1} className="pt-4 text-xs uppercase tracking-wide text-gray-500">
                    <div className="flex flex-wrap items-center gap-3">
                      <span>Everything listed ({items.length})</span>
                      {!showAll && items.length > 40 && (
                        <button onClick={() => setShowAll(true)} className="normal-case tracking-normal text-gray-300 underline">show all {items.length}</button>
                      )}
                    </div>
                  </td>
                </tr>
                {(showAll ? items : items.slice(0, 40)).map((it) => (
                  <tr key={it} className="border-t border-gray-800">
                    <th className={`${th} font-normal text-gray-300`}>{it}</th>
                    {cols.map(({ spec: s }) => <td key={s.spec_key} className="px-2 py-1"><Cell state={stateOf(s, it)} /></td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
