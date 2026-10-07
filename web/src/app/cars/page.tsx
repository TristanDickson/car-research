"use client";

import { Suspense, useMemo } from "react";

import { CarTable } from "@/components/CarTable";
import { QueryBar } from "@/components/QueryBar";
import { ErrorNote, Loading, PageHeader } from "@/components/ui";
import { useCarQuery } from "@/lib/useCarQuery";

export default function CarsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <Cars />
    </Suspense>
  );
}

function Cars() {
  const { query, set, cars, rows, options, flagLabels, loading, error } = useCarQuery();
  const nAuto = useMemo(() => (cars ?? []).filter((c) => c.auto).length, [cars]);
  const inScope = useMemo(() => (cars ?? []).filter((c) => query.scope === "all" || !c.auto).length, [cars, query.scope]);

  if (error) return <ErrorNote error={error} />;
  if (loading || !cars) return <Loading />;

  return (
    <div>
      <PageHeader
        title="Cars"
        subtitle="The same search as the cards, one row per derivative: the shortlist curated by hand, and with Every EV a row per derivative on sale. The brief column is your Requirements page applied to each row."
      />
      <QueryBar query={query} set={set} options={options} flagLabels={flagLabels} nAuto={nAuto} count={`${rows.length} of ${inScope}`} />
      <CarTable cars={rows} />
    </div>
  );
}
