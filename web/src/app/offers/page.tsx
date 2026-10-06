"use client";

import { Suspense, useMemo, useState } from "react";

import { FilterBar } from "@/components/FilterBar";
import { OfferTable } from "@/components/OfferTable";
import { ErrorNote, Loading, PageHeader } from "@/components/ui";
import { offerMatches, useFilters } from "@/lib/filters";
import { isCurrent } from "@/lib/freshness";
import { useCars, useDataPage, useOffers } from "@/lib/hooks";
import type { FinanceType } from "@/lib/types";

const TYPES: FinanceType[] = ["pcp", "pch", "cash", "campaign"];

export default function OffersPage() {
  return (
    <Suspense fallback={<Loading />}>
      <Offers />
    </Suspense>
  );
}

function Offers() {
  const offers = useOffers();
  const cars = useCars();
  const data = useDataPage();
  const [filters] = useFilters();
  const [types, setTypes] = useState<Set<FinanceType>>(new Set(["pcp", "pch", "cash"]));
  const [onlyCurrent, setOnlyCurrent] = useState(true);
  const [now] = useState(() => new Date());
  const staleDays = data.data?.stale_days ?? 14;

  const carMap = useMemo(() => new Map((cars.data ?? []).map((c) => [c.id, c])), [cars.data]);

  const rows = useMemo(
    () => (offers.data ?? []).filter((o) => types.has(o.finance_type) && (!onlyCurrent || isCurrent(o, staleDays, now)) && offerMatches(o, carMap.get(o.car_id), filters)),
    [offers.data, types, onlyCurrent, filters, carMap, staleDays, now],
  );

  if (offers.error) return <ErrorNote error={offers.error} />;
  if (!offers.data || !cars.data) return <Loading />;

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
        title="Offers"
        subtitle="Every offer observed, by source and date. 'Seen' is the last time the source showed it; an active offer not seen for a fortnight is stale and drops out of the best-price summaries. The finance maths is done once at export: implied APR as a check on the stated one, what you pay if you hand back or buy, and the premium and effective rate against the best cash price for the same car."
      />
      <FilterBar cars={cars.data} count={`${rows.length} of ${offers.data.length}`} />
      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
        {TYPES.map((t) => (
          <label key={t} className="flex items-center gap-1">
            <input type="checkbox" checked={types.has(t)} onChange={() => toggleType(t)} />
            {t.toUpperCase()}
          </label>
        ))}
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={onlyCurrent} onChange={(e) => setOnlyCurrent(e.target.checked)} />
          Current only (hide stale, gone, expired, historical, campaign)
        </label>
      </div>
      <OfferTable offers={rows} cars={carMap} staleDays={staleDays} />
    </div>
  );
}
