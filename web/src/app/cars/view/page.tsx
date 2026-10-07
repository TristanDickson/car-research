"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { EquipmentCard } from "@/components/EquipmentCard";
import { OfferTable } from "@/components/OfferTable";
import { PriceHistory } from "@/components/PriceHistory";
import { Badge, Card, Empty, ErrorNote, Loading, PageHeader, TriBadge } from "@/components/ui";
import { carName, gbp, num } from "@/lib/format";
import { useCar, useDataPage, useOffersForCar, useShortlist, useSpecsForCar, useToggleShortlist } from "@/lib/hooks";
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
  const offers = useOffersForCar(id);
  const specs = useSpecsForCar(id);
  const data = useDataPage();
  const { data: shortlist } = useShortlist();
  const toggle = useToggleShortlist();

  if (!id) return <Empty>No car selected.</Empty>;
  if (car.error) return <ErrorNote error={car.error} />;
  if (car.data === undefined) return <Loading />;
  if (car.data === null) return <Empty>Unknown car id: {id}</Empty>;
  const c = car.data;
  const picked = (shortlist ?? []).some((s) => s.car_id === c.id);

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
            {c.requirement_check.passes ? (
              <Badge tone={c.requirement_check.unknown.length ? "warn" : "good"}>
                meets hard requirements{c.requirement_check.unknown.length ? " (some unverified)" : ""}
              </Badge>
            ) : (
              <Badge tone="bad">fails: {c.requirement_check.failures.join(", ")}</Badge>
            )}
          </div>
          <Rows
            rows={[
              ["Heat pump", <TriBadge key="hp" value={c.heat_pump} detail={c.packs_required?.heat_pump} />],
              ["Internal V2L", <TriBadge key="iv" value={c.internal_v2l} detail={c.packs_required?.internal_v2l} />],
              ["External V2L", <TriBadge key="ev" value={c.external_v2l} />],
              ["Seats", num(c.seats)],
              ["Powered sliding doors", c.powered_sliding_doors != null ? String(c.powered_sliding_doors) : "—"],
              ["Memory seats", flag(c.memory_seats)],
              ["Glass roof", flag(c.glass_roof)],
              ["Heated seats", flag(c.heated_seats)],
              ["360 camera", flag(c.camera_360)],
            ]}
          />
          {c.requirement_check.unknown.length > 0 && (
            <p className="mt-2 text-xs text-gray-500">Unverified: {c.requirement_check.unknown.join(", ")}</p>
          )}
        </Card>

        <Card title="Spec">
          <Rows
            rows={[
              ["Battery", num(c.battery_kwh, 1, " kWh")],
              ["WLTP range", num(c.wltp_range_mi, 0, " mi")],
              ["Real range (est.)", num(c.real_range_mi, 0, " mi")],
              ["Power", num(c.power_hp, 0, " hp")],
              ["Architecture", num(c.architecture_v, 0, " V")],
              ["DC peak", num(c.dc_peak_kw, 0, " kW")],
              ["10–80%", num(c.dc_10_80_min, 0, " min")],
              ["0–62", num(c.zero_to_62_s, 1, " s")],
              ["Efficiency", num(c.efficiency_mi_kwh, 1, " mi/kWh")],
              ["Length × width", `${num(c.length_mm)} × ${num(c.width_mm)} mm`],
              ["Turning circle", num(c.turning_circle_m, 1, " m")],
              ["Boot", c.boot_l != null ? `${num(c.boot_l)} L${c.boot_max_l ? ` / ${num(c.boot_max_l)} L` : ""}` : "—"],
              ["Insurance group", c.insurance_group ?? "—"],
            ]}
          />
          {c.boot_notes && <p className="mt-2 text-xs text-gray-500">{c.boot_notes}</p>}
        </Card>

        <Card title="Price">
          <Rows
            rows={[
              ["List (OTR)", gbp(c.list_price_gbp)],
              ["Government grant", c.grant_gbp ? gbp(c.grant_gbp) : "—"],
              ["List after grant", c.list_price_gbp != null ? gbp(c.list_price_gbp - (c.grant_gbp ?? 0)) : "—"],
              ["Best true £/mo", c.deal_summary.best_true_monthly != null ? withAge(`${gbp(c.deal_summary.best_true_monthly)}/mo via ${c.deal_summary.best_true_route}`, c.deal_summary.true_monthly_by_route?.[c.deal_summary.best_true_route!]?.age_days ?? null) : "—"],
              ["Best current cash", withAge(gbp(c.deal_summary.best_cash_price), c.deal_summary.best_cash_age_days)],
              ["Best current PCP £0 down", withAge(c.deal_summary.best_pcp_monthly != null ? `${gbp(c.deal_summary.best_pcp_monthly)}/mo` : "—", c.deal_summary.best_pcp_age_days)],
              ["Best current PCH effective", withAge(c.deal_summary.best_pch_effective_monthly != null ? `${gbp(c.deal_summary.best_pch_effective_monthly)}/mo` : "—", c.deal_summary.best_pch_age_days)],
              ["Used from", c.used_stock ? `${gbp(c.used_stock.cheapest.price_gbp)} (${c.used_stock.cheapest.year ?? "?"})` : gbp(c.used_from_gbp)],
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

      {c.used_stock && (
        <Card title={`Buy used · ${c.used_stock.count} example${c.used_stock.count === 1 ? "" : "s"} of this model on ${Object.keys(c.used_stock.sources ?? {}).join(", ") || "Carwow"}`}>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="text-sm text-gray-300">
              <div>
                Cheapest: <b className="tabular-nums">{gbp(c.used_stock.cheapest.price_gbp)}</b> · {c.used_stock.cheapest.year ?? "?"} · {num(c.used_stock.cheapest.mileage)} miles
                {c.used_stock.cheapest.town ? ` · ${c.used_stock.cheapest.town}` : ""}
              </div>
              <div className="text-xs text-gray-500">{c.used_stock.cheapest.derivative}</div>
              {c.used_stock.cheapest.url && (
                <a href={c.used_stock.cheapest.url} target="_blank" rel="noreferrer" className="text-xs text-gray-400 underline">
                  listing on {c.used_stock.cheapest.sources?.join(" and ") ?? c.used_stock.cheapest.source ?? "the source"}
                </a>
              )}
              {c.used_stock.sources && Object.keys(c.used_stock.sources).length > 1 && (
                <div className="mt-1 text-xs text-gray-500">
                  {Object.entries(c.used_stock.sources).map(([s, n]) => `${s} ${n}`).join(" · ")} listings; the same car on two sites counts once.
                </div>
              )}
              <div className="mt-2">
                True cost as a route: <b className="tabular-nums">{c.used_stock.route.true_monthly != null ? `${gbp(c.used_stock.route.true_monthly)}/mo` : "—"}</b>
                <span className="text-xs text-gray-500">
                  {" "}· sold after the term at {gbp(c.used_stock.route.expected_value_at_end)} ({c.used_stock.route.residual_source === "used-market" ? "what examples that much older ask today" : "on the flat assumption"})
                </span>
              </div>
            </div>
            <div>
              <div className="mb-1 text-xs uppercase tracking-wide text-gray-500">Asking prices by registration year</div>
              <table className="w-full text-sm">
                <tbody>
                  {Object.entries(c.used_stock.by_year).sort((a, b) => Number(b[0]) - Number(a[0])).map(([y, v]) => (
                    <tr key={y} className="border-t border-gray-800">
                      <td className="py-0.5 pr-3">{y}</td>
                      <td className="py-0.5 pr-3 text-right tabular-nums">{v.n} listed</td>
                      <td className="py-0.5 pr-3 text-right tabular-nums">from {gbp(v.min)}</td>
                      <td className="py-0.5 text-right tabular-nums">median {gbp(v.median)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {c.used_stock.residual && (
                <p className="mt-2 text-xs text-gray-500">
                  The {c.used_stock.residual.year} median ({gbp(c.used_stock.residual.value)}, {c.used_stock.residual.n} cars) is the end-of-term value used for this car&apos;s PCP equity and outright cost.
                </p>
              )}
            </div>
          </div>
        </Card>
      )}

      <EquipmentCard car={c} specs={specs.data ?? []} flagLabels={data.data?.flag_labels ?? {}} />

      <Card title="Price over time">
        <PriceHistory car={c} offers={offers.data ?? []} />
      </Card>

      <Card title={`Price board · ${offers.data?.length ?? 0} offers observed`}>
        {offers.data && offers.data.length > 0 ? (
          <OfferTable offers={offers.data} cars={new Map<string, SnapshotCar>([[c.id, c]])} staleDays={data.data?.stale_days ?? 14} showCar={false} defaultSort={{ key: "true", dir: "asc" }} />
        ) : (
          <Empty>No offers observed for this trim yet.</Empty>
        )}
      </Card>
    </div>
  );
}

function withAge(value: string, days: number | null): string {
  if (days == null || value === "—") return value;
  return `${value} (seen ${days === 0 ? "today" : `${days}d ago`})`;
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
