"use client";

import { useState } from "react";

import { LineChart } from "@/components/charts/LineChart";
import { WindowPicker, type Window } from "@/components/PriceHistory";
import { ROUTE_LABEL, ROUTES } from "@/lib/costs";
import { gbp } from "@/lib/format";
import { useResidualsForModel, useSeriesForCar } from "@/lib/hooks";
import { clipChart, latestOf, seriesToChart, type Measure } from "@/lib/trends";
import type { Route, SnapshotCar } from "@/lib/types";

const DAY = 86_400_000;
const day = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "2-digit", timeZone: "UTC" });

/**
 * Every sighting of this car, route by route and source by source, on one
 * footing (the true monthly, or as printed), plus the used-market evidence
 * behind the end-of-term value. Reads the series the pipeline exported; no
 * arithmetic here.
 */
export function CostHistory({ car }: { car: SnapshotCar }) {
  const series = useSeriesForCar(car);
  const residuals = useResidualsForModel(car.model_key ?? null);
  const [route, setRoute] = useState<Route | null>(null);
  const [measure, setMeasure] = useState<Measure>("true");
  const [win, setWin] = useState<Window>(null);
  const [now] = useState(() => Date.now());

  const available = ROUTES.filter((r) => series.data?.some((s) => s.route === r));
  const active = route && available.includes(route) ? route : available[0] ?? null;
  const rows = (series.data ?? []).filter((s) => s.route === active);
  const chart = clipChart(seriesToChart(rows, measure, (s) => s.source_name), win == null ? null : now - win * DAY);
  const firstAt = Math.min(now, ...rows.flatMap((r) => r.points.map((p) => Date.parse(`${p.from}T00:00:00Z`))));
  const xDomain: [number, number] = [win == null ? firstAt : now - win * DAY, now];
  const latest = rows.map((r) => ({ r, l: latestOf(r, measure) })).sort((a, b) => (a.l?.v ?? Infinity) - (b.l?.v ?? Infinity));
  const byYear = [...(residuals.data ?? [])].sort((a, b) => b.year - a.year);

  if (series.isLoading) return <div className="text-sm text-gray-500">Loading history…</div>;
  if (!available.length) return <div className="text-sm text-gray-500">No sighting of this car on any route yet.</div>;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <div className="flex overflow-hidden rounded border border-gray-700">
          {available.map((r) => (
            <button key={r} onClick={() => setRoute(r)} className={`px-3 py-1 text-xs ${r === active ? "bg-gray-700 text-gray-100" : "text-gray-400 hover:bg-gray-800"}`}>
              {ROUTE_LABEL[r]}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2">
          Show
          <select value={measure} onChange={(e) => setMeasure(e.target.value as Measure)} className="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs">
            <option value="true">true £ per month</option>
            <option value="headline">as printed (price or monthly)</option>
          </select>
        </label>
        <WindowPicker value={win} onChange={setWin} />
        <span className="text-gray-500">{active === "used" ? "the model's cheapest used example, each site" : "one line per source"}</span>
      </div>
      <LineChart series={chart} format={(v) => gbp(v)} height={200} xDomain={xDomain} empty="Nothing sighted in this range." />
      <table className="w-full text-sm">
        <thead className="text-left text-xs uppercase text-gray-500">
          <tr>
            <th className="py-1 pr-3">Source</th>
            <th className="py-1 pr-3 text-right">True £/mo</th>
            <th className="py-1 pr-3 text-right">As printed</th>
            <th className="py-1 pr-3">End value from</th>
            <th className="py-1 pr-3">Seller</th>
            <th className="py-1">Last confirmed</th>
          </tr>
        </thead>
        <tbody>
          {latest.map(({ r, l }) => (
            <tr key={r.id} className="border-t border-gray-800">
              <td className="py-1 pr-3">{r.source_name}{active === "used" && l?.point.n ? <span className="text-xs text-gray-500"> · {l.point.n} on sale</span> : null}</td>
              <td className="py-1 pr-3 text-right tabular-nums">{l?.point.true_monthly != null ? gbp(l.point.true_monthly) : "—"}</td>
              <td className="py-1 pr-3 text-right tabular-nums">{l?.point.headline != null ? gbp(l.point.headline) : "—"}</td>
              <td className="py-1 pr-3 text-xs text-gray-400">{l?.point.residual_source ?? "—"}</td>
              <td className="py-1 pr-3 text-xs text-gray-400">{l?.point.seller ?? "—"}</td>
              <td className="py-1 text-xs text-gray-400">{l ? day(l.point.to) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {byYear.length > 0 && (
        <div>
          <div className="mb-1 text-xs uppercase tracking-wide text-gray-500">What the used market says this model is worth, by registration year</div>
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-gray-500">
              <tr>
                <th className="py-1 pr-3">Year</th>
                <th className="py-1 pr-3 text-right">Median now</th>
                <th className="py-1 pr-3 text-right">Examples</th>
                <th className="py-1 pr-3 text-right">First reading</th>
                <th className="py-1">Since</th>
              </tr>
            </thead>
            <tbody>
              {byYear.map((r) => {
                const first = r.points[0];
                const last = r.points[r.points.length - 1];
                const d = last.median - first.median;
                return (
                  <tr key={r.year} className="border-t border-gray-800">
                    <td className="py-1 pr-3">{r.year}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{gbp(last.median)}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{last.n}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{gbp(first.median)}</td>
                    <td className={`py-1 text-xs ${d < 0 ? "text-amber-300" : d > 0 ? "text-emerald-300" : "text-gray-400"}`}>
                      {day(first.date)}{d === 0 ? "" : ` (${d < 0 ? "−" : "+"}${gbp(Math.abs(d))} since)`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-1 text-xs text-gray-500">Medians over the examples on sale on each date, the same car on two sites counted once. The series builds from the nightly scrapes; there is no archive of used stock.</p>
        </div>
      )}
    </div>
  );
}
