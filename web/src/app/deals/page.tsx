"use client";

import { useMemo, useState } from "react";

import { DealTable } from "@/components/DealTable";
import { ErrorNote, Loading, PageHeader } from "@/components/ui";
import { carName } from "@/lib/format";
import { useCars, useDeals } from "@/lib/hooks";
import type { FinanceType } from "@/lib/types";

const TYPES: FinanceType[] = ["pcp", "pch", "cash", "campaign"];
const HIDDEN_BY_DEFAULT = new Set(["expired", "historical", "campaign"]);

export default function DealsPage() {
  const deals = useDeals();
  const cars = useCars();
  const [types, setTypes] = useState<Set<FinanceType>>(new Set(["pcp", "pch", "cash"]));
  const [showInactive, setShowInactive] = useState(false);
  const [q, setQ] = useState("");

  const carMap = useMemo(() => new Map((cars.data ?? []).map((c) => [c.id, c])), [cars.data]);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (deals.data ?? []).filter((d) => {
      if (!types.has(d.finance_type)) return false;
      if (!showInactive && HIDDEN_BY_DEFAULT.has(d.status)) return false;
      if (!needle) return true;
      const c = carMap.get(d.car_id);
      const hay = `${c ? carName(c) : d.car_id} ${d.dealer ?? ""} ${d.source ?? ""} ${d.notes ?? ""}`.toLowerCase();
      return hay.includes(needle);
    });
  }, [deals.data, types, showInactive, q, carMap]);

  if (deals.error) return <ErrorNote error={deals.error} />;
  if (!deals.data || !cars.data) return <Loading />;

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
        title="Deals"
        subtitle="Every offer captured, dated and sourced, with the finance maths done once at export: implied APR as a check on the stated one, what you pay if you hand back or buy, and the premium and effective rate against the best cash price for the same car."
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
          <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
          Show expired / historical / campaign
        </label>
        <span className="text-gray-500">{rows.length} of {deals.data.length}</span>
      </div>
      <DealTable deals={rows} cars={carMap} />
    </div>
  );
}
