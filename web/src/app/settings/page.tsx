"use client";

import Link from "next/link";
import { useState } from "react";

import { Badge, Card, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { useDataPage, useDeleteSearch, useRenameSearch, useRequirements, useResetRequirements, useResetSearches, useSaveRequirements, useSearches, useSeedRequirements, useSetDefaultSearch } from "@/lib/hooks";
import { basisOf } from "@/lib/model/dealMath";
import { describeQuery, parseQuery } from "@/lib/query";
import type { Requirements } from "@/lib/types";

/**
 * What the reader keeps in this browser: the saved searches (made from the search
 * bar; the default is what Pick, Cars and Specs open on), the budget line drawn on
 * every card, and the quoting basis every figure is computed under. Seeded once from
 * data/seed/requirements.json and only ever overwritten by a reset.
 */
export default function SettingsPage() {
  const own = useRequirements();
  const seed = useSeedRequirements();
  const save = useSaveRequirements();
  const reset = useResetRequirements();
  // The reader's edits, layered over the stored copy until the save lands; the stored copy wins once it changes.
  const [draft, setDraft] = useState<{ base: Requirements | null; doc: Requirements } | null>(null);
  const stored = own.data ?? null;
  const doc = draft && draft.base === stored ? draft.doc : stored;

  if (own.error) return <ErrorNote error={own.error} />;
  if (!doc) return <Loading />;

  const update = (patch: Partial<Requirements>) => {
    const next = { ...doc, ...patch };
    setDraft({ base: stored, doc: next });
    save.mutate(next);
  };
  const seeded = seed.data;
  const edited = seeded ? JSON.stringify(seeded.quoting_basis) !== JSON.stringify(doc.quoting_basis) || JSON.stringify(seeded.budget) !== JSON.stringify(doc.budget) : false;
  const budget = (doc.budget ?? {}) as Record<string, unknown>;
  const qb = (doc.quoting_basis ?? {}) as Record<string, unknown>;
  const basis = basisOf(qb);
  const setBasis = (k: string, v: unknown) => update({ quoting_basis: { ...qb, [k]: v } });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        subtitle={
          <>
            Kept in this browser. {save.isPending && <span className="text-xs text-gray-500">Saving and recomputing every figure…</span>}
          </>
        }
      />

      <SavedSearches />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Budget line">
          <div className="space-y-2 text-sm">
            <NumberField label="Monthly ceiling (£)" value={budget.monthly_ceiling_gbp as number | undefined} onChange={(v) => update({ budget: { ...budget, monthly_ceiling_gbp: v } })} />
            <p className="text-xs text-gray-500">Drawn on every card: within budget, or how far over.</p>
          </div>
        </Card>

        <div className="lg:col-span-2">
          <Card title="Quoting basis · how every figure is computed">
            <div className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
              <NumberField label="Term (months)" value={basis.term_months} onChange={(v) => setBasis("term_months", v ?? 37)} />
              <NumberField label="Savings rate (% a year)" value={Math.round(basis.savings_rate_apr * 10000) / 100} step={0.25} onChange={(v) => setBasis("savings_rate_apr", (v ?? 0) / 100)} />
              <NumberField label="Residual assumption (% of list)" value={Math.round(basis.residual_pct_of_list * 1000) / 10} step={1} onChange={(v) => setBasis("residual_pct_of_list", (v ?? 45) / 100)} />
              <NumberField label="… at (months)" value={basis.residual_at_months} onChange={(v) => setBasis("residual_at_months", v ?? 36)} />
              <label className="flex items-center justify-between gap-3 sm:col-span-2">
                <span className="text-gray-300">Rank deals of other lengths</span>
                <select value={basis.compare_over} onChange={(e) => setBasis("compare_over", e.target.value)} className="rounded border border-gray-700 bg-gray-950 px-2 py-1 text-gray-100">
                  <option value="horizon">over my term ({basis.term_months} months)</option>
                  <option value="own">each over its own term</option>
                </select>
              </label>
            </div>
            <p className="mt-3 text-xs text-gray-500">
              Every payment is discounted at the savings rate (money not spent on a car earns this) and the car&apos;s expected value at the end is credited back: what the used market asks for the model at that age where there are enough examples, else the lender&apos;s GFV grown at the rate, else this share of list.
              Over your term, a longer PCP is settled early and the car sold; a shorter one pays its balloon and keeps the car to the end.
            </p>
          </Card>
        </div>
      </div>

      {edited && (
        <p className="text-sm text-gray-400">
          <Badge tone="warn">changed from the seed</Badge>{" "}
          <button onClick={() => { if (confirm("Put the budget line and the quoting basis back to the seed (data/seed/requirements.json)?")) reset.mutate(); }} className="underline hover:text-gray-100">
            put the budget and basis back to the seed
          </button>
        </p>
      )}
    </div>
  );
}

function SavedSearches() {
  const searches = useSearches();
  const data = useDataPage();
  const rename = useRenameSearch();
  const remove = useDeleteSearch();
  const setDefault = useSetDefaultSearch();
  const reset = useResetSearches();
  const flagLabels = data.data?.flag_labels ?? {};
  const list = searches.data?.searches ?? [];

  return (
    <Card title="Saved searches">
      <p className="mb-3 text-xs text-gray-500">
        Save a search from the search bar on Pick, Cars or Specs. The default one is what those pages open on; after that a search follows you between them until you change it.
      </p>
      {searches.error ? <ErrorNote error={searches.error} /> : list.length === 0 ? (
        <p className="text-sm text-gray-400">None yet.</p>
      ) : (
        <ul className="divide-y divide-gray-800 text-sm">
          {list.map((x) => (
            <li key={x.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
              <label className="flex items-center gap-1.5 text-xs text-gray-400" title="Open on this search">
                <input type="radio" name="default-search" checked={x.id === searches.data?.default_id} onChange={() => setDefault.mutate(x.id)} /> default
              </label>
              <input
                key={x.name}
                defaultValue={x.name}
                aria-label="Name"
                onBlur={(e) => { if (e.target.value.trim() && e.target.value.trim() !== x.name) rename.mutate({ id: x.id, name: e.target.value }); }}
                onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                className="w-44 rounded border border-gray-800 bg-gray-950 px-2 py-0.5 text-gray-100"
              />
              <span className="min-w-0 flex-1 text-xs text-gray-400">{describeQuery(parseQuery(new URLSearchParams(x.query)), flagLabels)}</span>
              <Link href={x.query ? `/?${x.query}` : "/"} className="text-xs text-gray-300 underline hover:text-gray-100">open</Link>
              <button onClick={() => { if (confirm(`Delete the saved search “${x.name}”?`)) remove.mutate(x.id); }} className="text-xs text-gray-500 hover:text-rose-300">delete</button>
            </li>
          ))}
        </ul>
      )}
      <button onClick={() => { if (confirm("Replace your saved searches with the seeded ones?")) reset.mutate(); }} className="mt-3 text-xs text-gray-500 underline hover:text-gray-200">
        back to the seeded searches
      </button>
    </Card>
  );
}

function NumberField({ label, value, step, onChange }: { label: string; value: number | undefined; step?: number; onChange: (v: number | undefined) => void }) {
  return (
    <label className="flex items-center justify-between gap-3">
      <span className="text-gray-300">{label}</span>
      <input
        type="number"
        step={step}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
        className="w-28 rounded border border-gray-700 bg-gray-950 px-2 py-1 text-right tabular-nums text-gray-100"
      />
    </label>
  );
}
