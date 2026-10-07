"use client";

import Link from "next/link";
import { Suspense, useMemo, useState } from "react";

import { CarCard } from "@/components/CarCard";
import { FilterBar } from "@/components/FilterBar";
import { Empty, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { briefAllows, evaluateBrief, type Brief, type BriefFilter } from "@/lib/brief";
import { carCosts, type CarCosts } from "@/lib/costs";
import { allCars, carMatches, useFilters } from "@/lib/filters";
import { carName, gbp } from "@/lib/format";
import { useCars, useRequirements, useShortlist, useToggleShortlist } from "@/lib/hooks";
import type { SnapshotCar } from "@/lib/types";

type SortKey = "true" | "monthly" | "threeYear" | "cash" | "fell" | "range" | "seats" | "name";
/** Cards per page: every EV on sale is ~2,000 derivatives, which no one scrolls. */
const PAGE = 48;

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
  const reqs = useRequirements();
  const shortlist = useShortlist();
  const toggle = useToggleShortlist();

  const [briefFilter, setBriefFilter] = useState<BriefFilter>("pass-or-unknown");
  const [onlyPriced, setOnlyPriced] = useState(false);
  const [sort, setSort] = useState<SortKey>("true");
  const [compare, setCompare] = useState<string[]>([]);
  const [shown, setShown] = useState(PAGE);

  const budget = reqs.data?.budget as { monthly_ceiling_gbp?: number } | undefined;
  const ceiling = budget?.monthly_ceiling_gbp ?? null;
  const rules = reqs.data?.hard;

  // Everything a card shows is on the car record (deal_summary from model/sightings.py); nothing is recomputed here.
  const costsById = useMemo(() => new Map<string, CarCosts>((cars.data ?? []).map((c) => [c.id, carCosts(c)])), [cars.data]);
  const briefById = useMemo(() => new Map<string, Brief>((cars.data ?? []).map((c) => [c.id, evaluateBrief(rules, c)])), [cars.data, rules]);

  const rows = useMemo(() => {
    const list = (cars.data ?? []).filter((c) =>
      carMatches(c, filters)
      && briefAllows(briefFilter, briefById.get(c.id)!)
      && (!onlyPriced || costsById.get(c.id)!.trueCost != null));
    const key = (c: SnapshotCar): number | string | null => {
      const k = costsById.get(c.id)!;
      switch (sort) {
        case "true": return k.trueCost?.monthly ?? null;
        case "monthly": return k.monthly;
        case "threeYear": return k.threeYear;
        case "cash": return k.cash?.price ?? null;
        case "fell": return c.deal_summary.trend?.delta ?? null;
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
  }, [cars.data, filters, briefFilter, onlyPriced, sort, costsById, briefById]);
  const nAuto = useMemo(() => (cars.data ?? []).filter((c) => c.auto).length, [cars.data]);

  if (cars.error) return <ErrorNote error={cars.error} />;
  if (!cars.data || reqs.data === undefined) return <Loading />;

  const starred = new Set((shortlist.data ?? []).map((s) => s.car_id));
  const toggleCompare = (id: string) =>
    setCompare((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= 4 ? s : [...s, id]));

  return (
    <div className="space-y-5">
      <PageHeader
        title="Pick a car"
        subtitle={
          <>
            Each card puts every way of having the car on one footing: cash, PCP, lease and used as a true cost per month, with what the car
            is expected to be worth at the end of the term. {ceiling != null && <>Your budget line is <b>{gbp(ceiling)}/month</b> (<Link href="/requirements" className="underline">change it</Link>).</>}{" "}
            Tick cars to compare them side by side.
          </>
        }
      />

      <FilterBar cars={cars.data} />
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-2">
          Brief
          <select value={briefFilter} onChange={(e) => setBriefFilter(e.target.value as BriefFilter)} className="rounded border border-gray-700 bg-gray-900 px-2 py-1">
            <option value="pass">meets it, confirmed</option>
            <option value="pass-or-unknown">meets it or not yet confirmed</option>
            <option value="all">every car</option>
          </select>
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={onlyPriced} onChange={(e) => setOnlyPriced(e.target.checked)} /> Has a current price
        </label>
        <label className="flex items-center gap-2">
          Sort by
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)} className="rounded border border-gray-700 bg-gray-900 px-2 py-1">
            <option value="true">cheapest true cost per month</option>
            <option value="monthly">cheapest to pay monthly</option>
            <option value="threeYear">cheapest over the agreement</option>
            <option value="cash">cheapest to buy</option>
            <option value="fell">biggest price fall, 30 days</option>
            <option value="range">longest range</option>
            <option value="seats">most seats</option>
            <option value="name">name</option>
          </select>
        </label>
        <span className="text-gray-500">{rows.length} cars</span>
      </div>

      {rows.length === 0 ? (
        <Empty>
          Nothing matches. Loosen a filter.
          {!allCars(filters) && nAuto > 0 && (
            <>
              {" "}
              <Link href={`?${new URLSearchParams({ ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)), scope: "all" }).toString()}`} className="underline">
                Look across every EV on sale
              </Link>{" "}
              ({nAuto} more derivatives).
            </>
          )}
        </Empty>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {rows.slice(0, shown).map((c) => (
            <CarCard
              key={c.id}
              car={c}
              costs={costsById.get(c.id)!}
              brief={briefById.get(c.id)!}
              ceiling={ceiling}
              starred={starred.has(c.id)}
              onStar={() => toggle.mutate(c.id)}
              compared={compare.includes(c.id)}
              onCompare={() => toggleCompare(c.id)}
            />
          ))}
        </div>
      )}

      {rows.length > shown && (
        <div className="flex justify-center">
          <button onClick={() => setShown((n) => n + PAGE)} className="rounded border border-gray-700 px-4 py-2 text-sm text-gray-300 hover:bg-gray-800">
            Show {Math.min(PAGE, rows.length - shown)} more of {rows.length}
          </button>
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
