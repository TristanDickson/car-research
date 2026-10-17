"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { DataTable, type Column } from "@/components/DataTable";
import { Badge, Card, Empty } from "@/components/ui";
import { carName } from "@/lib/format";
import { OUTCOMES, filterChanges, orderChanges, outcomeWords, sourceName, sumCounts } from "@/lib/resolverChanges";
import type { ResolverChange, ResolverSection, SnapshotCar } from "@/lib/types";

const n = (v: number | undefined) => (v ?? 0).toLocaleString("en-GB");
const TONE = { lost: "bad", moved: "warn", "to best spec": "muted", "newly placed": "good", unplaced: "muted", same: "muted" } as const;

/**
 * What would change if the app's cars came from the resolver (ticket T3): the totals by source, then the
 * changes one row per record or group of alike records. The app still shows today's cars.
 */
export function ResolverComparison({ resolver, cars }: { resolver: ResolverSection; cars: SnapshotCar[] }) {
  const [source, setSource] = useState("all");
  const [outcome, setOutcome] = useState("all");
  const carById = useMemo(() => new Map(cars.map((c) => [c.id, c])), [cars]);
  const name = sourceName;
  const ordered = useMemo(() => orderChanges(resolver.changes), [resolver.changes]);
  const rows = useMemo(() => filterChanges(ordered, source, outcome), [ordered, source, outcome]);
  const sourceNames = useMemo(() => Object.keys(resolver.by_source), [resolver.by_source]);
  const kinds = useMemo(() => OUTCOMES.filter((o) => o.key !== "same" && resolver.changes.some((c) => c.outcome === o.key)), [resolver.changes]);
  const totals = useMemo(() => sumCounts(Object.values(resolver.by_source)), [resolver.by_source]);

  const columns = useMemo<Column<ResolverChange>[]>(() => {
    const carLabel = (id: string) => {
      const c = carById.get(id);
      return c ? <Link href={`/cars/view?id=${encodeURIComponent(id)}`} className="hover:underline">{carName(c)}</Link> : <span className="font-mono text-xs text-gray-400">{id}</span>;
    };
    return [
      { key: "source", header: "Source", render: (r) => sourceName(r.source), sortValue: (r) => r.source },
      { key: "model", header: "Model", render: (r) => <span className="font-mono text-xs text-gray-400">{r.model ?? "—"}</span>, sortValue: (r) => r.model },
      { key: "outcome", header: "What changes", render: (r) => <Badge tone={TONE[r.outcome]} title={outcomeWords(r.outcome)}>{r.outcome === "unplaced" ? "placed by neither" : r.outcome}</Badge>, sortValue: (r) => r.outcome },
      { key: "label", header: "The record as printed", render: (r) => <span className="text-gray-200">{r.label || "—"}</span>, sortValue: (r) => r.label },
      {
        key: "today", header: "Today's car",
        render: (r) => r.today.length === 0 ? "—" : (
          <div className="space-y-0.5">{r.today.slice(0, 3).map((id) => <div key={id}>{carLabel(id)}</div>)}
            {r.today.length > 3 && <div className="text-xs text-gray-500">and {r.today.length - 3} more</div>}</div>
        ),
      },
      {
        key: "car", header: "The resolver's car",
        render: (r) => r.car ? (
          <div>{carLabel(r.car)}
            {r.others_count > 0 && <div className="text-xs text-gray-500" title={r.others.join("\n")}>or {r.others_count} other{r.others_count === 1 ? "" : "s"} it could have been</div>}
          </div>
        ) : "—",
      },
      { key: "why", header: "Why", render: (r) => <span className="text-xs text-gray-400">{r.why ?? "—"}</span> },
      { key: "records", header: "Records", align: "right", render: (r) => n(r.records), sortValue: (r) => r.records },
    ];
  }, [carById]);

  const pill = (active: boolean) => `rounded border px-2 py-0.5 ${active ? "border-gray-500 bg-gray-700 text-gray-100" : "border-gray-700 text-gray-400"}`;
  const perSource = Object.entries(resolver.by_source);
  const th = "py-1 pr-3 text-right";

  return (
    <Card title={`If the cars came from the resolver · ${resolver.changes.length.toLocaleString("en-GB")} changes to go through`}>
      <p className="mb-2 text-sm text-gray-400">
        The resolver is the new way of choosing which car a record belongs to (an offer, a used listing, a spec sheet). This is what would change if the app&apos;s cars came from it, for you to go through before the switch.
        The app still shows today&apos;s cars. Each record either keeps its car, goes to the best spec of the cars it fits (today&apos;s car included), moves to another car, gets a car it has none of today, loses its car,
        or is placed by neither. Records of the same text and the same cars are one row.
      </p>
      <div className="mb-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-gray-500">
            <tr><th className="py-1 pr-3">Source</th>{OUTCOMES.map((o) => <th key={o.key} className={th} title={o.long}>{o.short}</th>)}<th className="py-1 text-right" title="Records the resolver lists for you to look at">listed</th></tr>
          </thead>
          <tbody>
            {perSource.map(([s, t]) => (
              <tr key={s} className="border-t border-gray-800">
                <td className="py-1 pr-3">{name(s)}</td>
                {OUTCOMES.map((o) => <td key={o.key} className="py-1 pr-3 text-right tabular-nums">{n(t[o.key])}</td>)}
                <td className="py-1 text-right tabular-nums">{n(t.listed)}</td>
              </tr>
            ))}
            <tr className="border-t border-gray-700 font-medium text-gray-100">
              <td className="py-1 pr-3">All sources</td>
              {OUTCOMES.map((o) => <td key={o.key} className="py-1 pr-3 text-right tabular-nums">{n(totals[o.key])}</td>)}
              <td className="py-1 text-right tabular-nums">{n(totals.listed)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="mb-3 text-xs text-gray-500">
        Cars the resolver makes: {Object.entries(resolver.cars).map(([k, v]) => `${v.toLocaleString("en-GB")} from ${name(k.replace(" (no longer on sale)", ""))}${k.includes("no longer") ? " (no longer on sale)" : ""}`).join(", ")}.
        The resolver&apos;s own cars that the app does not carry yet are named the way the resolver names them (make, model, body and year, then the motor and trim).
      </p>

      <div className="mb-2 flex flex-wrap items-center gap-1 text-xs">
        <span className="mr-1 text-gray-500">Source</span>
        <button onClick={() => setSource("all")} className={pill(source === "all")}>all</button>
        {sourceNames.filter((s) => resolver.changes.some((c) => c.source === s)).map((s) => <button key={s} onClick={() => setSource(s)} className={pill(source === s)}>{name(s)}</button>)}
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-1 text-xs">
        <span className="mr-1 text-gray-500">Change</span>
        <button onClick={() => setOutcome("all")} className={pill(outcome === "all")}>all</button>
        {kinds.map((o) => <button key={o.key} onClick={() => setOutcome(o.key)} className={pill(outcome === o.key)} title={o.long}>{o.short}</button>)}
      </div>
      {rows.length === 0 ? <Empty>No changes of that kind.</Empty> : (
        <>
          <p className="mb-1 text-xs text-gray-500">{rows.length.toLocaleString("en-GB")} rows standing for {rows.reduce((a, r) => a + r.records, 0).toLocaleString("en-GB")} records. Losses and moves of prices come first, then of used cars, then the rest.</p>
          <DataTable rows={rows} columns={columns} rowKey={(r) => `${r.source}|${r.key}|${r.outcome}|${r.car ?? ""}|${r.today.join(",")}`} dense />
        </>
      )}
    </Card>
  );
}
