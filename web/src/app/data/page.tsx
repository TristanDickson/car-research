"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { LevelsTable, NightsGrid } from "@/components/PipelineView";
import { Badge, Card, Empty, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { doesNotAddUp } from "@/lib/explain";
import { carName, dateLabel, gbp } from "@/lib/format";
import { pct } from "@/lib/format";
import { useBasis, useCars, useComputeStats, useDataPage, useModels, useOffers, useSnapshot } from "@/lib/hooks";

/**
 * Where the numbers come from and what is wrong with them. Leads with the
 * sources and their latest runs, what each level of the pipeline holds per source
 * and what each stage did night by night, then the issues a reader can act on (broker
 * rows that matched no derivative, twins the rules refused to guess between),
 * each Carwow model's Parkers model and generations for the owner to review,
 * then the catalogue coverage; the assumptions and the raw counts close the
 * page. Every sighting ever observed is one click away.
 */
export default function DataPage() {
  const snap = useSnapshot();
  const models = useModels();
  const basis = useBasis();
  const computed = useComputeStats();
  const { data, error } = useDataPage();
  const offers = useOffers();
  const cars = useCars();
  const [issueFilter, setIssueFilter] = useState<"all" | "conflict" | "unmapped">("all");
  // PCP quotes whose own figures disagree (lib/model/dealMath.ts, pcpAddsUp), newest first.
  const unsound = useMemo(() => (offers.data ?? []).filter((o) => o.finance_type === "pcp" && o.metrics.adds_up === false)
    .sort((a, b) => (b.freshness.last_seen_at ?? "").localeCompare(a.freshness.last_seen_at ?? "")), [offers.data]);
  const carById = useMemo(() => new Map((cars.data ?? []).map((c) => [c.id, c])), [cars.data]);

  // Each source's latest scrape: from the night history where the snapshot has one, else the run log's last rows.
  const lastRun = useMemo(() => {
    const out = new Map<string, { finished_at: string | null; status: string; errors?: number; artifacts: number; records: number }>();
    for (const n of data?.pipeline?.nights ?? []) {
      for (const s of n.scrapes) {
        if (!out.has(s.source) && s.status) out.set(s.source, { finished_at: s.finished_at, status: s.status, errors: s.errors, artifacts: s.fetches, records: s.records });
      }
    }
    for (const r of data?.runs ?? []) if (!out.has(r.source)) out.set(r.source, r);
    return out;
  }, [data]);

  if (error) return <ErrorNote error={error} />;
  if (data === undefined) return <Loading />;
  if (data === null) return <ErrorNote error={new Error("data.json missing from snapshot")} />;

  const issues = data.unmapped_trims.filter((t) => issueFilter === "all" || (t.status ?? "unmapped") === issueFilter);
  const conflicts = data.unmapped_trims.filter((t) => t.status === "conflict").length;
  const counts = data.counts;
  // Unplaced and ambiguous models first, most cars on sale first; then the placed ones by name.
  const order = { unplaced: 0, ambiguous: 1, placed: 2 } as const;
  const mapRows = [...(data.model_map ?? [])].sort((a, b) => order[a.status] - order[b.status]
    || (a.status === "placed" ? 0 : b.cars_on_sale - a.cars_on_sale) || a.slug.localeCompare(b.slug));
  const mapCount = (s: keyof typeof order) => mapRows.filter((r) => r.status === s).length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Data"
        subtitle={
          <>
            Snapshot generated {dateLabel(snap.data?.generated_at)}. Every price is a sighting: a source is re-read nightly, the sighting is
            recorded, and an offer not seen for {data.stale_days} days goes stale. <Link href="/offers" className="underline">Every sighting as a table</Link>.
          </>
        }
      />

      <Card title="Sources">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-gray-500">
            <tr><th className="py-1 pr-3">Source</th><th className="py-1 pr-3">What it gives</th><th className="py-1 pr-3">Last run</th><th className="py-1 pr-3">Status</th><th className="py-1 pr-3 text-right">Pages</th><th className="py-1 text-right">Records</th></tr>
          </thead>
          <tbody>
            {data.providers.map((p) => {
              const r = lastRun.get(p.name);
              return (
                <tr key={p.name} className="border-t border-gray-800 align-top">
                  <td className="py-1 pr-3">
                    <div className="font-medium text-gray-100">{p.name}</div>
                    <div className="text-xs text-gray-500">{p.live ? "scrapes the web" : "offline"} · {p.capabilities.map((c) => c.kinds.join("/")).join(", ")}</div>
                  </td>
                  <td className="py-1 pr-3 text-gray-300">{p.description}</td>
                  <td className="py-1 pr-3 whitespace-nowrap text-gray-400">{r ? dateLabel(r.finished_at) : "—"}</td>
                  <td className="py-1 pr-3">{r ? <Badge tone={r.status === "ok" ? "good" : "bad"}>{r.status}{r.errors ? ` · ${r.errors} failed` : ""}</Badge> : <Badge tone="muted">no run in this snapshot</Badge>}</td>
                  <td className="py-1 pr-3 text-right tabular-nums">{r?.artifacts ?? "—"}</td>
                  <td className="py-1 text-right tabular-nums">{r?.records ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>

      <Card title="What each level holds, per source">
        <p className="mb-2 text-xs text-gray-500">
          Each source&apos;s pages go into the raw store (kept for good), the build reads records from every page held, matches them to cars, and writes what the app shows. A source that describes models (a spec table, EV Database) is laid over the cars by model and battery instead of naming one.
        </p>
        <LevelsTable levels={data.pipeline?.levels ?? []} />
      </Card>

      <Card title="Night by night: scrape, build, publish">
        <NightsGrid nights={data.pipeline?.nights ?? []} />
      </Card>

      <Card title={`Issues · ${data.unmapped_trims.length} broker rows with no car (${conflicts} conflicts)`}>
        <p className="mb-2 text-sm text-gray-400">
          A broker&apos;s derivative text resolves to one generated car by trim and powertrain, and among same-trim twins by the broker&apos;s own RRP, a pack in the name, or the cheapest.
          <span className="text-gray-300"> Conflicts</span> are twins the rules refuse to guess between (no RRP, no pack named, three or more prices); <span className="text-gray-300">unmapped</span> rows match no derivative at all.
          Resolution methods so far: {Object.entries(data.resolution_methods ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ")}.
        </p>
        <div className="mb-2 flex gap-1 text-xs">
          {(["all", "conflict", "unmapped"] as const).map((k) => (
            <button key={k} onClick={() => setIssueFilter(k)} className={`rounded border px-2 py-0.5 ${issueFilter === k ? "border-gray-500 bg-gray-700 text-gray-100" : "border-gray-700 text-gray-400"}`}>{k}</button>
          ))}
        </div>
        {issues.length === 0 ? (
          <Empty>Nothing here: every scraped trim resolves to a car.</Empty>
        ) : (
          <div className="max-h-[28rem] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-gray-900 text-left text-xs uppercase text-gray-500"><tr><th className="py-1 pr-3">Source</th><th className="py-1 pr-3">As printed</th><th className="py-1 pr-3">Why</th><th className="py-1">First seen</th></tr></thead>
              <tbody>
                {issues.map((t) => {
                  const words = (t.label ?? "").split(/[·\s]+/).filter((w) => /^[A-Za-z]{3,}$/.test(w)).slice(0, 2).join(" ");
                  return (
                    <tr key={`${t.source}|${t.source_key}`} className="border-t border-gray-800 align-top">
                      <td className="py-1 pr-3">{t.source}</td>
                      <td className="py-1 pr-3">
                        <div>{t.label ?? "—"}</div>
                        <div className="font-mono text-xs text-gray-600">{t.source_key}</div>
                        {words && <Link href={`/cars?q=${encodeURIComponent(words)}`} className="text-xs text-gray-400 underline">find the derivatives</Link>}
                      </td>
                      <td className="py-1 pr-3 text-xs text-gray-400">
                        <Badge tone={t.status === "conflict" ? "warn" : "muted"}>{t.status ?? "unmapped"}</Badge>
                        {t.evidence?.reason ? <div className="mt-0.5">{String(t.evidence.reason)}</div> : null}
                        {Array.isArray(t.evidence?.prices) && t.evidence.prices.length > 0 ? (
                          <div className="text-gray-600">twins at {(t.evidence.prices as number[]).map((p) => `£${p.toLocaleString("en-GB")}`).join(", ")}</div>
                        ) : null}
                      </td>
                      <td className="py-1 whitespace-nowrap">{t.first_seen_at.slice(0, 10)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title={`Carwow's models on Parkers' · ${mapCount("placed")} placed, ${mapCount("ambiguous")} ambiguous, ${mapCount("unplaced")} unplaced`}>
        <p className="mb-2 text-sm text-gray-400">
          Parkers lists every derivative of every generation, and files body styles as generations of one model (the Q4 Sportback e-tron is its Q4 e-tron&apos;s Sportback generation).
          Each Carwow model is placed on the Parkers model of the same make whose name reads alike and whose derivatives share the most names with Carwow&apos;s list of the model;
          failing a name that reads alike, on the one Parkers model holding most of Carwow&apos;s derivative names. Its generations are those whose body its name prints (Sportback, Touring, N),
          else those no other Carwow model names. Nothing here matches a price to a car yet: the coming resolver will read it.
          <span className="text-gray-300"> Ambiguous</span> models fit more than one Parkers model or generation; <span className="text-gray-300">unplaced</span> ones fit none.
        </p>
        {mapRows.length === 0 ? (
          <Empty>No Parkers mapping in this snapshot yet.</Empty>
        ) : (
          <div className="max-h-[32rem] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-gray-900 text-left text-xs uppercase text-gray-500"><tr><th className="py-1 pr-3">Carwow model</th><th className="py-1 pr-3 text-right">On sale</th><th className="py-1 pr-3">Parkers model</th><th className="py-1 pr-3">Generations</th><th className="py-1">How, or why not</th></tr></thead>
              <tbody>
                {mapRows.map((r) => (
                  <tr key={r.slug} className="border-t border-gray-800 align-top">
                    <td className="py-1 pr-3">
                      <div>{r.make_name ?? r.make} {r.model_name ?? r.model}</div>
                      <div className="font-mono text-xs text-gray-600">{r.slug}</div>
                    </td>
                    <td className="py-1 pr-3 text-right tabular-nums">{r.cars_on_sale}</td>
                    <td className="py-1 pr-3">
                      {r.parkers ?? (r.candidates?.length ? <span className="text-gray-400">{r.candidates.map((c) => c.parkers).join(" or ")}</span> : "—")}
                    </td>
                    <td className="py-1 pr-3 text-xs text-gray-300">
                      {r.generations.map((g) => (
                        <div key={g.generation}>
                          {g.label} {g.start ?? ""}
                          <span className="text-gray-500"> · {g.since ?? "?"} to {g.until ?? "now"} · {g.derivatives} derivatives{g.shared ? `, ${g.shared} named alike on Carwow` : ""}</span>
                        </div>
                      ))}
                    </td>
                    <td className="py-1 text-xs text-gray-400">
                      <Badge tone={r.status === "placed" ? (r.rule === "name and derivatives" ? "good" : "muted") : r.status === "ambiguous" ? "warn" : "bad"}>{r.status === "placed" ? `by ${r.rule}` : r.status}</Badge>
                      {r.why ? <div className="mt-0.5">{r.why}</div> : null}
                      <div className="text-gray-600">{r.registry} derivatives on Carwow&apos;s list</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title={`Quotes that don't add up · ${unsound.length}`}>
        <p className="mb-2 text-sm text-gray-400">
          A PCP quote whose printed monthly is not what its own amount borrowed, APR and final payment give (allowing for the APR printed to one decimal and a pound or so of the seller&apos;s rounding),
          or whose price less the deposit is not what it lends. It stays in the offer lists, marked, and is left out of every cheapest price.
        </p>
        {unsound.length === 0 ? (
          <Empty>Every PCP quote&apos;s figures agree with each other.</Empty>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-gray-500"><tr><th className="py-1 pr-3">Car</th><th className="py-1 pr-3">Seller</th><th className="py-1 pr-3 text-right">Printed</th><th className="py-1 pr-3 text-right">Its figures give</th><th className="py-1 pr-3">Why</th><th className="py-1">Last seen</th></tr></thead>
            <tbody>
              {unsound.map((o) => {
                const c = carById.get(o.car_id);
                return (
                  <tr key={o.id} className="border-t border-gray-800 align-top">
                    <td className="py-1 pr-3"><Link href={`/cars/view?id=${encodeURIComponent(o.car_id)}`} className="text-gray-100 hover:underline">{c ? carName(c) : o.car_id}</Link></td>
                    <td className="py-1 pr-3 text-gray-300">{o.source_url ? <a href={o.source_url} target="_blank" rel="noreferrer" className="hover:underline">{o.dealer ?? o.source}</a> : (o.dealer ?? o.source)}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{gbp(o.metrics.monthly_payment, 2)}</td>
                    <td className="py-1 pr-3 text-right tabular-nums">{gbp(o.metrics.monthly_at_stated_apr, 2)}</td>
                    <td className="max-w-[28rem] whitespace-pre-line py-1 pr-3 text-xs text-gray-400">{doesNotAddUp(o)}</td>
                    <td className="whitespace-nowrap py-1 text-xs text-gray-400">{o.freshness.last_seen_at?.slice(0, 10) ?? "—"}{o.freshness.state === "gone" ? " · gone" : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>

      <Card title={`Catalogue · ${models.data?.length ?? 0} electric models on sale`}>
        <p className="mb-2 text-sm text-gray-400">
          Every model Carwow lists as electric. Derivatives is how many variants the specification page lists; cars how many car records exist (one per derivative); priced how many of those have a current figure on any route; used how many used examples are on sale.
        </p>
        {!models.data?.length ? (
          <Empty>No catalogue in this snapshot yet.</Empty>
        ) : (
          <div className="max-h-[32rem] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-gray-900 text-xs uppercase text-gray-500"><tr><th className="text-left">Model</th><th className="text-left">Deals</th><th className="text-left">Specs</th><th className="text-right">Derivatives</th><th className="text-right">Cars</th><th className="text-right">Priced</th><th className="text-right">Used</th><th className="text-left">Last seen</th></tr></thead>
              <tbody>
                {models.data.map((m) => {
                  const name = `${m.make_name ?? m.make} ${m.model_name ?? m.model}`;
                  return (
                    <tr key={m.slug} className="border-t border-gray-800">
                      <td className="py-1 pr-3">
                        {m.cars > 0 ? (
                          <Link href={`/cars?make=${encodeURIComponent(m.make_name ?? m.make)}&model=${encodeURIComponent(m.model_name ?? m.model)}`} className="hover:underline">{name}</Link>
                        ) : name}
                      </td>
                      <td className="py-1 pr-3">{m.has_deals ? "yes" : "—"}</td>
                      <td className="py-1 pr-3">{m.has_specs ? "yes" : "—"}</td>
                      <td className="py-1 text-right tabular-nums">{m.derivatives}</td>
                      <td className="py-1 text-right tabular-nums">{m.cars}</td>
                      <td className="py-1 text-right tabular-nums">{m.priced}</td>
                      <td className="py-1 text-right tabular-nums">{m.used ?? 0}</td>
                      <td className="py-1 pl-3 whitespace-nowrap text-gray-400">{m.last_seen_at.slice(0, 10)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>


      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Costed in this browser">
          <p className="mb-2 text-sm text-gray-400">
            The pipeline exports facts only: every price as a span of days it held, every used asking price, every car. This browser puts them on one footing under your
            basis (<Link href="/settings" className="underline">Settings</Link>) and stores the results; a change to the term or the rate recomputes everything.
          </p>
          {basis.data && (
            <ul className="space-y-1 text-sm">
              <li className="flex justify-between"><span>term</span><span className="tabular-nums">{basis.data.term_months} months</span></li>
              <li className="flex justify-between"><span>savings rate</span><span className="tabular-nums">{pct(basis.data.savings_rate_apr)}</span></li>
              <li className="flex justify-between"><span>residual assumption</span><span className="tabular-nums">{pct(basis.data.residual_pct_of_list, 0)} of list at {basis.data.residual_at_months} months</span></li>
              <li className="flex justify-between"><span>deals of other lengths</span><span>{basis.data.compare_over === "own" ? "each over its own term" : `every deal over ${basis.data.term_months} months`}</span></li>
            </ul>
          )}
          {computed.data && (
            <p className="mt-2 text-xs text-gray-500">
              Last computed {dateLabel(computed.data.computed_at)}: {computed.data.sightings.toLocaleString("en-GB")} sightings, {computed.data.costed.toLocaleString("en-GB")} costed, {computed.data.cars.toLocaleString("en-GB")} cars priced, {computed.data.series.toLocaleString("en-GB")} series, {computed.data.offers.toLocaleString("en-GB")} offers, in {computed.data.ms} ms (plus {computed.data.read_ms} ms reading the facts and {computed.data.write_ms} ms storing the results).
              The GFV a lender guarantees is the floor; the used market&apos;s own prices for the model at that age are the expectation where there are enough of them (three or more cars).
            </p>
          )}
        </Card>
        <Card title="In this snapshot">
          <p className="text-sm text-gray-400">
            {counts.cars} cars across {counts.models} models from {counts.makes} makes ·{" "}
            {counts.offers} offers from {counts.observations} sightings · {counts.used_spans ?? 0} used asking-price spans · {counts.specs} spec rows · {counts.derivatives ?? 0} registry derivatives · {counts.used_listings} used listings over {counts.used_models} models.
            {counts.claims != null && <> Every car field is resolved from {counts.claims.toLocaleString("en-GB")} claims: {counts.fields_from_claims?.toLocaleString("en-GB")} fields filled from a source, {counts.disagreements ?? 0} left unknown because the strongest sources disagree.</>}
            {counts.configurations != null && counts.configurations > 0 && <> The makers&apos; own configurators list {counts.configurations.toLocaleString("en-GB")} orderable configurations with prices and packages, {counts.configured ?? 0} of them matched to a CAP derivative.</>}
          </p>
          <p className="mt-2 text-xs text-gray-500">
            Offer states: {Object.entries(data.offer_states).map(([k, v]) => `${k} ${v}`).join(" · ")}.
          </p>
        </Card>
      </div>
    </div>
  );
}
