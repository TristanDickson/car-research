"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { EquipmentCard } from "@/components/EquipmentCard";
import { Pricing } from "@/components/Pricing";
import { Badge, Card, Empty, ErrorNote, Loading, PageHeader, TriBadge } from "@/components/ui";
import { carCosts, ROUTE_LABEL } from "@/lib/costs";
import { carName, gbp, num } from "@/lib/format";
import { evaluateBrief } from "@/lib/brief";
import { useCar, useCarDetails, useDataPage, useRequirements, useShortlist, useSpecsForCar, useToggleShortlist } from "@/lib/hooks";
import type { SnapshotCar } from "@/lib/types";

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
  const reqs = useRequirements();
  const data = useDataPage();
  const { data: shortlist } = useShortlist();
  const toggle = useToggleShortlist();

  if (!id) return <Empty>No car selected.</Empty>;
  if (car.error) return <ErrorNote error={car.error} />;
  if (car.data === undefined) return <Loading />;
  if (car.data === null) return <Empty>Unknown car id: {id}</Empty>;
  const c = car.data;
  const picked = (shortlist ?? []).some((s) => s.car_id === c.id);
  const brief = evaluateBrief(reqs.data?.hard, c);
  const costs = carCosts(c);

  return (
    <div className="space-y-6">
      <PageHeader
        title={carName(c)}
        subtitle={
          <>
            {c.body ?? ""} · {c.model_year ?? ""} {c.used ? "· used" : ""} ·{" "}
            <Link href={c.auto ? "/cars?scope=all" : "/cars"} className="underline">all cars</Link>
            {c.auto && (
              <>
                {" · "}
                <Badge tone="muted" title={c.notes ?? undefined}>
                  {c.source_kind === "stub" ? "generated from a Carwow deals page" : "generated from Carwow's specification page"}
                </Badge>
                {c.make_slug && c.model_slug && (
                  <>
                    {" "}
                    <Link href={`/cars?scope=all&make=${encodeURIComponent(c.make)}&model=${encodeURIComponent(c.model)}`} className="underline">
                      every {c.make} {c.model} derivative
                    </Link>
                  </>
                )}
              </>
            )}
          </>
        }
        right={
          <button
            onClick={() => toggle.mutate(c.id)}
            className="rounded border border-gray-700 px-3 py-1 text-sm hover:bg-gray-800"
          >
            {picked ? "★ Shortlisted" : "☆ Shortlist"}
          </button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Brief">
          <div className="mb-3">
            {brief.status === "pass" && <Badge tone="good">meets your hard requirements</Badge>}
            {brief.status === "fail" && <Badge tone="bad">fails: {brief.failedLabels.join(", ")}</Badge>}
            {brief.status === "unknown" && <Badge tone="muted">not confirmed: {brief.unknownLabels.join(", ")}</Badge>}
          </div>
          <Rows
            rows={[
              ["Heat pump", <span key="hp"><TriBadge value={c.heat_pump} detail={c.packs_required?.heat_pump} />{mark(c, "heat_pump")}</span>],
              ["Internal V2L", <span key="iv"><TriBadge value={c.internal_v2l} detail={c.packs_required?.internal_v2l} />{mark(c, "internal_v2l")}</span>],
              ["External V2L", <span key="ev"><TriBadge value={c.external_v2l} />{mark(c, "external_v2l")}</span>],
              ["Seats", num(c.seats)],
              ["Powered sliding doors", c.powered_sliding_doors != null ? String(c.powered_sliding_doors) : "—"],
              ["Memory seats", flag(c.memory_seats)],
              ["Glass roof", flag(c.glass_roof)],
              ["Heated seats", flag(c.heated_seats)],
              ["360 camera", flag(c.camera_360)],
            ]}
          />
          {brief.unknown.length > 0 && (
            <p className="mt-2 text-xs text-gray-500">No source has confirmed: {brief.unknownLabels.join(", ")}. <Link href="/requirements" className="underline">Your rules</Link>.</p>
          )}
        </Card>

        <Card title="Spec">
          <Rows
            rows={[
              ["Battery", num(c.battery_kwh, 1, " kWh")],
              ["WLTP range", num(c.wltp_range_mi, 0, " mi")],
              ["Real range", src(c, "real_range_mi", num(c.real_range_mi, 0, " mi"))],
              ["Power", num(c.power_hp, 0, " hp")],
              ["0–62", src(c, "zero_to_62_s", num(c.zero_to_62_s, 1, " s"))],
              ["Top speed", num(c.top_speed_mph, 0, " mph")],
              ["Efficiency", src(c, "efficiency_mi_kwh", num(c.efficiency_mi_kwh, 1, " mi/kWh"))],
              ["DC peak", num(c.dc_peak_kw, 0, " kW")],
              ["DC 10–80%, average", src(c, "dc_avg_kw", num(c.dc_avg_kw, 0, " kW"))],
              ["10–80% time", num(c.dc_10_80_min, 0, " min")],
              ["AC onboard", src(c, "ac_kw", num(c.ac_kw, 0, " kW"))],
              ["Length × width", `${num(c.length_mm)} × ${num(c.width_mm)} mm`],
              ["Turning circle", num(c.turning_circle_m, 1, " m")],
              ["Boot", src(c, "boot_l", c.boot_l != null ? `${num(c.boot_l)} L${c.boot_max_l ? ` / ${num(c.boot_max_l)} L` : ""}` : "—")],
              ["Weight", src(c, "weight_kg", num(c.weight_kg, 0, " kg"))],
              ["Towing", src(c, "tow_kg", num(c.tow_kg, 0, " kg"))],
              ["Insurance group", c.insurance_group ?? "—"],
            ]}
          />
          {c.boot_notes && <p className="mt-2 text-xs text-gray-500">{c.boot_notes}</p>}
          {c.field_sources && Object.keys(c.field_sources).length > 0 && (
            <p className="mt-2 text-xs text-gray-500">
              ° filled from {Array.from(new Set(Object.values(c.field_sources))).join("; ")}{c.evdb_url ? <> · <a href={c.evdb_url} target="_blank" rel="noreferrer" className="underline">EV Database page</a></> : null}
            </p>
          )}
        </Card>

        <Card title="List price">
          <Rows
            rows={[
              ["List (OTR)", gbp(c.list_price_gbp)],
              ["Government grant", c.grant_gbp ? gbp(c.grant_gbp) : "—"],
              ["List after grant", c.list_price_gbp != null ? gbp(c.list_price_gbp - (c.grant_gbp ?? 0)) : "—"],
              ["Cheapest way to have it", costs.trueCost ? `${gbp(costs.trueCost.monthly)}/mo true · ${ROUTE_LABEL[costs.trueCost.route]} (${costs.trueCost.source})` : "—"],
              ["Sources pricing it today", String(costs.sources)],
              ["Expected value at term end", c.used_stock?.residual ? `${gbp(c.used_stock.residual.value)} · ${c.used_stock.residual.n} × ${c.used_stock.residual.year} examples` : "from the GFV or the assumption"],
              ["Expensive-car VED", c.expensive_car_supplement ? "yes (£440/yr)" : "no"],
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

      {c.notes && (
        <Card title="Notes">
          <p className="text-sm text-gray-300">{c.notes}</p>
          <p className="mt-2 text-xs text-gray-500">verification: {c.verification ?? "—"}</p>
        </Card>
      )}

      <Pricing car={c} costs={costs} details={details.data} staleDays={data.data?.stale_days ?? 14} />

      <EquipmentCard car={c} specs={specs.data ?? []} specCheck={details.data?.spec_check} flagLabels={data.data?.flag_labels ?? {}} />

    </div>
  );
}


/** A degree sign after a value another source filled in; the Spec card's footnote names it. */
function mark(c: SnapshotCar, field: string): React.ReactNode {
  const from = c.field_sources?.[field];
  return from ? <span className="ml-1 text-xs text-gray-500" title={`from ${from}`}>°</span> : null;
}

function src(c: SnapshotCar, field: string, value: string): React.ReactNode {
  const from = c.field_sources?.[field];
  return from ? <span title={`from ${from}`}>{value}<span className="ml-0.5 text-xs text-gray-500">°</span></span> : value;
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
