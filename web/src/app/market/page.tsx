"use client";

import Link from "next/link";
import { Suspense, useMemo, useState } from "react";

import { LineChart } from "@/components/charts/LineChart";
import { FilterBar } from "@/components/FilterBar";
import { WindowPicker, type Window } from "@/components/PriceHistory";
import { Card, Empty, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { ROUTE_LABEL, ROUTES } from "@/lib/costs";
import { carMatches, useFilters } from "@/lib/filters";
import { carName, gbp } from "@/lib/format";
import { useCars, useSeries } from "@/lib/hooks";
import { clipChart, latestOf, seriesToChart, valueOn, type Measure } from "@/lib/trends";
import type { Route, SnapshotCar, SnapshotSeries } from "@/lib/types";

const fullName = (c: SnapshotCar) => carName(c) + (c.packs?.length ? ` + ${c.packs.join(" + ")}` : "");

interface Row {
  subject: string;
  label: string;
  href: string;
  rows: SnapshotSeries[];
  /** Cheapest current figure across sources, and the source it came from. */
  now: number | null;
  nowSource: string | null;
  /** The cheapest figure at the start of the window (or the first sighting). */
  then: number | null;
  firstAt: number;
}

const DAY = 86_400_000;
/** Small multiples per page; the movers table always lists every row. */
const CHARTS = 36;

/**
 * Trends: every route, every source, over time, on one footing. One row per
 * derivative (per model for used stock), one line per source, and a movers
 * table that is the charts' twin. The pipeline costs each sighting as of its
 * own day (model/sightings.py); this page only draws what it exported.
 */
export default function MarketPage() {
  return (
    <Suspense fallback={<Loading />}>
      <Market />
    </Suspense>
  );
}

const delta = (r: Row) => (r.now != null && r.then != null ? r.now - r.then : null);

function Market() {
  const [filters] = useFilters();
  const cars = useCars();
  const series = useSeries();
  const [route, setRoute] = useState<Route>("cash");
  const [measure, setMeasure] = useState<Measure>("true");
  const [win, setWin] = useState<Window>(90);
  const [charts, setCharts] = useState(CHARTS);
  const [now] = useState(() => Date.now());

  const rows = useMemo<Row[]>(() => {
    const bySubject = new Map<string, SnapshotSeries[]>();
    for (const s of series.data ?? []) {
      if (s.route === route) bySubject.set(s.subject, [...(bySubject.get(s.subject) ?? []), s]);
    }
    const out: Row[] = [];
    const seen = new Set<string>();
    for (const c of cars.data ?? []) {
      if (!carMatches(c, filters)) continue;
      const subject = route === "used" ? (c.model_key ? `model:${c.model_key}` : null) : c.id;
      if (!subject || seen.has(subject)) continue;
      const rs = bySubject.get(subject);
      if (!rs?.length) continue;
      seen.add(subject);
      const latest = rs.map((r) => ({ r, l: latestOf(r, measure) })).filter((x) => x.l).sort((a, b) => a.l!.v - b.l!.v);
      const firstAt = Math.min(...rs.flatMap((r) => r.points.map((p) => Date.parse(`${p.from}T00:00:00Z`))));
      const thenT = win == null ? firstAt : now - win * DAY;
      const thenVals = rs.map((r) => valueOn(r, measure, thenT)).filter((v): v is number => v != null);
      out.push({
        subject, rows: rs, firstAt,
        label: route === "used" ? `${c.make} ${c.model} · any trim, used` : fullName(c),
        href: `/cars/view?id=${encodeURIComponent(c.id)}`,
        now: latest[0]?.l?.v ?? null, nowSource: latest[0]?.r.source_name ?? null,
        then: thenVals.length ? Math.min(...thenVals) : null,
      });
    }
    return out.sort((a, b) => (delta(a) ?? 0) - (delta(b) ?? 0) || (a.now ?? 0) - (b.now ?? 0));
  }, [cars.data, series.data, route, measure, win, now, filters]);

  if (cars.error) return <ErrorNote error={cars.error} />;
  if (series.error) return <ErrorNote error={series.error} />;
  if (!cars.data || !series.data) return <Loading />;

  const from = win == null ? Math.min(now, ...rows.map((r) => r.firstAt)) : now - win * DAY;
  const xDomain: [number, number] = [from, now];
  const chartFor = (r: Row) => clipChart(seriesToChart(r.rows, measure, (s) => s.source_name), win == null ? null : from);
  const day = (ms: number) => new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
  const unit = measure === "true" ? "/mo" : route === "cash" || route === "used" ? "" : "/mo";

  return (
    <div className="space-y-5">
      <PageHeader
        title="Trends"
        subtitle="Every sighting of every car, by route and by source, over time. True £ per month puts cash, PCP, lease and used on one footing: each payment discounted at the savings rate, the car's expected end value credited back as the used market stood on that day, spread over the agreement. 'As printed' is the price or monthly the source showed."
      />
      <FilterBar cars={cars.data} />
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <div className="flex overflow-hidden rounded border border-gray-700">
          {ROUTES.map((r) => (
            <button key={r} onClick={() => setRoute(r)} className={`px-3 py-1 text-xs ${r === route ? "bg-gray-700 text-gray-100" : "text-gray-400 hover:bg-gray-800"}`}>
              {ROUTE_LABEL[r]}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2">
          Show
          <select value={measure} onChange={(e) => setMeasure(e.target.value as Measure)} className="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs">
            <option value="true">true £ per month</option>
            <option value="headline">as printed</option>
          </select>
        </label>
        <WindowPicker value={win} onChange={setWin} />
        <span className="text-gray-500">{rows.length} {route === "used" ? "models" : "cars"} sighted · {rows.reduce((n, r) => n + r.rows.length, 0)} source lines</span>
      </div>

      {rows.length === 0 ? (
        <Empty>No {ROUTE_LABEL[route]} sightings for this selection yet.</Empty>
      ) : (
        <>
          <Card title="Movers">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase text-gray-500">
                  <tr>
                    <th className="py-1 pr-3">{route === "used" ? "Model" : "Car"}</th>
                    <th className="py-1 pr-3 text-right">{measure === "true" ? "True £/mo now" : "As printed now"}</th>
                    <th className="py-1 pr-3 text-right">{win == null ? "Since first seen" : `Over ${win} days`}</th>
                    <th className="py-1 pr-3 text-right">Sources</th>
                    <th className="py-1 pr-3">Cheapest at</th>
                    <th className="py-1">First seen</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const d = delta(r);
                    return (
                      <tr key={r.subject} className="border-t border-gray-800">
                        <td className="py-1 pr-3"><Link href={r.href} className="hover:underline">{r.label}</Link></td>
                        <td className="py-1 pr-3 text-right tabular-nums">{r.now != null ? `${gbp(r.now)}${unit}` : "—"}</td>
                        <td className={`py-1 pr-3 text-right tabular-nums ${d == null ? "text-gray-500" : d < 0 ? "text-emerald-300" : d > 0 ? "text-amber-300" : ""}`}>
                          {d == null ? "no earlier figure" : d === 0 ? "unchanged" : `${d < 0 ? "−" : "+"}${gbp(Math.abs(d))}`}
                        </td>
                        <td className="py-1 pr-3 text-right tabular-nums">{r.rows.length}</td>
                        <td className="py-1 pr-3 text-gray-400">{r.nowSource ?? "—"}</td>
                        <td className="py-1 text-gray-400">{day(r.firstAt)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {rows.slice(0, charts).map((r) => (
              <Card key={r.subject} title={<Link href={r.href} className="normal-case tracking-normal hover:underline">{r.label}</Link>}>
                <LineChart series={chartFor(r)} format={(v) => gbp(v)} height={150} xDomain={xDomain} empty="Nothing sighted in this range." />
              </Card>
            ))}
          </div>
          {rows.length > charts && (
            <div className="flex justify-center">
              <button onClick={() => setCharts((n) => n + CHARTS)} className="rounded border border-gray-700 px-4 py-2 text-sm text-gray-300 hover:bg-gray-800">
                Show {Math.min(CHARTS, rows.length - charts)} more charts of {rows.length}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
