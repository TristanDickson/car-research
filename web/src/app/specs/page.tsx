"use client";

/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import { Suspense, useMemo, useState } from "react";

import { FilterBar } from "@/components/FilterBar";
import { Badge, Empty, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { specMatches, useFilters } from "@/lib/filters";
import { gbp, num } from "@/lib/format";
import { useCars, useDataPage, useSpecs } from "@/lib/hooks";
import type { FlagState, SnapshotSpec } from "@/lib/types";

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
  { key: "zero_to_62_s", label: "0–62 mph", fmt: (v) => (typeof v === "number" ? `${num(v, 1)} s` : "—") },
  { key: "zero_to_60_s", label: "0–60 mph", fmt: (v) => (typeof v === "number" ? `${num(v, 1)} s` : "—") },
  { key: "dc_10_80_min", label: "DC 10–80%", fmt: (v) => (typeof v === "number" ? `${num(v)} min` : "—") },
  { key: "seats", label: "Seats", fmt: (v) => (typeof v === "number" ? String(v) : "—") },
  { key: "boot_l", label: "Boot", fmt: (v) => (typeof v === "number" ? `${num(v)} L` : "—") },
  { key: "length_mm", label: "Length", fmt: (v) => (typeof v === "number" ? `${num(v)} mm` : "—") },
  { key: "width_mm", label: "Width", fmt: (v) => (typeof v === "number" ? `${num(v)} mm` : "—") },
  { key: "turning_circle_m", label: "Turning circle", fmt: (v) => (typeof v === "number" ? `${num(v, 1)} m` : "—") },
  { key: "insurance_group", label: "Insurance group", fmt: (v) => (v == null || v === "" ? "—" : String(v)) },
];

const MAX_COLS = 60;

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

