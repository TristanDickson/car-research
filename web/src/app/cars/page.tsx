"use client";

import { Suspense, useMemo, useState } from "react";

import { CarTable } from "@/components/CarTable";
import { FilterBar } from "@/components/FilterBar";
import { ErrorNote, Loading, PageHeader } from "@/components/ui";
import { carMatches, inScope, useFilters } from "@/lib/filters";
import { useCars } from "@/lib/hooks";

export default function CarsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <Cars />
    </Suspense>
  );
}

function Cars() {
  const { data, error } = useCars();
  const [filters] = useFilters();
  const [onlyMeets, setOnlyMeets] = useState(false);
  const [minSeats, setMinSeats] = useState(0);

  const rows = useMemo(
    () => (data ?? []).filter((c) => carMatches(c, filters) && (!onlyMeets || c.requirement_check.passes) && (c.seats ?? 0) >= minSeats),
    [data, filters, onlyMeets, minSeats],
  );

  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;

  return (
    <div>
      <PageHeader
        title="Cars"
        subtitle="One row per trim. The shortlist is curated by hand (heat pump and internal V2L are what force the trim choice); Every EV adds a row per derivative on sale, generated from Carwow's catalogue, with its equipment read off the specification page. Best cash and Best PCP come from the deals captured for that exact trim."
      />
      <FilterBar cars={data} count={`${rows.length} of ${data.filter((c) => inScope(c, filters)).length}`} />
      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-1">
          Min seats
          <input
            type="number"
            min={0}
            max={9}
            value={minSeats}
            onChange={(e) => setMinSeats(Number(e.target.value) || 0)}
            className="w-14 rounded border border-gray-700 bg-gray-900 px-2 py-1"
          />
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={onlyMeets} onChange={(e) => setOnlyMeets(e.target.checked)} />
          Only cars that meet the hard requirements
        </label>
      </div>
      <CarTable cars={rows} />
    </div>
  );
}
