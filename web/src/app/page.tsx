"use client";

import Link from "next/link";
import { Suspense, useMemo, useState } from "react";

import { CarCard } from "@/components/CarCard";
import { QueryBar } from "@/components/QueryBar";
import { Empty, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { gbp } from "@/lib/format";
import { useToggleShortlist } from "@/lib/hooks";
import { allCars, withQuery } from "@/lib/query";
import { useCarQuery } from "@/lib/useCarQuery";

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
  const { query, set, cars, rows, ctxOf, options, flagLabels, budgetCeiling, loading, error } = useCarQuery();
  const toggle = useToggleShortlist();
  const [compare, setCompare] = useState<string[]>([]);
  const [shown, setShown] = useState(PAGE);
  const nAuto = useMemo(() => (cars ?? []).filter((c) => c.auto).length, [cars]);

  if (error) return <ErrorNote error={error} />;
  if (loading || !cars) return <Loading />;

  const toggleCompare = (id: string) =>
    setCompare((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= 4 ? s : [...s, id]));

  return (
    <div className="space-y-5">
      <PageHeader
        title="Pick a car"
        subtitle={
          <>
            Each card puts every way of having the car on one footing: cash, PCP, lease and used as a true cost per month, with what the car
            is expected to be worth at the end of the term. {budgetCeiling != null && <>Your budget line is <b>{gbp(budgetCeiling)}/month</b> (<Link href="/requirements" className="underline">change it</Link>).</>}{" "}
            Tick cars to compare them side by side.
          </>
        }
      />

      <QueryBar query={query} set={set} options={options} flagLabels={flagLabels} nAuto={nAuto} count={`${rows.length} cars`} />

      {rows.length === 0 ? (
        <Empty>
          Nothing matches. Loosen a filter.
          {!allCars(query) && nAuto > 0 && (
            <>
              {" "}
              <Link href={withQuery("/", { ...query, scope: "all" })} className="underline">Look across every EV on sale</Link> ({nAuto} more derivatives).
            </>
          )}
        </Empty>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {rows.slice(0, shown).map((c) => {
            const ctx = ctxOf(c);
            return (
              <CarCard
                key={c.id}
                car={c}
                costs={ctx.costs}
                brief={ctx.brief}
                ceiling={budgetCeiling}
                starred={ctx.starred}
                onStar={() => toggle.mutate(c.id)}
                compared={compare.includes(c.id)}
                onCompare={() => toggleCompare(c.id)}
              />
            );
          })}
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