function Specs() {
  const specs = useSpecs();
  const cars = useCars();
  const data = useDataPage();
  const [f] = useFilters();
  const [onlyDiff, setOnlyDiff] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [wide, setWide] = useState(false);
  const [needle, setNeedle] = useState("");

  const matching = useMemo(
    () => (specs.data ?? []).filter((s) => specMatches(s, f))
      .sort((a, b) => a.make.localeCompare(b.make) || a.model.localeCompare(b.model) || a.trim.localeCompare(b.trim)
        || (a.powertrain ?? a.engine ?? "").localeCompare(b.powertrain ?? b.engine ?? "") || (a.seats ?? 0) - (b.seats ?? 0)),
    [specs.data, f],
  );
  // A matrix of every derivative on sale is ~1,500 columns: show the first MAX_COLS until a filter narrows it (or the reader insists).
  const cols = useMemo(() => (wide ? matching : matching.slice(0, MAX_COLS)), [matching, wide]);
  const flagLabels = data.data?.flag_labels ?? {};
  const flagKeys = Object.keys(flagLabels);
  const carById = useMemo(() => new Map((cars.data ?? []).map((c) => [c.id, c])), [cars.data]);

  const items = useMemo(() => {
    const all = new Map<string, number>();
    for (const s of cols) for (const it of [...s.features, ...s.options]) all.set(it, (all.get(it) ?? 0) + 1);
    let list = Array.from(all.keys()).sort((a, b) => a.localeCompare(b));
    if (needle.trim()) list = list.filter((i) => i.toLowerCase().includes(needle.trim().toLowerCase()));
    if (onlyDiff && cols.length > 1) list = list.filter((i) => new Set(cols.map((s) => stateOf(s, i))).size > 1);
    return list;
  }, [cols, needle, onlyDiff]);

  const flagRows = useMemo(
    () => flagKeys.filter((k) => !onlyDiff || cols.length < 2 || new Set(cols.map((s) => s.flags?.[k] ?? null)).size > 1),
    [flagKeys, cols, onlyDiff],
  );

  if (specs.error) return <ErrorNote error={specs.error} />;
  if (!specs.data || !cars.data) return <Loading />;

  const th = "sticky left-0 z-10 bg-gray-900 py-1 pr-3 text-left font-normal text-gray-400";

  return (
    <div className="space-y-4">
      <PageHeader
        title="Specs"
        subtitle="Every variant the spec sources list, side by side: Carwow's specification pages (one column per derivative, dated by its CAP version) and Kia's own specification tables (one per grade and powertrain). ✓ is standard, opt is an option, – is not listed. The canonical flags are the same ones the brief is checked against."
      />
      <FilterBar
        cars={cars.data}
        specs={specs.data}
        scope={false}
        count={`${matching.length} of ${specs.data.length} variants${cols.length < matching.length ? ` (first ${cols.length} shown)` : ""}`}
        extra={
          <>
            <label className="flex items-center gap-1"><input type="checkbox" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} /> only differences</label>
            {matching.length > cols.length && (
              <button onClick={() => setWide(true)} className="text-gray-400 underline hover:text-gray-100">show all {matching.length}</button>
            )}
          </>
        }
      />
      {cols.length === 0 ? (
        <Empty>No variants match. Clear a filter.</Empty>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-800 bg-gray-900 p-3">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="align-bottom">
                <th className={`${th} w-56`}>Variant</th>
                {cols.map((s) => {
                  const car = s.car_id ? carById.get(s.car_id) : undefined;
                  return (
                    <th key={s.spec_key} className="min-w-[9rem] px-2 pb-2 text-left font-normal">
                      {s.image_url && <img src={s.image_url} alt="" className="mb-1 h-14 w-32 rounded object-cover" loading="lazy" />}
                      <div className="font-medium text-gray-100">{s.make} {s.model}</div>
                      <div className="text-gray-300">{s.trim}{s.seats ? ` · ${s.seats} seats` : ""}</div>
                      <div className="text-xs text-gray-500">{s.engine ?? s.powertrain}</div>
                      <div className="mt-1 flex flex-wrap gap-1">
                        <Badge tone="muted" title={s.source}>{s.provider === "carwow_specs" ? "Carwow" : "Kia UK"}</Badge>
                        {(s.version_date ?? s.model_year_hint) && <Badge tone="muted" title="derivative version">{(s.version_date ?? s.model_year_hint)!.slice(0, 7)}</Badge>}
                        {car && (
                          <Link href={`/cars/view?id=${encodeURIComponent(car.id)}`} className="rounded border border-blue-900 bg-blue-950 px-1.5 py-0.5 text-xs text-blue-300 hover:underline">
                            {car.auto ? "car" : "shortlist"}
                          </Link>
                        )}
                      </div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              <tr><td colSpan={cols.length + 1} className="pt-2 text-xs uppercase tracking-wide text-gray-500">Price</td></tr>
              <tr className="border-t border-gray-800">
                <th className={th}>RRP</th>
                {cols.map((s) => <td key={s.spec_key} className="px-2 py-1 tabular-nums">{gbp(s.rrp)}</td>)}
              </tr>
              <tr className="border-t border-gray-800">
                <th className={th}>Carwow price</th>
                {cols.map((s) => <td key={s.spec_key} className="px-2 py-1 tabular-nums">{gbp(s.carwow_price)}</td>)}
              </tr>
              <tr><td colSpan={cols.length + 1} className="pt-3 text-xs uppercase tracking-wide text-gray-500">Numbers</td></tr>
              {NUMBERS.filter((n) => cols.some((s) => s.numbers?.[n.key] != null && s.numbers?.[n.key] !== "")).map((n) => (
                <tr key={n.key} className="border-t border-gray-800">
                  <th className={th}>{n.label}</th>
                  {cols.map((s) => <td key={s.spec_key} className="px-2 py-1 tabular-nums">{n.fmt(s.numbers?.[n.key])}</td>)}
                </tr>
              ))}
              <tr><td colSpan={cols.length + 1} className="pt-3 text-xs uppercase tracking-wide text-gray-500">Equipment that matters (canonical flags)</td></tr>
              {flagRows.map((k) => (
                <tr key={k} className="border-t border-gray-800">
                  <th className={th}>{flagLabels[k]}</th>
                  {cols.map((s) => <td key={s.spec_key} className="px-2 py-1"><Cell state={s.flags?.[k] ?? null} /></td>)}
                </tr>
              ))}
              <tr>
                <td colSpan={cols.length + 1} className="pt-4 text-xs uppercase tracking-wide text-gray-500">
                  <div className="flex flex-wrap items-center gap-3">
                    <span>Everything listed ({items.length})</span>
                    <input value={needle} onChange={(e) => setNeedle(e.target.value)} placeholder="search equipment" className="rounded border border-gray-700 bg-gray-950 px-2 py-0.5 text-xs normal-case tracking-normal text-gray-100" />
                    {!showAll && items.length > 40 && (
                      <button onClick={() => setShowAll(true)} className="normal-case tracking-normal text-gray-300 underline">show all {items.length}</button>
                    )}
                  </div>
                </td>
              </tr>
              {(showAll ? items : items.slice(0, 40)).map((it) => (
                <tr key={it} className="border-t border-gray-800">
                  <th className={`${th} font-normal text-gray-300`}>{it}</th>
                  {cols.map((s) => <td key={s.spec_key} className="px-2 py-1"><Cell state={stateOf(s, it)} /></td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
