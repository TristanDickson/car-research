"use client";

import Link from "next/link";
import { useState } from "react";

import { Badge, Card, Empty } from "@/components/ui";
import { ageLabel } from "@/lib/freshness";
import type { CarDetails, FlagState, SnapshotCar, SnapshotSpec } from "@/lib/types";

const VERDICT_TONE: Record<string, "good" | "warn" | "bad" | "muted" | "info"> = {
  agrees: "good", "not listed": "muted", differs: "bad", "source lists it": "warn",
};

function Mark({ state }: { state: FlagState }) {
  if (state === "standard") return <span className="text-emerald-300">✓ standard</span>;
  if (state === "option") return <span className="text-amber-300">option</span>;
  return <span className="text-gray-600">not listed</span>;
}

/**
 * What the spec sources say this exact variant has, next to what was typed in
 * by hand. A disagreement is a question for the dealer, not an automatic edit.
 */
export function EquipmentCard({ car, specs, specCheck, flagLabels }: { car: SnapshotCar; specs: SnapshotSpec[]; specCheck?: CarDetails["spec_check"] | null; flagLabels: Record<string, string> }) {
  const [open, setOpen] = useState<string | null>(null);
  const specsHref = `/specs?make=${encodeURIComponent(car.make)}&model=${encodeURIComponent(car.model)}`;
  if (!specs.length) {
    return (
      <Card title="Equipment (scraped)">
        <Empty>
          No spec source maps to this exact variant yet. <Link href={specsHref} className="underline">See every {car.make} {car.model} variant on the Specs page.</Link>
        </Empty>
      </Card>
    );
  }
  const keys = Object.keys(flagLabels);
  return (
    <Card title="Equipment (scraped)">
      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm text-gray-400">
        <span>What the sources list for this variant, against the hand-entered brief fields.</span>
        <Link href={specsHref} className="underline">Compare every {car.model} variant →</Link>
      </div>
      {(specCheck?.rows?.length ?? 0) > 0 && (
        <table className="mb-4 w-full text-sm">
          <thead className="text-left text-xs uppercase text-gray-500">
            <tr><th className="py-1 pr-3">Brief field</th><th className="py-1 pr-3">Entered</th><th className="py-1 pr-3">Source</th><th className="py-1 pr-3">Source says</th><th className="py-1">Verdict</th></tr>
          </thead>
          <tbody>
            {specCheck!.rows.map((r, i) => (
              <tr key={i} className="border-t border-gray-800">
                <td className="py-1 pr-3">{r.label}</td>
                <td className="py-1 pr-3 text-gray-300">{r.hand ?? "—"}</td>
                <td className="py-1 pr-3 text-gray-400">{r.source === "carwow_specs" ? "Carwow" : r.source === "kia_specs" ? "Kia UK" : r.source}</td>
                <td className="py-1 pr-3"><Mark state={r.seen} /></td>
                <td className="py-1"><Badge tone={VERDICT_TONE[r.verdict] ?? "muted"}>{r.verdict}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        {specs.map((s) => (
          <div key={s.spec_key} className="rounded border border-gray-800 bg-gray-950/50 p-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div>
                <span className="font-medium text-gray-100">{s.variant}</span>
                <span className="ml-2 text-xs text-gray-500">{s.provider === "carwow_specs" ? "Carwow specifications" : "Kia UK specification"} · seen {ageLabel(s.last_seen_at)}</span>
              </div>
              <a href={s.source_url} target="_blank" rel="noreferrer" className="text-xs text-gray-400 underline">source</a>
            </div>
            <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-sm">
              {keys.filter((k) => s.flags?.[k]).map((k) => (
                <div key={k} className="contents">
                  <dt className="text-gray-400">{flagLabels[k]}</dt>
                  <dd><Mark state={s.flags[k]} /></dd>
                </div>
              ))}
            </dl>
            <button onClick={() => setOpen(open === s.spec_key ? null : s.spec_key)} className="mt-2 text-xs text-gray-400 underline">
              {open === s.spec_key ? "hide" : `all ${s.features.length} standard items${s.options.length ? ` and ${s.options.length} options` : ""}`}
            </button>
            {open === s.spec_key && (
              <div className="mt-2 text-xs text-gray-300">
                <ul className="columns-2 gap-4">
                  {s.features.map((it) => <li key={it}>{it}</li>)}
                </ul>
                {s.options.length > 0 && (
                  <p className="mt-2 text-amber-300">Options: {s.options.join(", ")}</p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}
