"use client";

import { Suspense, useMemo, useState } from "react";

import { CarTable } from "@/components/CarTable";
import { FilterBar } from "@/components/FilterBar";
import { ErrorNote, Loading, PageHeader } from "@/components/ui";
import { briefAllows, evaluateBrief, type BriefFilter } from "@/lib/brief";
import { carMatches, inScope, useFilters } from "@/lib/filters";
import { useCars, useRequirements } from "@/lib/hooks";

export default function CarsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <Cars />
    </Suspense>
  );
}

function Cars() {
  const { data, error } = useCars();
  const reqs = useRequirements();
  const [filters] = useFilters();
  const [brief, setBrief] = useState<BriefFilter>("all");
  const [minSeats, setMinSeats] = useState(0);

  const rows = useMemo(
    () => (data ?? []).filter((c) => carMatches(c, filters) && briefAllows(brief, evaluateBrief(reqs.data?.hard, c)) && (c.seats ?? 0) >= minSeats),
    [data, filters, brief, minSeats, reqs.data],
  );

  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;

  return (
    <div>
      <PageHeader
        title="Cars"
        subtitle="One row per derivative: the shortlist curated by hand, and with Every EV a row per derivative on sale, its equipment read off the specification page. The brief column is your Requirements page applied to each row."
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
          Brief
          <select value={brief} onChange={(e) => setBrief(e.target.value as BriefFilter)} className="rounded border border-gray-700 bg-gray-900 px-2 py-1">
            <option value="all">every car</option>
            <option value="pass-or-unknown">meets it or not yet confirmed</option>
            <option value="pass">meets it, confirmed</option>
          </select>
        </label>
      </div>
      <CarTable cars={rows} />
    </div>
  );
}
