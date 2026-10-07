"use client";

import { useEffect, useState } from "react";

import { Badge, Card, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { useRequirements, useResetRequirements, useSaveRequirements, useSeedRequirements } from "@/lib/hooks";
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
 * the reset button. The quoting basis is a pipeline input, shown but not
 * editable here: every cost in the snapshot was computed with it.
 */
export default function RequirementsPage() {
  const own = useRequirements();
  const seed = useSeedRequirements();
  const save = useSaveRequirements();
  const reset = useResetRequirements();
  const [doc, setDoc] = useState<Requirements | null>(null);
  useEffect(() => { if (own.data) setDoc(own.data); }, [own.data]);

  if (own.error) return <ErrorNote error={own.error} />;
  if (!doc) return <Loading />;

  const edited = seed.data ? JSON.stringify(seed.data) !== JSON.stringify(doc) : false;
  const update = (patch: Partial<Requirements>) => {
    const next = { ...doc, ...patch };
    setDoc(next);
    save.mutate(next);
  };
  const budget = (doc.budget ?? {}) as Record<string, unknown>;
  const setBudget = (k: string, v: unknown) => update({ budget: { ...budget, [k]: v } });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Requirements"
        subtitle={
          <>
            Your brief, kept in this browser and applied everywhere a car is judged. {edited ? <Badge tone="warn">edited from the seed</Badge> : <Badge tone="muted">as seeded</Badge>}
            {save.isPending && <span className="ml-2 text-xs text-gray-500">saving…</span>}
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
        <Card title="Quoting basis · pipeline inputs">
          <p className="mb-2 text-xs text-gray-500">
            Every true monthly in the snapshot was computed with these (term, savings rate, residual assumption), so they cannot be changed here. Edit <code>data/seed/requirements.json</code> and let the nightly run recompute.
          </p>
          <KV obj={doc.quoting_basis} />
        </Card>
        <Card title="Household"><KV obj={doc.household} /></Card>
        <Card title="Context"><KV obj={doc.context} /><KV obj={doc.finance_posture} /></Card>
      </div>
    </div>
  );
}

function NumberField({ label, value, onChange }: { label: string; value: number | undefined; onChange: (v: number | undefined) => void }) {
  return (
    <label className="flex items-center justify-between gap-3">
      <span className="text-gray-300">{label}</span>
      <input
        type="number"
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
