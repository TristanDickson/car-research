"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { EquipmentCard } from "@/components/EquipmentCard";
import { Pricing } from "@/components/Pricing";
import { Badge, Card, Empty, ErrorNote, Loading, PageHeader, TriBadge } from "@/components/ui";
import { carCosts, ROUTE_LABEL } from "@/lib/costs";
import { FIELDS, GROUPS, show } from "@/lib/fields";
import { carName, gbp, num } from "@/lib/format";
import { useBasis, useCar, useCarDetails, useCostsForCar, useDataPage, useSpecsForCar } from "@/lib/hooks";
import { carPacks } from "@/lib/query";
import type { CarDetails, SnapshotCar } from "@/lib/types";

type Sources = CarDetails["field_sources"];

// Static export: no dynamic segments, so the car id rides a query param.
// useSearchParams needs a Suspense boundary in the exported build.
export default function CarViewPage() {
  return (
    <Suspense fallback={<Loading />}>
      <CarView />
    </Suspense>
  );
}

function CarView() {
  const id = useSearchParams().get("id");
  const car = useCar(id);
  const specs = useSpecsForCar(id);
  const details = useCarDetails(id);
  const costRow = useCostsForCar(id);
  const basis = useBasis();
  const data = useDataPage();

  if (!id) return <Empty>No car selected.</Empty>;
  if (car.error) return <ErrorNote error={car.error} />;
  if (car.data === undefined || costRow.data === undefined) return <Loading />;
  if (car.data === null) return <Empty>Unknown car id: {id}</Empty>;
  const c = car.data;
  const packs = carPacks(c);
  const flagLabels = data.data?.flag_labels ?? {};
  const costs = carCosts(c, costRow.data, data.data?.sources);
  const horizon = basis.data?.term_months ?? 37;
  const from = details.data?.field_sources ?? null;
  const disagreements = details.data?.disagreements ?? null;
  const overruled = details.data?.overruled ?? null;

  return (
    <div className="space-y-6">
      <PageHeader
        title={carName(c)}
        subtitle={
          <>
            {c.cap_name ? <><span className="text-gray-300">{c.cap_name}</span> · </> : null}{c.body ?? ""} · {c.model_year ?? ""} {c.used ? "· used" : ""} ·{" "}
            <Link href="/cars" className="underline">all cars</Link>
            {c.auto && (
              <>
                {" · "}
                <Badge tone="muted" title={c.notes ?? undefined}>
                  {c.source_kind === "stub" ? "generated from a Carwow deals page" : "generated from Carwow's specification page"}
                </Badge>
                {c.make_slug && c.model_slug && (
                  <>
                    {" "}
                    <Link href={`/cars?make=${encodeURIComponent(c.make)}&model=${encodeURIComponent(c.model)}`} className="underline">
                      every {c.make} {c.model} derivative
                    </Link>
                  </>
                )}
              </>
            )}
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Key equipment">
          <Rows
            rows={[
              ["Heat pump", <span key="hp"><TriBadge value={c.heat_pump} detail={c.packs_required?.heat_pump} />{mark(from, "heat_pump")}</span>],
              ["Internal V2L", <span key="iv"><TriBadge value={c.internal_v2l} detail={c.packs_required?.internal_v2l} />{mark(from, "internal_v2l")}</span>],
              ["External V2L", <span key="ev"><TriBadge value={c.external_v2l} />{mark(from, "external_v2l")}</span>],
              ["Seats", num(c.seats)],
              ["Powered sliding doors", c.powered_sliding_doors != null ? String(c.powered_sliding_doors) : "—"],
              ["Memory seats", flag(c.memory_seats)],
              ["Glass roof", flag(c.glass_roof)],
              ["Heated seats", flag(c.heated_seats)],
              ["360 camera", flag(c.camera_360)],
            ]}
          />
          {packs.length > 0 && (
            <p className="mt-2 text-xs text-amber-200/80">
              {packs.map((p) => `${p.pack}${p.price != null ? ` (${gbp(p.price)})` : ""}: ${p.flags.map((f) => flagLabels[f] ?? f.replaceAll("_", " ")).join(", ")}`).join(" · ")}
            </p>
          )}
        </Card>

        <Card title="List price">
          <Rows
            rows={[
              ["List (OTR)", gbp(c.list_price_gbp)],
              ["Government grant", c.grant_gbp ? gbp(c.grant_gbp) : "—"],
              ["List after grant", c.list_price_gbp != null ? gbp(c.list_price_gbp - (c.grant_gbp ?? 0)) : "—"],
              [`Cheapest way to have it, over ${horizon} mo`, costs.trueCost ? `${gbp(costs.trueCost.monthly)}/mo · ${ROUTE_LABEL[costs.trueCost.route]} (${costs.trueCost.sourceName})` : "—"],
              ["Sources pricing it today", String(costs.sources)],
              ["Expected value at term end", costs.stock?.residual ? `${gbp(costs.stock.residual.value)} · ${costs.stock.residual.n} × ${costs.stock.residual.year} examples` : "from the GFV or the assumption"],
              ["Expensive-car VED", c.expensive_car_supplement ? "yes (£440/yr)" : "no"],
              ["Insurance group", src(from, "insurance_group", c.insurance_group ?? "—")],
            ]}
          />
          {c.list_price_breakdown && (
            <p className="mt-2 text-xs text-gray-500">
              {Object.entries(c.list_price_breakdown).map(([k, v]) => `${k} ${gbp(v)}`).join(" + ")}
            </p>
          )}
          {c.pack_prices_gbp && (
            <p className="mt-1 text-xs text-gray-500">
              Packs: {Object.entries(c.pack_prices_gbp).map(([k, v]) => `${k} ${gbp(v)}`).join(", ")}
            </p>
          )}
        </Card>
      </div>

      <Card title="Spec">
        <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
          {GROUPS.filter((g) => g !== "Price and cost" && g !== "Equipment").map((g) => (
            <div key={g}>
              <div className="mb-1 text-xs uppercase tracking-wide text-gray-500">{g}</div>
              <Rows
                rows={FIELDS.filter((x) => x.group === g && x.key !== "curated").map((x) => {
                  const v = show(x, x.value(c, costs));
                  return [x.label, x.field ? src(from, x.field, v) : v];
                })}
              />
            </div>
          ))}
        </div>
        {c.boot_notes && <p className="mt-2 text-xs text-gray-500">{c.boot_notes}</p>}
        {from && Object.keys(from).length > 0 && (
          <p className="mt-3 text-xs text-gray-500">
            ° filled from {Array.from(new Set(Object.values(from))).join("; ")}{c.evdb_url ? <> · <a href={c.evdb_url} target="_blank" rel="noreferrer" className="underline">EV Database page</a></> : null}
          </p>
        )}
        {disagreements && Object.keys(disagreements).length > 0 && (
          <p className="mt-2 text-xs text-gray-500">Sources disagree on {Object.entries(disagreements).map(([k, v]) => `${k.replaceAll("_", " ")} (${v.join(" vs ")})`).join("; ")}; left unknown.</p>
        )}
        {overruled && Object.keys(overruled).length > 0 && (
          <p className="mt-2 text-xs text-gray-500">Set aside by a stronger source: {Object.entries(overruled).map(([k, v]) => `${k.replaceAll("_", " ")} said ${v.join(" / ")}`).join("; ")}.</p>
        )}
      </Card>

      {c.notes && (
        <Card title="Notes">
          <p className="text-sm text-gray-300">{c.notes}</p>
          <p className="mt-2 text-xs text-gray-500">verification: {c.verification ?? "—"}</p>
        </Card>
      )}

      <Pricing car={c} costs={costs} horizon={horizon} sources={data.data?.sources ?? {}} staleDays={data.data?.stale_days ?? 14} />

      <EquipmentCard car={c} specs={specs.data ?? []} specCheck={details.data?.spec_check} flagLabels={data.data?.flag_labels ?? {}} />

    </div>
  );
}


/** A degree sign after a value a source filled in; the Spec card's footnote names them all. */
function mark(from: Sources, field: string): React.ReactNode {
  const by = from?.[field];
  return by ? <span className="ml-1 text-xs text-gray-500" title={`from ${by}`}>°</span> : null;
}

function src(from: Sources, field: string, value: string): React.ReactNode {
  const by = value === "—" ? null : from?.[field];
  return by ? <span title={`from ${by}`}>{value}<span className="ml-0.5 text-xs text-gray-500">°</span></span> : value;
}

function flag(v: boolean | undefined): string {
  return v == null ? "—" : v ? "yes" : "no";
}

function Rows({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-gray-500">{k}</dt>
          <dd className="text-right tabular-nums text-gray-200">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
