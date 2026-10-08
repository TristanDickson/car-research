"use client";

import { useState } from "react";

import { Badge, Card, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { useRequirements, useResetRequirements, useSaveRequirements, useSeedRequirements } from "@/lib/hooks";
import { basisOf } from "@/lib/model/dealMath";
import type { RequirementRule, Requirements } from "@/lib/types";

/** Car fields a rule can test, with the kind of value they take. */
const FIELDS: { key: string; label: string; kind: "tri" | "number" | "text" }[] = [
  { key: "heat_pump", label: "Heat pump", kind: "tri" },
  { key: "internal_v2l", label: "Internal V2L (cabin socket)", kind: "tri" },
  { key: "external_v2l", label: "External V2L", kind: "tri" },
  { key: "seats", label: "Seats", kind: "number" },
  { key: "wltp_range_mi", label: "WLTP range (mi)", kind: "number" },
  { key: "battery_kwh", label: "Battery (kWh)", kind: "number" },
  { key: "dc_peak_kw", label: "DC peak charge (kW)", kind: "number" },
  { key: "dc_avg_kw", label: "DC 10–80% average charge (kW)", kind: "number" },
  { key: "efficiency_mi_kwh", label: "Efficiency (mi/kWh)", kind: "number" },
  { key: "dc_10_80_min", label: "10–80% (min)", kind: "number" },
  { key: "width_mm", label: "Width (mm)", kind: "number" },
  { key: "length_mm", label: "Length (mm)", kind: "number" },
  { key: "boot_l", label: "Boot (L)", kind: "number" },
  { key: "power_hp", label: "Power (hp)", kind: "number" },
  { key: "list_price_gbp", label: "List price (£)", kind: "number" },
  { key: "model_year", label: "Model year", kind: "number" },
  { key: "fuel", label: "Fuel", kind: "text" },
  { key: "body", label: "Body", kind: "text" },
];
const TRI = ["standard", "pack", "option", "none"];
const OPS: Record<"tri" | "number" | "text", string[]> = { tri: ["in", "not in"], number: [">=", "<=", "==", ">", "<"], text: ["==", "!=", "in"] };

const fieldKind = (key: string | undefined) => FIELDS.find((f) => f.key === key)?.kind ?? "text";

/**
 * The reader's brief, kept in this browser (IndexedDB settings): seeded once
 * from data/seed/requirements.json, edited here, and only ever overwritten by
 * the reset button. The quoting basis (term, savings rate, residual assumption,
 * how deals of other lengths rank) is the reader's too: every figure on every
 * page is recomputed from the exported facts when it changes.
 */
export default function RequirementsPage() {
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

  const edited = seed.data ? JSON.stringify(seed.data) !== JSON.stringify(doc) : false;
  const update = (patch: Partial<Requirements>) => {
    const next = { ...doc, ...patch };
    setDraft({ base: stored, doc: next });
    save.mutate(next);
  };
  const budget = (doc.budget ?? {}) as Record<string, unknown>;
  const setBudget = (k: string, v: unknown) => update({ budget: { ...budget, [k]: v } });
  const qb = (doc.quoting_basis ?? {}) as Record<string, unknown>;
  const basis = basisOf(qb);
  const setBasis = (k: string, v: unknown) => update({ quoting_basis: { ...qb, [k]: v } });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Requirements"
        subtitle={
          <>
            Your brief, kept in this browser and applied everywhere a car is judged or costed. {edited ? <Badge tone="warn">edited from the seed</Badge> : <Badge tone="muted">as seeded</Badge>}
            {save.isPending && <span className="ml-2 text-xs text-gray-500">saving and recomputing every figure…</span>}
          </>
        }
        right={
          <button
            onClick={() => { if (confirm("Replace your brief with the seed from data/seed/requirements.json?")) reset.mutate(); }}
            className="rounded border border-gray-700 px-3 py-1 text-sm hover:bg-gray-800"
          >
            Reset to seed
          </button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Budget">
          <div className="space-y-2 text-sm">
            <NumberField label="Monthly ceiling (£)" value={budget.monthly_ceiling_gbp as number | undefined} onChange={(v) => setBudget("monthly_ceiling_gbp", v)} />
            <NumberField label="Tolerance (£/month)" value={budget.monthly_tolerance_gbp as number | undefined} onChange={(v) => setBudget("monthly_tolerance_gbp", v)} />
            <label className="flex items-center justify-between gap-3">
              <span className="text-gray-300">Buying outright is an option</span>
              <input type="checkbox" checked={!!budget.cash_purchase_ok} onChange={(e) => setBudget("cash_purchase_ok", e.target.checked)} />
            </label>
            <p className="text-xs text-gray-500">The ceiling draws the budget line on every card. Owners and notes from the seed are kept as they are.</p>
          </div>
        </Card>

        <div className="lg:col-span-2">
          <RulesCard
            title="Hard requirements"
            hint="A car passes when every switched-on rule holds. A car that carries no value for a rule is 'not confirmed', never a fail."
            rules={doc.hard}
            onChange={(hard) => update({ hard })}
            withValues
          />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <RulesCard title="Strong preferences" hint="Weighted, for ranking later; switch off what no longer matters." rules={doc.preferences} onChange={(preferences) => update({ preferences })} />
        <RulesCard title="Wants" hint="Nice to have." rules={doc.wants} onChange={(wants) => update({ wants })} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Quoting basis · how every figure is computed">
          <div className="space-y-2 text-sm">
            <NumberField label="Term (months)" value={basis.term_months} onChange={(v) => setBasis("term_months", v ?? 37)} />
            <NumberField label="Savings rate (% a year)" value={Math.round(basis.savings_rate_apr * 10000) / 100} step={0.25} onChange={(v) => setBasis("savings_rate_apr", (v ?? 0) / 100)} />
            <NumberField label="Residual assumption (% of list)" value={Math.round(basis.residual_pct_of_list * 1000) / 10} step={1} onChange={(v) => setBasis("residual_pct_of_list", (v ?? 45) / 100)} />
            <NumberField label="… at (months)" value={basis.residual_at_months} onChange={(v) => setBasis("residual_at_months", v ?? 36)} />
            <NumberField label="Annual mileage" value={typeof qb.annual_mileage === "number" ? qb.annual_mileage : undefined} step={1000} onChange={(v) => setBasis("annual_mileage", v)} />
            <label className="flex items-center justify-between gap-3">
              <span className="text-gray-300">Rank deals of other lengths</span>
              <select value={basis.compare_over} onChange={(e) => setBasis("compare_over", e.target.value)} className="rounded border border-gray-700 bg-gray-950 px-2 py-1 text-gray-100">
                <option value="horizon">over my term ({basis.term_months} months)</option>
                <option value="own">each over its own term</option>
              </select>
            </label>
            <p className="text-xs text-gray-500">
              Every payment is discounted at the savings rate (money not spent on a car earns this) and the car&apos;s expected value at the end is credited back: what the used market asks for the model at that age where there are enough examples, else the lender&apos;s GFV grown at the rate, else this share of list.
              Over your term, a longer PCP is settled early and the car sold; a shorter one pays its balloon and keeps the car to the end; a lease of another length keeps its own-term figure and says so.
            </p>
          </div>
        </Card>
        <Card title="Household"><KV obj={doc.household} /></Card>
        <Card title="Context"><KV obj={doc.context} /><KV obj={doc.finance_posture} /></Card>
      </div>
    </div>
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

function RulesCard({ title, hint, rules, onChange, withValues = false }: {
  title: string; hint: string; rules: RequirementRule[]; onChange: (rules: RequirementRule[]) => void; withValues?: boolean;
}) {
  const setRule = (i: number, patch: Partial<RequirementRule>) => onChange(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const remove = (i: number) => onChange(rules.filter((_, j) => j !== i));
  const add = () => onChange([...rules, { id: `rule-${Date.now().toString(36)}`, label: "New rule", field: "seats", op: ">=", value: 4, enabled: true }]);
  return (
    <Card title={title}>
      <p className="mb-2 text-xs text-gray-500">{hint}</p>
      <ul className="space-y-2 text-sm">
        {rules.map((r, i) => {
          const kind = fieldKind(r.field);
          const deal = r.applies_to === "deal";
          return (
            <li key={r.id} className={`rounded border border-gray-800 p-2 ${r.enabled === false ? "opacity-50" : ""}`}>
              <div className="flex flex-wrap items-center gap-2">
                <input type="checkbox" checked={r.enabled !== false} onChange={(e) => setRule(i, { enabled: e.target.checked })} title="Switched on" />
                <input value={r.label} onChange={(e) => setRule(i, { label: e.target.value })} className="min-w-[14rem] flex-1 rounded border border-gray-800 bg-gray-950 px-2 py-0.5 text-gray-100" />
                {r.weight != null && (
                  <label className="flex items-center gap-1 text-xs text-gray-400">w
                    <input type="number" value={r.weight} onChange={(e) => setRule(i, { weight: Number(e.target.value) })} className="w-14 rounded border border-gray-800 bg-gray-950 px-1 py-0.5 text-right text-gray-100" />
                  </label>
                )}
                <button onClick={() => remove(i)} className="text-xs text-gray-500 hover:text-rose-300" title="Delete this rule">remove</button>
              </div>
              {withValues && !deal && (
                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
                  <select value={r.field ?? ""} onChange={(e) => {
                    const k = fieldKind(e.target.value);
                    setRule(i, { field: e.target.value, op: OPS[k][0], value: k === "tri" ? ["standard", "pack", "option"] : k === "number" ? 0 : "" });
                  }} className="rounded border border-gray-800 bg-gray-950 px-1 py-0.5 text-gray-100">
                    <option value="">(no field: not checked)</option>
                    {FIELDS.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
                  </select>
                  {r.field && (
                    <select value={r.op ?? OPS[kind][0]} onChange={(e) => setRule(i, { op: e.target.value })} className="rounded border border-gray-800 bg-gray-950 px-1 py-0.5 text-gray-100">
                      {OPS[kind].map((o) => <option key={o} value={o}>{o}</option>)}
                    </select>
                  )}
                  {r.field && kind === "tri" && (
                    <span className="flex flex-wrap gap-2">
                      {TRI.map((t) => (
                        <label key={t} className="flex items-center gap-1 text-gray-300">
                          <input type="checkbox" checked={Array.isArray(r.value) && (r.value as string[]).includes(t)}
                            onChange={(e) => {
                              const cur = Array.isArray(r.value) ? (r.value as string[]) : [];
                              setRule(i, { value: e.target.checked ? [...cur, t] : cur.filter((x) => x !== t) });
                            }} /> {t}
                        </label>
                      ))}
                    </span>
                  )}
                  {r.field && kind === "number" && (
                    <input type="number" value={typeof r.value === "number" ? r.value : ""} onChange={(e) => setRule(i, { value: Number(e.target.value) })} className="w-24 rounded border border-gray-800 bg-gray-950 px-1 py-0.5 text-right text-gray-100" />
                  )}
                  {r.field && kind === "text" && (
                    <input value={Array.isArray(r.value) ? (r.value as string[]).join(", ") : String(r.value ?? "")} onChange={(e) => setRule(i, { value: r.op === "in" ? e.target.value.split(",").map((x) => x.trim()).filter(Boolean) : e.target.value })} className="w-40 rounded border border-gray-800 bg-gray-950 px-1 py-0.5 text-gray-100" />
                  )}
                </div>
              )}
              {deal && <div className="mt-1 text-xs text-gray-500">Applies to the deal, not the car: {r.field ?? ""} {r.op ?? ""} {JSON.stringify(r.value)}</div>}
            </li>
          );
        })}
      </ul>
      <button onClick={add} className="mt-2 text-xs text-gray-400 underline hover:text-gray-100">add a rule</button>
    </Card>
  );
}

function KV({ obj }: { obj?: Record<string, unknown> }) {
  if (!obj) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
      {Object.entries(obj).map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-gray-500">{k.replaceAll("_", " ")}</dt>
          <dd className={`text-right text-gray-200 ${typeof v === "string" && v.length > 40 ? "text-xs text-gray-400" : ""}`}>{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}
