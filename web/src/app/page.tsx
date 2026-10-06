"use client";

import Link from "next/link";
import { Suspense, useMemo, useState } from "react";

import { CarCard } from "@/components/CarCard";
import { FilterBar } from "@/components/FilterBar";
import { Empty, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { carCosts, type CarCosts } from "@/lib/costs";
import { dailyBest, lastDays, movement, type Movement, type Pt } from "@/lib/trends";
import { carMatches, useFilters } from "@/lib/filters";
import { carName, gbp } from "@/lib/format";
import { useCars, useDataPage, useOffers, useRequirements, useShortlist, useToggleShortlist } from "@/lib/hooks";
import type { SnapshotCar, SnapshotOffer } from "@/lib/types";

type SortKey = "monthly" | "threeYear" | "cash" | "range" | "seats" | "name";

export interface CarTrend {
  /** Best cash price per day, last 90 days. */
  points: Pt[];
  movement: Movement | null;
}

export default function PickPage() {
  return (
    <Suspense fallback={<Loading />}>
      <Pick />
    </Suspense>
  );
}

function Pick() {
  const [filters] = useFilters();
  const cars = useCars();
  const offers = useOffers();
  const reqs = useRequirements();
  const data = useDataPage();
  const shortlist = useShortlist();
  const toggle = useToggleShortlist();

  const [onlyMeets, setOnlyMeets] = useState(true);
  const [onlyPriced, setOnlyPriced] = useState(false);
  const [sort, setSort] = useState<SortKey>("monthly");
  const [compare, setCompare] = useState<string[]>([]);
  const [now] = useState(() => Date.now());

  const staleDays = data.data?.stale_days ?? 14;
  const budget = reqs.data?.budget as { monthly_ceiling_gbp?: number; monthly_tolerance_gbp?: number } | undefined;
  const ceiling = budget?.monthly_ceiling_gbp ?? null;

  const carRows = cars.data;
  const offerRows = offers.data;
  const costsById = useMemo(() => {
    const byCar = new Map<string, SnapshotOffer[]>();
    for (const o of offerRows ?? []) byCar.set(o.car_id, [...(byCar.get(o.car_id) ?? []), o]);
    const out = new Map<string, CarCosts>();
    for (const c of carRows ?? []) out.set(c.id, carCosts(byCar.get(c.id) ?? [], staleDays));
    return out;
  }, [carRows, offerRows, staleDays]);

  const trendById = useMemo(() => {
    const byCar = new Map<string, SnapshotOffer[]>();
    for (const o of offerRows ?? []) byCar.set(o.car_id, [...(byCar.get(o.car_id) ?? []), o]);
    const out = new Map<string, CarTrend>();
    for (const c of carRows ?? []) {
      const daily = dailyBest(byCar.get(c.id) ?? [], "vehicle_price", now, (o) => o.finance_type === "cash" && !o.metrics.skipped);
      out.set(c.id, { points: lastDays(daily, 90, now), movement: movement(daily, 30) });
    }
    return out;
  }, [carRows, offerRows, now]);

  const rows = useMemo(() => {
    const list = (carRows ?? []).filter((c) => carMatches(c, filters) && (!onlyMeets || c.requirement_check.passes) && (!onlyPriced || costsById.get(c.id)?.monthly != null || costsById.get(c.id)?.cash));
    const key = (c: SnapshotCar): number | string | null => {
      const k = costsById.get(c.id)!;
      switch (sort) {
        case "monthly": return k.monthly;
        case "threeYear": return k.threeYear;
        case "cash": return k.cash?.price ?? null;
        case "range": return c.wltp_range_mi == null ? null : -c.wltp_range_mi;
        case "seats": return c.seats == null ? null : -c.seats;
        default: return carName(c);
      }
    };
    return list.sort((a, b) => {
      const ka = key(a), kb = key(b);
      if (ka == null && kb == null) return 0;
      if (ka == null) return 1;
      if (kb == null) return -1;
      return typeof ka === "number" && typeof kb === "number" ? ka - kb : String(ka).localeCompare(String(kb));
    });
  }, [carRows, filters, onlyMeets, onlyPriced, sort, costsById]);

  if (cars.error) return <ErrorNote error={cars.error} />;
  if (!cars.data || !offers.data) return <Loading />;

  const starred = new Set((shortlist.data ?? []).map((s) => s.car_id));
  const toggleCompare = (id: string) =>
    setCompare((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= 4 ? s : [...s, id]));

  return (
    <div className="space-y-5">
      <PageHeader
        title="Pick a car"
        subtitle={
          <>
            Each card shows the cheapest way to have the car each month from the offers we have actually seen, what that adds up to
            over the agreement, and the best price to buy it outright.
            {ceiling != null && <> The budget line is <b>{gbp(ceiling)}/month</b>.</>} Tick cars to compare them side by side.
          </>
        }
      />

      <FilterBar cars={cars.data} />
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={onlyMeets} onChange={(e) => setOnlyMeets(e.target.checked)} /> Meets the brief
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={onlyPriced} onChange={(e) => setOnlyPriced(e.target.checked)} /> Has a current price
        </label>
        <label className="flex items-center gap-2">
          Sort by
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)} className="rounded border border-gray-700 bg-gray-900 px-2 py-1">
            <option value="monthly">cheapest per month</option>
            <option value="threeYear">cheapest over the agreement</option>
            <option value="cash">cheapest to buy</option>
            <option value="range">longest range</option>
            <option value="seats">most seats</option>
            <option value="name">name</option>
          </select>
        </label>
        <span className="text-gray-500">{rows.length} cars</span>
      </div>

      {rows.length === 0 ? (
        <Empty>Nothing matches. Untick a filter.</Empty>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {rows.map((c) => (
            <CarCard
              key={c.id}
              car={c}
              costs={costsById.get(c.id)!}
              trend={trendById.get(c.id) ?? null}
              ceiling={ceiling}
              starred={starred.has(c.id)}
              onStar={() => toggle.mutate(c.id)}
              compared={compare.includes(c.id)}
              onCompare={() => toggleCompare(c.id)}
            />
          ))}
        </div>
      )}

      {compare.length > 0 && (
        <div className="sticky bottom-3 z-10 mx-auto flex w-fit items-center gap-3 rounded-full border border-blue-800 bg-gray-900/95 px-4 py-2 text-sm shadow-lg">
          <span>{compare.length} selected{compare.length === 1 ? " (pick one more)" : ""}</span>
          <Link
            href={`/compare?ids=${compare.map(encodeURIComponent).join(",")}`}
            aria-disabled={compare.length < 2}
            className={`rounded-full px-3 py-1 font-medium ${compare.length < 2 ? "pointer-events-none bg-gray-800 text-gray-500" : "bg-blue-600 text-white hover:bg-blue-500"}`}
          >
            Compare side by side
          </Link>
          <button onClick={() => setCompare([])} className="text-gray-400 hover:text-gray-100">clear</button>
        </div>
      )}
    </div>
  );
}
