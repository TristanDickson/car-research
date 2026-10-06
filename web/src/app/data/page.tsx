"use client";

import Link from "next/link";

import { Badge, Card, Empty, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { dateLabel } from "@/lib/format";
import { useDataPage, useModels, useSnapshot } from "@/lib/hooks";

export default function DataPage() {
  const snap = useSnapshot();
  const models = useModels();
  const { data, error } = useDataPage();
  if (error) return <ErrorNote error={error} />;
  if (data === undefined) return <Loading />;
  if (data === null) return <ErrorNote error={new Error("data.json missing from snapshot")} />;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Data"
        subtitle={
          <>
            Where the numbers come from and how fresh they are. Snapshot generated {dateLabel(snap.data?.generated_at)}.
            Offers are observations: a source is re-read, the sighting is recorded, and anything not seen for {data.stale_days} days goes stale.
          </>
        }
      />
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {Object.entries(data.counts).map(([k, v]) => (
          <div key={k} className="rounded-lg border border-gray-800 bg-gray-900 p-4">
            <div className="text-xs uppercase tracking-wide text-gray-500">{k.replaceAll("_", " ")}</div>
            <div className="mt-1 text-2xl font-semibold tabular-nums">{v}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Offer states">
          <ul className="space-y-1 text-sm">
            {Object.entries(data.offer_states).map(([k, v]) => (
              <li key={k} className="flex justify-between"><span>{k}</span><span className="tabular-nums">{v}</span></li>
            ))}
          </ul>
        </Card>
        <Card title="Providers">
          <ul className="space-y-2 text-sm">
            {data.providers.map((p) => (
              <li key={p.name}>
                <span className="font-medium text-gray-100">{p.name}</span>
                <span className="ml-2"><Badge tone={p.live ? "good" : "muted"}>{p.live ? "scrapes the web" : "offline"}</Badge></span>
                {p.description && <div className="text-gray-400">{p.description}</div>}
                <div className="text-xs text-gray-500">
                  {p.capabilities.map((c) => `${c.name} → ${c.kinds.join(", ")} (parser v${c.parser_version})`).join("; ")}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card title={`Catalogue · ${models.data?.length ?? 0} electric models on sale (from Carwow's index)`}>
        <p className="mb-2 text-sm text-gray-400">
          Every model Carwow lists as electric. Deals and specs say whether Carwow has that page; derivatives is how many variants the
          specification page lists; cars is how many car records exist for it (hand-curated plus generated); priced is how many of those have a current offer.
        </p>
        {!models.data?.length ? (
          <Empty>No catalogue in this snapshot yet.</Empty>
        ) : (
          <div className="max-h-[32rem] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-gray-900 text-xs uppercase text-gray-500"><tr><th className="text-left">Model</th><th className="text-left">Deals</th><th className="text-left">Specs</th><th className="text-right">Derivatives</th><th className="text-right">Cars</th><th className="text-right">Priced</th><th className="text-left">Last seen</th></tr></thead>
              <tbody>
                {models.data.map((m) => {
                  const name = `${m.make_name ?? m.make} ${m.model_name ?? m.model}`;
                  return (
                    <tr key={m.slug} className="border-t border-gray-800">
                      <td className="py-1 pr-3">
                        {m.cars > 0 ? (
                          <Link href={`/cars?scope=all&make=${encodeURIComponent(m.make_name ?? m.make)}&model=${encodeURIComponent(m.model_name ?? m.model)}`} className="hover:underline">{name}</Link>
                        ) : name}
                      </td>
                      <td className="py-1 pr-3">{m.has_deals ? "yes" : "—"}</td>
                      <td className="py-1 pr-3">{m.has_specs ? "yes" : "—"}</td>
                      <td className="py-1 text-right tabular-nums">{m.derivatives}</td>
                      <td className="py-1 text-right tabular-nums">{m.cars}</td>
                      <td className="py-1 text-right tabular-nums">{m.priced}</td>
                      <td className="py-1 pl-3 whitespace-nowrap text-gray-400">{m.last_seen_at.slice(0, 10)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title={`Unmapped trims (${data.unmapped_trims.length})`}>
        {data.unmapped_trims.length === 0 ? (
          <Empty>Every scraped trim resolves to a car (hand-curated, or generated from the catalogue). Broker derivatives that match no car appear here until added to data/seed/trim_map.json.</Empty>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-xs uppercase text-gray-500"><tr><th className="text-left">Source</th><th className="text-left">Key</th><th className="text-left">As printed</th><th className="text-left">First seen</th></tr></thead>
            <tbody>
              {data.unmapped_trims.map((t) => (
                <tr key={`${t.source}|${t.source_key}`} className="border-t border-gray-800">
                  <td className="py-1 pr-3">{t.source}</td>
                  <td className="py-1 pr-3 font-mono text-xs">{t.source_key}</td>
                  <td className="py-1 pr-3">{t.label ?? "—"}</td>
                  <td className="py-1">{t.first_seen_at.slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="Recent runs">
        <table className="w-full text-sm">
          <thead className="text-xs uppercase text-gray-500">
            <tr><th className="text-left">Provider</th><th className="text-left">Capability</th><th className="text-left">Finished</th><th className="text-left">Status</th><th className="text-right">Artifacts</th><th className="text-right">Records</th><th className="text-right">Unmapped</th><th className="text-right">Failed targets</th></tr>
          </thead>
          <tbody>
            {data.runs.map((r) => (
              <tr key={r.id} className="border-t border-gray-800">
                <td className="py-1 pr-3">{r.source}</td>
                <td className="py-1 pr-3">{r.capability}</td>
                <td className="py-1 pr-3 whitespace-nowrap">{dateLabel(r.finished_at)}</td>
                <td className="py-1 pr-3"><Badge tone={r.status === "ok" ? "good" : "bad"}>{r.status}</Badge></td>
                <td className="py-1 text-right tabular-nums">{r.artifacts}</td>
                <td className="py-1 text-right tabular-nums">{r.records}</td>
                <td className="py-1 text-right tabular-nums">{r.unmapped}</td>
                <td className="py-1 text-right tabular-nums">{r.errors ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
