"use client";

import Link from "next/link";

import { CarImage } from "@/components/CarImage";
import { Sparkline } from "@/components/charts/Sparkline";
import type { CarTrend } from "@/app/page";
import { Badge } from "@/components/ui";
import { briefTicks, budgetGap, IONIQ5_WIDTH_MM, type CarCosts } from "@/lib/costs";
import { carName, gbp, num } from "@/lib/format";
import { ageLabel } from "@/lib/freshness";
import type { SnapshotCar } from "@/lib/types";

interface Props {
  car: SnapshotCar;
  costs: CarCosts;
  trend: CarTrend | null;
  ceiling: number | null;
  starred: boolean;
  onStar: () => void;
  compared: boolean;
  onCompare: () => void;
}

const VERDICT_TONE: Record<string, "good" | "warn" | "bad" | "muted"> = { want: "good", maybe: "warn", no: "bad", control: "muted" };

export function CarCard({ car, costs, trend, ceiling, starred, onStar, compared, onCompare }: Props) {
  const gap = budgetGap(costs.monthly, ceiling);
  const widthDelta = car.width_mm != null ? car.width_mm - IONIQ5_WIDTH_MM : null;
  const route = costs.monthlyRoute === "pcp" ? costs.pcp : costs.monthlyRoute === "pch" ? costs.pch : null;

  return (
    <article className={`flex flex-col overflow-hidden rounded-xl border bg-gray-900 ${compared ? "border-blue-700" : "border-gray-800"}`}>
      <div className="relative aspect-[16/9] w-full">
        <CarImage car={car} />
        <div className="absolute left-2 top-2 flex gap-1">
          {car.picks.map((p, i) => (
            <Badge key={i} tone={VERDICT_TONE[p.verdict] ?? "muted"} title={p.note ?? undefined}>
              {p.who}: {p.verdict}
            </Badge>
          ))}
        </div>
        <button
          onClick={onStar}
          aria-label={starred ? "Remove from my shortlist" : "Add to my shortlist"}
          className={`absolute right-2 top-2 rounded-full bg-gray-950/70 px-2 py-0.5 text-lg ${starred ? "text-amber-300" : "text-gray-400 hover:text-gray-100"}`}
        >
          {starred ? "★" : "☆"}
        </button>
      </div>

      <div className="flex flex-1 flex-col gap-3 p-4">
        <div>
          <Link href={`/cars/view?id=${encodeURIComponent(car.id)}`} className="text-base font-semibold text-gray-100 hover:underline">
            {carName(car)}
          </Link>
          <div className="text-xs text-gray-500">
            {car.packs?.length ? car.packs.join(" + ") : car.used ? "used" : car.body ?? ""}
            {car.auto && (
              <span title={car.notes ?? undefined}>
                {car.packs?.length || car.used || car.body ? " · " : ""}
                {car.source_kind === "stub" ? "from a Carwow deals page" : "from Carwow's specification page"}
                {car.model_year ? ` · ${car.model_year} list` : ""}
              </span>
            )}
          </div>
        </div>

        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-gray-300">
          <li><span className="text-gray-500">seats</span> {num(car.seats)}</li>
          <li><span className="text-gray-500">range</span> {car.wltp_range_mi != null ? `${num(car.wltp_range_mi)} mi` : "—"}</li>
          <li><span className="text-gray-500">charge</span> {car.dc_peak_kw ? `${num(car.dc_peak_kw)} kW` : "—"}</li>
          <li title="width versus the Ioniq 5 (1,890 mm)">
            <span className="text-gray-500">width</span>{" "}
            {widthDelta == null ? "—" : widthDelta === 0 ? "same as Ioniq 5" : widthDelta < 0 ? `${-widthDelta} mm narrower` : `${widthDelta} mm wider`}
          </li>
          {car.powered_sliding_doors ? <li><span className="text-gray-500">sliding doors</span> {car.powered_sliding_doors} powered</li> : null}
        </ul>

        <div className="flex flex-wrap gap-1.5">
          {briefTicks(car).map((t) => (
            <Badge key={t.label} tone={t.ok === true ? "good" : t.ok === false ? "bad" : "muted"}>
              {t.ok === true ? "✓" : t.ok === false ? "✗" : "?"} {t.label}
            </Badge>
          ))}
        </div>

        <div className="mt-auto rounded-lg border border-gray-800 bg-gray-950/60 p-3">
          {costs.monthly != null ? (
            <>
              <div className="flex items-baseline justify-between gap-2">
                <div>
                  <span className="text-2xl font-semibold tabular-nums text-gray-100">{gbp(costs.monthly)}</span>
                  <span className="text-sm text-gray-400">/mo</span>
                  <span className="ml-2 text-xs text-gray-500">
                    {costs.monthlyRoute === "pcp" ? "PCP, nothing down" : "lease, upfront spread"}
                    {route?.dealer ? ` · ${route.dealer}` : ""}
                  </span>
                </div>
                {gap != null && (
                  <Badge tone={gap <= 0 ? "good" : "warn"}>{gap <= 0 ? "within budget" : `+${gbp(gap)} over`}</Badge>
                )}
              </div>
              <div className="mt-1 text-sm text-gray-300">
                {costs.threeYear != null ? <>Over the agreement, handed back: <b className="tabular-nums">{gbp(costs.threeYear)}</b></> : null}
              </div>
              <div className="mt-0.5 text-xs text-gray-500">seen {ageLabel(route?.lastSeenAt)}</div>
            </>
          ) : (
            <div className="text-sm text-gray-500">No current monthly price captured.</div>
          )}
          <div className="mt-2 border-t border-gray-800 pt-2 text-sm text-gray-300">
            {costs.cash ? (
              <>
                <div className="flex items-center justify-between gap-2">
                  <div>
                    Buy outright: <b className="tabular-nums">{gbp(costs.cash.price)}</b>
                    {costs.cash.dealer ? <span className="text-xs text-gray-500"> · {costs.cash.dealer}</span> : null}
                  </div>
                  {trend && trend.points.length >= 2 && (
                    <Sparkline points={trend.points} title={`Best outright price, last ${trend.points.length} days`} />
                  )}
                </div>
                {trend?.movement && <MovementLine m={trend.movement} />}
                {costs.cashThreeYearAtFloor != null && (
                  <div className="text-xs text-gray-500">
                    about {gbp(costs.cashThreeYearAtFloor)} over three years if it is still worth {gbp(costs.pcp?.gfv)} (the finance company&apos;s floor)
                  </div>
                )}
              </>
            ) : (
              <span className="text-gray-500">No current cash price captured.</span>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between text-sm">
          <label className="flex items-center gap-2 text-gray-300">
            <input type="checkbox" checked={compared} onChange={onCompare} /> Compare
          </label>
          <Link href={`/cars/view?id=${encodeURIComponent(car.id)}`} className="text-gray-400 hover:text-gray-100">
            Details and every offer →
          </Link>
        </div>
      </div>
    </article>
  );
}


function MovementLine({ m }: { m: import("@/lib/trends").Movement }) {
  const day = (ms: number) => new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
  if (m.points < 2) return <div className="text-xs text-gray-500">first seen {day(m.firstAt)}; no history yet</div>;
  const d = m.deltaSinceThen ?? m.deltaSinceFirst;
  const since = m.deltaSinceThen != null ? "over 30 days" : `since ${day(m.firstAt)}`;
  return (
    <div className="text-xs">
      {d === 0 ? (
        <span className="text-gray-500">unchanged {since} · at this price {m.daysAtNow} day{m.daysAtNow === 1 ? "" : "s"}</span>
      ) : (
        <span className={d < 0 ? "text-emerald-300" : "text-amber-300"}>
          {d < 0 ? "down" : "up"} {gbp(Math.abs(d))} {since}
          <span className="text-gray-500"> · at this price {m.daysAtNow} day{m.daysAtNow === 1 ? "" : "s"}</span>
        </span>
      )}
    </div>
  );
}
