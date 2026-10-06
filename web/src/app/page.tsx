"use client";

import Link from "next/link";

import { CarTable } from "@/components/CarTable";
import { Card, Empty, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { gbp } from "@/lib/format";
import { useCars, useDeals, useRequirements, useShortlist } from "@/lib/hooks";

export default function OverviewPage() {
  const cars = useCars();
  const deals = useDeals();
  const reqs = useRequirements();
  const shortlist = useShortlist();

  if (cars.error) return <ErrorNote error={cars.error} />;
  if (!cars.data || !deals.data) return <Loading />;

  const meets = cars.data.filter((c) => c.requirement_check.passes);
  const picked = new Set((shortlist.data ?? []).map((s) => s.car_id));
  const shortlisted = cars.data.filter((c) => picked.has(c.id));
  const active = deals.data.filter((d) => ["live", "lead", "derived"].includes(d.status));
  const budget = reqs.data?.budget as { monthly_ceiling_gbp?: number; monthly_tolerance_gbp?: number } | undefined;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Overview"
        subtitle={
          <>
            Every deal normalised to £0 deposit and total cost, measured against the best confirmed cash price for the
            same car. The GFV is a floor, not a forecast. Rules and context live in the repo under <code>docs/</code>.
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Cars captured" value={String(cars.data.length)} sub={`${meets.length} meet the hard requirements`} />
        <Stat label="Deals captured" value={String(deals.data.length)} sub={`${active.length} live, lead or derived`} />
        <Stat
          label="Budget line"
          value={budget?.monthly_ceiling_gbp != null ? `${gbp(budget.monthly_ceiling_gbp)}/mo` : "—"}
          sub={budget?.monthly_tolerance_gbp != null ? `tolerance ${gbp(budget.monthly_tolerance_gbp)}/mo` : ""}
        />
        <Stat label="Shortlisted" value={String(shortlisted.length)} sub="saved in this browser" />
      </div>

      <Card title="Shortlist">
        {shortlisted.length ? (
          <CarTable cars={shortlisted} />
        ) : (
          <Empty>
            Nothing shortlisted yet. Star cars on the <Link href="/cars" className="underline">Cars</Link> page.
          </Empty>
        )}
      </Card>

      <Card title="Cars that meet the hard requirements">
        <CarTable cars={meets} />
      </Card>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
      <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="mt-1 text-xs text-gray-400">{sub}</div>}
    </div>
  );
}
