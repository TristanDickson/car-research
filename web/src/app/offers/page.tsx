"use client";

import { Suspense, useMemo, useState } from "react";

import { OfferTable } from "@/components/OfferTable";
import { QueryBar } from "@/components/QueryBar";
import { ErrorNote, Loading, PageHeader } from "@/components/ui";
import { isCurrent } from "@/lib/freshness";
import { useDataPage, useOffers } from "@/lib/hooks";
import { useCarQuery } from "@/lib/useCarQuery";
import type { FinanceType } from "@/lib/types";

const TYPES: FinanceType[] = ["pcp", "pch", "cash", "campaign"];

/** Every sighting as a table: the data behind the cards, filtered by the same search. Reached from the Data page. */
export default function OffersPage() {
  return (
    <Suspense fallback={<Loading />}>
      <Offers />
    </Suspense>
  );
}

function Offers() {
  const offers = useOffers();
  const data = useDataPage();
  const { query, set, cars, rows: carRows, options, flagLabels, loading, error } = useCarQuery();
  const [types, setTypes] = useState<Set<FinanceType>>(new Set(["pcp", "pch", "cash"]));
  const [onlyCurrent, setOnlyCurrent] = useState(true);
  const [now] = useState(() => new Date());
  const staleDays = data.data?.stale_days ?? 14;
  const nAuto = useMemo(() => (cars ?? []).filter((c) => c.auto).length, [cars]);

  const carMap = useMemo(() => new Map((cars ?? []).map((c) => [c.id, c])), [cars]);
  const admitted = useMemo(() => new Set(carRows.map((c) => c.id)), [carRows]);
  const rows = useMemo(
    () => (offers.data ?? []).filter((o) => admitted.has(o.car_id) && types.has(o.finance_type) && (!onlyCurrent || isCurrent(o, staleDays, now))),
    [offers.data, admitted, types, onlyCurrent, staleDays, now],
  );

  if (error) return <ErrorNote error={error} />;
  if (offers.error) return <ErrorNote error={offers.error} />;
  if (loading || !offers.data || !cars) return <Loading />;

  function toggleType(t: FinanceType) {
    setTypes((s) => {
      const n = new Set(s);
      if (n.has(t)) n.delete(t);
      else n.add(t);
      return n;
    });
  }

  return (
    <div>
      <PageHeader
        title="Every offer observed"
        subtitle="The raw sightings behind every card, for the cars the search admits. 'Seen' is the last time the source showed the offer; one not seen for a fortnight is stale and drops out of the summaries. The maths is done once at export: implied APR against the stated one, what you pay if you hand back or buy, and the true monthly."
      />
      <QueryBar query={query} set={set} options={options} flagLabels={flagLabels} nAuto={nAuto} count={`${rows.length} of ${offers.data.length} offers`} />
      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
        {TYPES.map((t) => (
          <label key={t} className="flex items-center gap-1">
            <input type="checkbox" checked={types.has(t)} onChange={() => toggleType(t)} />
            {t.toUpperCase()}
          </label>
        ))}
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={onlyCurrent} onChange={(e) => setOnlyCurrent(e.target.checked)} />
          Current only
        </label>
      </div>
      <OfferTable offers={rows} cars={carMap} staleDays={staleDays} />
    </div>
  );
}
