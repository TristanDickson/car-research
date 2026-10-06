"use client";

import { useMemo, useState } from "react";

import { CarTable } from "@/components/CarTable";
import { ErrorNote, Loading, PageHeader } from "@/components/ui";
import { carName } from "@/lib/format";
import { useCars } from "@/lib/hooks";

export default function CarsPage() {
  const { data, error } = useCars();
  const [q, setQ] = useState("");
  const [onlyMeets, setOnlyMeets] = useState(false);
  const [make, setMake] = useState("");
  const [minSeats, setMinSeats] = useState(0);

  const makes = useMemo(() => Array.from(new Set((data ?? []).map((c) => c.make))).sort(), [data]);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data ?? []).filter(
      (c) =>
        (!onlyMeets || c.requirement_check.passes) &&
        (!make || c.make === make) &&
        (c.seats ?? 0) >= minSeats &&
        (!needle || carName(c).toLowerCase().includes(needle) || (c.notes ?? "").toLowerCase().includes(needle)),
    );
  }, [data, q, onlyMeets, make, minSeats]);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;

  return (
    <div>
      <PageHeader
        title="Cars"
        subtitle="One row per trim that matters. Heat pump and internal V2L are what force the trim choice; Best cash and Best PCP come from the deals captured for that exact trim."
      />
      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search make, model, trim, notes"
          className="w-72 rounded border border-gray-700 bg-gray-900 px-2 py-1 text-gray-100"
        />
        <select value={make} onChange={(e) => setMake(e.target.value)} className="rounded border border-gray-700 bg-gray-900 px-2 py-1">
          <option value="">All makes</option>
          {makes.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
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
        <span className="text-gray-500">{rows.length} of {data.length}</span>
      </div>
      <CarTable cars={rows} />
    </div>
  );
}
