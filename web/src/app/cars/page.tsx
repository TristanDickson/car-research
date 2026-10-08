"use client";

import { Suspense } from "react";

import { CarTable } from "@/components/CarTable";
import { QueryBar } from "@/components/QueryBar";
import { ErrorNote, Loading, PageHeader } from "@/components/ui";
import { useBasis } from "@/lib/hooks";
import { useCarQuery } from "@/lib/useCarQuery";

export default function CarsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <Cars />
    </Suspense>
  );
}

function Cars() {
  const { query, set, cars, rows, ctxOf, options, flagLabels, loading, error } = useCarQuery();
  const basis = useBasis();

  if (error) return <ErrorNote error={error} />;
  if (loading || !cars) return <Loading />;

  return (
    <div>
      <PageHeader
        title="Cars"
        subtitle="The same search as the cards, one row per derivative. Pick the columns and their order with Columns; the car stays in view when the table scrolls sideways."
      />
      <QueryBar query={query} set={set} options={options} flagLabels={flagLabels} count={`${rows.length} of ${cars.length}`} />
      <CarTable cars={rows} ctxOf={ctxOf} horizon={basis.data?.term_months ?? 37} />
    </div>
  );
}
