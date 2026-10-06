"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { LineChart } from "@/components/charts/LineChart";
import { WindowPicker, type Window } from "@/components/PriceHistory";
import { Card, Empty, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { carName, gbp, pct } from "@/lib/format";

const fullName = (c: SnapshotCar) => carName(c) + (c.packs?.length ? ` + ${c.packs.join(" + ")}` : "");
import { useCars, useOffers } from "@/lib/hooks";
import { dailyBest, discountSeries, lastDays, movement, type DailyPoint, type Movement, type Series } from "@/lib/trends";
import type { SnapshotCar, SnapshotOffer } from "@/lib/types";

type Metric = "discount" | "cash";

interface Row {
  car: SnapshotCar;
  daily: DailyPoint[];
  move: Movement | null;
  discountNow: number | null;
  source: string | null;
}

const DAY = 86_400_000;

/**
 * Market view: how each car's best outright price has moved. One small chart
 * per car (same axis, same window) and a movers table that is the chart twin.
 */
export default function MarketPage() {
  const cars = useCars();
  const offers = useOffers();
  const [win, setWin] = useState<Window>(90);
  const [metric, setMetric] = useState<Metric>("discount");
  const [now] = useState(() => Date.now());

  const rows = useMemo<Row[]>(() => {
    const byCar = new Map<string, SnapshotOffer[]>();
    for (const o of offers.data ?? []) byCar.set(o.car_id, [...(byCar.get(o.car_id) ?? []), o]);
    const out: Row[] = [];
    for (const c of cars.data ?? []) {
      const list = byCar.get(c.id) ?? [];
      const daily = dailyBest(list, "vehicle_price", now, (o) => o.finance_type === "cash" && !o.metrics.skipped);
      if (!daily.length) continue;
      const last = daily[daily.length - 1];
      const src = list.find((o) => o.id === last.offerId);
      out.push({
        car: c, daily, move: movement(daily, win ?? 30),
        discountNow: c.list_price_gbp ? 1 - last.v / c.list_price_gbp : null,
        source: src ? src.dealer ?? src.source ?? null : null,
      });
    }
    return out.sort((a, b) => (a.move?.deltaSinceThen ?? a.move?.deltaSinceFirst ?? 0) - (b.move?.deltaSinceThen ?? b.move?.deltaSinceFirst ?? 0));
  }, [cars.data, offers.data, win, now]);

  if (cars.error) return <ErrorNote error={cars.error} />;
  if (!cars.data || !offers.data) return <Loading />;

  const xDomain: [number, number] = [
    win == null ? Math.min(...rows.map((r) => r.daily[0]?.t ?? now)) : now - win * DAY,
    now,
  ];
  const fmt = metric === "discount" ? (v: number) => pct(v, 1) : (v: number) => gbp(v);
  const seriesFor = (r: Row): Series[] => {
    const pts = lastDays(metric === "discount" ? discountSeries(r.daily, r.car.list_price_gbp) : r.daily, win, now);
    return pts.length ? [{ id: r.car.id, label: fullName(r.car), segments: [pts], slot: 0 }] : [];
  };
  const day = (ms: number) => new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Trends"
        subtitle="How the best outright price of each car has moved, from every sighting we have. A nightly scrape adds a point per day; the Carwow quotes from September start the lines earlier."
      />
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <WindowPicker value={win} onChange={setWin} />
        <label className="flex items-center gap-2">
          Show
          <select value={metric} onChange={(e) => setMetric(e.target.value as Metric)} className="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs">
            <option value="discount">discount against list</option>
            <option value="cash">best outright price</option>
          </select>
        </label>
        <span className="text-gray-500">{rows.length} cars with a cash price</span>
      </div>

      {rows.length === 0 ? (
        <Empty>No cash prices observed yet.</Empty>
      ) : (
        <>
          <Card title="Movers">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase text-gray-500">
                  <tr>
                    <th className="py-1 pr-3">Car</th>
                    <th className="py-1 pr-3 text-right">Best outright</th>
                    <th className="py-1 pr-3 text-right">Off list</th>
                    <th className="py-1 pr-3 text-right">{win == null ? "Since first seen" : `Over ${win} days`}</th>
                    <th className="py-1 pr-3 text-right">At this price</th>
                    <th className="py-1 pr-3">First seen</th>
                    <th className="py-1">Where</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const d = win == null ? r.move?.deltaSinceFirst ?? null : r.move?.deltaSinceThen ?? null;
                    return (
                      <tr key={r.car.id} className="border-t border-gray-800">
                        <td className="py-1 pr-3"><Link href={`/cars/view?id=${encodeURIComponent(r.car.id)}`} className="hover:underline">{fullName(r.car)}</Link></td>
                        <td className="py-1 pr-3 text-right tabular-nums">{gbp(r.move?.now)}</td>
                        <td className="py-1 pr-3 text-right tabular-nums">{r.discountNow == null ? "—" : pct(r.discountNow, 0)}</td>
                        <td className={`py-1 pr-3 text-right tabular-nums ${d == null ? "text-gray-500" : d < 0 ? "text-emerald-300" : d > 0 ? "text-amber-300" : ""}`}>
                          {d == null ? "no earlier price" : d === 0 ? "unchanged" : `${d < 0 ? "−" : "+"}${gbp(Math.abs(d))}`}
                        </td>
                        <td className="py-1 pr-3 text-right tabular-nums">{r.move ? `${r.move.daysAtNow}d` : "—"}</td>
                        <td className="py-1 pr-3 text-gray-400">{r.move ? day(r.move.firstAt) : "—"}</td>
                        <td className="py-1 text-gray-400">{r.source ?? "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {rows.map((r) => (
              <Card key={r.car.id} title={<Link href={`/cars/view?id=${encodeURIComponent(r.car.id)}`} className="normal-case tracking-normal hover:underline">{fullName(r.car)}</Link>}>
                <LineChart series={seriesFor(r)} format={fmt} height={150} xDomain={xDomain}
                  reference={metric === "cash" && r.car.list_price_gbp ? { value: r.car.list_price_gbp - (r.car.grant_gbp ?? 0), label: "list after grant" } : null}
                  empty={metric === "discount" && !r.car.list_price_gbp ? "No list price to compare against." : "No price in this range."} />
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
