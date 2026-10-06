"use client";

import { Card, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { useRequirements } from "@/lib/hooks";
import type { RequirementRule } from "@/lib/types";

export default function RequirementsPage() {
  const { data, error } = useRequirements();
  if (error) return <ErrorNote error={error} />;
  if (data === undefined) return <Loading />;
  if (data === null) return <ErrorNote error={new Error("requirements missing from snapshot")} />;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Requirements"
        subtitle={<>As of {data.as_of}. Edit <code>data/seed/requirements.json</code> and re-run <code>make snapshot</code>.</>}
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <RuleCard title="Hard requirements" rules={data.hard} />
        <RuleCard title="Strong preferences" rules={data.preferences} />
        <RuleCard title="Wants" rules={data.wants} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <KV title="Quoting basis" obj={data.quoting_basis} />
        <KV title="Budget" obj={data.budget} />
        <KV title="Finance posture" obj={data.finance_posture} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <KV title="Household" obj={data.household} />
        <KV title="Context" obj={data.context} />
      </div>
    </div>
  );
}

function RuleCard({ title, rules }: { title: string; rules: RequirementRule[] }) {
  return (
    <Card title={title}>
      <ul className="space-y-2 text-sm">
        {rules.map((r) => (
          <li key={r.id} className="flex items-start justify-between gap-3">
            <span className="text-gray-200">{r.label}</span>
            <span className="whitespace-nowrap text-xs text-gray-500">
              {r.weight != null ? `w${r.weight}` : ""}
              {r.field ? ` · ${r.field}${r.op ? ` ${r.op} ${JSON.stringify(r.value)}` : ""}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function KV({ title, obj }: { title: string; obj?: Record<string, unknown> }) {
  if (!obj) return null;
  return (
    <Card title={title}>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        {Object.entries(obj).map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-gray-500">{k.replaceAll("_", " ")}</dt>
            <dd className="text-right text-gray-200">{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}
