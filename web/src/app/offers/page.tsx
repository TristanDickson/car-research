"use client";

import { useMemo, useState } from "react";

import { OfferTable } from "@/components/OfferTable";
import { ErrorNote, Loading, PageHeader } from "@/components/ui";
import { carName } from "@/lib/format";
import { isCurrent } from "@/lib/freshness";
import { useCars, useDataPage, useOffers } from "@/lib/hooks";
import type { FinanceType } from "@/lib/types";

const TYPES: FinanceType[] = ["pcp", "pch", "cash", "campaign"];

export default function OffersPage() {
  const offers = useOffers();
  const cars = useCars();
  const data = useDataPage();
  const [types, setTypes] = useState<Set<FinanceType>>(new Set(["pcp", "pch", "cash"]));
  const [onlyCurrent, setOnlyCurrent] = useState(true);
  const [q, setQ] = useState("");
  const staleDays = data.data?.stale_days ?? 14;

  const carMap = useMemo(() => new Map((cars.data ?? []).map((c) => [c.id, c])), [cars.data]);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const now = new Date();
    return (offers.data ?? []).filter((o) => {
      if (!types.has(o.finance_type)) return false;
      if (onlyCurrent && !isCurrent(o, staleDays, now)) return false;
      if (!needle) return true;
      const c = carMap.get(o.car_id);
      const hay = `${c ? carName(c) : o.car_id} ${o.dealer ?? ""} ${o.source ?? ""} ${o.notes ?? ""}`.toLowerCase();
      return hay.includes(needle);
    });
  }, [offers.data, types, onlyCurrent, q, carMap, staleDays]);

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
      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search car, dealer, source, notes"
          className="w-72 rounded border border-gray-700 bg-gray-900 px-2 py-1 text-gray-100"
        />
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
        <span className="text-gray-500">{rows.length} of {offers.data.length}</span>
      </div>
      <OfferTable offers={rows} cars={carMap} staleDays={staleDays} />
    </div>
  );
}
