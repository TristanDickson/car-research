"use client";

import { useState } from "react";

import { Badge, Empty } from "@/components/ui";
import { dateLabel, num } from "@/lib/format";
import type { PipelineBuild, PipelineLevel, PipelineNight, PipelineScrape } from "@/lib/types";

const REPO = "https://github.com/TristanDickson/car-research";

/** What a source's records are called, in plain words: [one, several]. */
const KIND: Record<string, [string, string]> = {
  offer: ["offer", "offers"], used: ["used car", "used cars"], spec: ["spec row", "spec rows"], model: ["model", "models"],
  derivative: ["derivative", "derivatives"], configuration: ["configuration", "configurations"], options: ["option page", "option pages"],
  car: ["car of yours", "cars of yours"], trim_map: ["decision of yours", "decisions of yours"], requirements: ["requirements file", "requirements files"],
};
const APP: Record<string, [string, string]> = { offers: ["offer", "offers"], used: ["used car on sale", "used cars on sale"], specs: ["spec row", "spec rows"] };

/** '1 offer', '2,056 offers'. */
function count(n: number, kind: string, names: Record<string, [string, string]> = KIND): string {
  const [one, many] = names[kind] ?? [kind, kind];
  return `${num(n)} ${n === 1 ? one : many}`;
}

const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

/**
 * One row per source, one column per level: what the raw store holds, the records read from it, how many
 * of those name a car, and what this snapshot carries.
 */
export function LevelsTable({ levels }: { levels: PipelineLevel[] }) {
  if (!levels.length) return <Empty>This snapshot was built before the levels were counted.</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs uppercase text-gray-500">
          <tr>
            <th className="py-1 pr-3">Source</th>
            <th className="py-1 pr-3 text-right" title="Pages fetched and kept in the raw store, all nights; a fetch that combines several pages counts once">Pages held</th>
            <th className="py-1 pr-3 text-right" title="Answers that were not a page: a 404, a refusal, an error">Failed</th>
            <th className="py-1 pr-3" title="When the raw store last fetched from it">Last fetched</th>
            <th className="py-1 pr-3 text-right" title="Distinct records read from every page held">Records</th>
            <th className="py-1 pr-3 text-right" title="Of the offers, used cars and spec rows, how many name a car">Name a car</th>
            <th className="py-1 text-right" title="What this snapshot, the app's data, carries from it">In the app</th>
          </tr>
        </thead>
        <tbody>
          {levels.map((lv) => {
            const kinds = Object.entries(lv.records ?? {});
            const matched = Object.values(lv.matched ?? {});
            const total = sum(matched.map((m) => m.total));
            const named = sum(matched.map((m) => m.matched));
            const conflicts = sum(matched.map((m) => m.conflict));
            const app = Object.entries(lv.in_snapshot ?? {}).filter(([, n]) => n);
            return (
              <tr key={lv.provider} className="border-t border-gray-800 align-top">
                <td className="py-1 pr-3 font-medium text-gray-100">{lv.provider}</td>
                <td className="py-1 pr-3 text-right tabular-nums" title={lv.raw ? `${num(lv.raw.responses)} responses kept, ${num(lv.raw.bodies)} distinct bodies${lv.raw.wayback ? `, ${num(lv.raw.wayback)} from the Wayback Machine` : ""}` : undefined}>
                  {lv.raw ? num(lv.raw.fetches) : <span className="text-gray-500">not fetched</span>}
                </td>
                <td className="py-1 pr-3 text-right tabular-nums">
                  {lv.raw?.failed ? <span className={lv.raw.refused ? "text-amber-300" : "text-gray-300"}>{num(lv.raw.failed)}{lv.raw.refused ? ` (${num(lv.raw.refused)} refused)` : ""}</span> : <span className="text-gray-600">0</span>}
                </td>
                <td className="py-1 pr-3 whitespace-nowrap text-gray-400">{lv.raw ? dateLabel(lv.raw.last_at) : "—"}</td>
                <td className="py-1 pr-3 text-right tabular-nums" title={kinds.map(([k, v]) => `${count(v.keys, k)}${v.first_seen_live < v.keys ? ` (${num(v.keys - v.first_seen_live)} from the committed history or your files)` : ""}`).join("; ")}>
                  {kinds.length ? kinds.map(([k, v]) => count(v.keys, k)).join(", ") : "—"}
                </td>
                <td className="py-1 pr-3 text-right tabular-nums" title={lv.describes_models ? "Describes models, trims or variants; laid over the cars by model and battery rather than naming one" : matched.length ? `${num(total - named)} name no car${conflicts ? `; ${num(conflicts)} of those are look-alike cars the rules would not guess between` : ""}` : undefined}>
                  {lv.describes_models ? <span className="text-gray-500">describes models</span> : total ? (
                    <span className={named < total ? "text-gray-200" : "text-gray-300"}>
                      {num(named)} of {num(total)}{conflicts ? <span className="text-amber-300"> · {num(conflicts)} unsure</span> : null}
                    </span>
                  ) : "—"}
                </td>
                <td className="py-1 text-right tabular-nums text-gray-300">
                  {app.length ? app.map(([k, n]) => count(n, k, APP)).join(", ") : <span className="text-gray-600">—</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** '2026-10-11' → '11–12 Oct': the evening and the morning a night label covers. */
function nightLabel(night: string): string {
  const d = new Date(`${night}T12:00:00Z`);
  const next = new Date(d.getTime() + 86400000);
  const day = (x: Date) => x.toLocaleDateString("en-GB", { day: "numeric", timeZone: "UTC" });
  const month = (x: Date) => x.toLocaleDateString("en-GB", { month: "short", timeZone: "UTC" });
  return month(d) === month(next) ? `${day(d)}–${day(next)} ${month(d)}` : `${day(d)} ${month(d)}–${day(next)} ${month(next)}`;
}

function rested(s: PipelineScrape): boolean {
  return !!s.allowance && Object.values(s.allowance).some(([allowed]) => allowed === 0);
}

function held(s: PipelineScrape): string | null {
  if (!s.allowance) return null;
  const parts = Object.entries(s.allowance).filter(([, [allowed, usual]]) => allowed < usual)
    .map(([host, [allowed, usual]]) => (allowed === 0 ? `${host} rested after refusals` : `${host}: ${num(allowed)} of its usual ${num(usual)} pages, coming back after refusals`));
  return parts.length ? parts.join("; ") : null;
}

function scrapeTone(s: PipelineScrape): string {
  if (s.errors > s.refused || (s.status === "error" && !s.refused)) return "bg-rose-950 text-rose-200";
  if (rested(s)) return "bg-gray-800 text-gray-400";
  if (s.refused || s.deferred || s.status === "refused" || held(s)) return "bg-amber-950 text-amber-200";
  return "bg-emerald-950/60 text-emerald-100";
}

function scrapeTitle(s: PipelineScrape): string {
  return [
    `${s.source} (${s.capabilities.join(", ") || "fetches only"}): ${s.status ?? "no run logged"}`,
    `${num(s.fetches)} pages asked for, ${num(s.responses)} responses kept`,
    s.failed ? `${num(s.failed)} failed${s.refused ? `, ${num(s.refused)} refused` : ""}` : null,
    s.deferred ? `${num(s.deferred)} put off to another night after two refusals` : null,
    s.skipped ? `${num(s.skipped)} guessed pages the site does not have` : null,
    held(s),
    `${num(s.records)} records read`,
    s.errors ? `${num(s.errors)} pages failed to fetch or parse` : null,
    s.started_at ? `${dateLabel(s.started_at)} to ${dateLabel(s.finished_at)}` : null,
  ].filter(Boolean).join("\n");
}

function buildTitle(b: PipelineBuild): string {
  return [
    `${b.this ? "This snapshot's build" : `Build (${b.mode})`}, ${dateLabel(b.started_at)}, ${num(b.seconds)} s${b.commit ? `, code ${b.commit}` : ""}`,
    `${num(b.fetches)} stored pages: ${num(b.parsed)} parsed, ${num(b.from_cache)} from the cache${b.unparsed ? `, ${num(b.unparsed)} could not be read` : ""}`,
    `${num(b.records)} records, ${num(b.sightings)} price sightings`,
    Object.keys(b.snapshot ?? {}).length ? `snapshot: ${Object.entries(b.snapshot).map(([k, v]) => `${k.replaceAll("_", " ")} ${num(v)}`).join(", ")}` : null,
  ].filter(Boolean).join("\n");
}

/**
 * Night by night, newest first: each source's scrape, the builds, and the publishes to the site. A
 * column opens that night's detail below the grid.
 */
export function NightsGrid({ nights }: { nights: PipelineNight[] }) {
  const [picked, setPicked] = useState<string | null>(null);
  if (!nights.length) return <Empty>No runs are logged yet.</Empty>;
  const sources = [...new Set(nights.flatMap((n) => n.scrapes.map((s) => s.source)))].sort();
  const open = nights.find((n) => n.night === picked) ?? nights.find((n) => n.scrapes.length || n.builds.length) ?? nights[0];
  const cell = "px-1 py-0.5 text-center text-xs tabular-nums";

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto">
        <table className="border-separate border-spacing-0.5 text-sm">
          <thead>
            <tr>
              <th className="sticky left-0 bg-gray-900 pr-2 text-left text-xs uppercase text-gray-500">Stage</th>
              {nights.map((n) => (
                <th key={n.night} className="px-0.5">
                  <button type="button" onClick={() => setPicked(n.night)} title={`From noon on ${n.night} to noon the next day (UTC). Show this night's detail.`}
                    className={`whitespace-nowrap rounded px-1 text-xs ${n.night === open.night ? "bg-gray-700 text-gray-100" : "text-gray-400 hover:text-gray-100"}`}>
                    {nightLabel(n.night)}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sources.map((src) => (
              <tr key={src}>
                <td className="sticky left-0 bg-gray-900 pr-2 text-xs text-gray-300">{src}</td>
                {nights.map((n) => {
                  const s = n.scrapes.find((x) => x.source === src);
                  return (
                    <td key={n.night} className={`${cell} rounded ${s ? scrapeTone(s) : "text-gray-700"}`} title={s ? scrapeTitle(s) : undefined}>
                      {s ? (rested(s) && !s.responses ? "rested" : num(s.responses || s.fetches)) : "·"}
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr>
              <td className="sticky left-0 bg-gray-900 pr-2 pt-1 text-xs font-medium text-gray-100">Build</td>
              {nights.map((n) => (
                <td key={n.night} className={`${cell} rounded ${n.builds.length ? (n.builds.some((b) => b.unparsed) ? "bg-amber-950 text-amber-200" : "bg-sky-950/70 text-sky-100") : "text-gray-700"}`}
                  title={n.builds.map(buildTitle).join("\n\n") || undefined}>
                  {n.builds.length ? (n.builds.length > 1 ? `${n.builds.length}×` : "✓") : "·"}
                </td>
              ))}
            </tr>
            <tr>
              <td className="sticky left-0 bg-gray-900 pr-2 text-xs font-medium text-gray-100">Publish</td>
              {nights.map((n) => (
                <td key={n.night} className={`${cell} rounded ${n.publishes.length ? "bg-sky-950/70 text-sky-100" : "text-gray-700"}`}
                  title={n.publishes.map((p) => `${dateLabel(p.at)} · ${p.subject}`).join("\n") || undefined}>
                  {n.publishes.length ? (n.publishes.length > 1 ? `${n.publishes.length}×` : "✓") : "·"}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      <p className="text-xs text-gray-500">
        A number is the responses a source&apos;s scrape kept that night. Amber: the site refused some, some were put off, or politeness held the source below its usual number; grey: resting after refusals; red: pages failed for another reason. Hover for the detail, or pick a night.
      </p>
      <NightDetail night={open} />
    </div>
  );
}

function NightDetail({ night }: { night: PipelineNight }) {
  return (
    <div className="space-y-3">
      <div className="text-sm font-medium text-gray-200">Night of {nightLabel(night.night)}</div>
      {night.scrapes.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-gray-500">
              <tr>
                <th className="py-1 pr-3">Scrape</th><th className="py-1 pr-3">Status</th>
                <th className="py-1 pr-3 text-right" title="Pages asked for; a fetch that combines several pages counts once">Asked</th>
                <th className="py-1 pr-3 text-right" title="Responses kept, the parts of a combined fetch included">Kept</th>
                <th className="py-1 pr-3 text-right">Refused</th><th className="py-1 pr-3 text-right" title="Put off to another night after two refusals">Put off</th>
                <th className="py-1 pr-3 text-right" title="Guessed pages the site does not have">Missing</th>
                <th className="py-1 pr-3 text-right">Records</th><th className="py-1 pr-3">Politeness</th><th className="py-1">Ran</th>
              </tr>
            </thead>
            <tbody>
              {night.scrapes.map((s) => (
                <tr key={s.source} className="border-t border-gray-800">
                  <td className="py-1 pr-3 text-gray-100" title={s.capabilities.join(", ")}>{s.source}</td>
                  <td className="py-1 pr-3">
                    {s.status ? <Badge tone={s.status === "ok" && !s.errors ? "good" : s.status === "refused" || s.errors <= s.refused ? "warn" : "bad"}>
                      {s.errors && s.errors <= s.refused ? `refused · ${s.refused}` : `${s.status}${s.errors ? ` · ${s.errors} failed` : ""}`}
                    </Badge> : <Badge tone="muted">no run logged</Badge>}
                  </td>
                  <td className="py-1 pr-3 text-right tabular-nums">{num(s.fetches)}</td>
                  <td className="py-1 pr-3 text-right tabular-nums">{num(s.responses)}</td>
                  <td className={`py-1 pr-3 text-right tabular-nums ${s.refused ? "text-amber-300" : "text-gray-600"}`}>{num(s.refused)}</td>
                  <td className={`py-1 pr-3 text-right tabular-nums ${s.deferred ? "text-amber-300" : "text-gray-600"}`}>{num(s.deferred)}</td>
                  <td className="py-1 pr-3 text-right tabular-nums text-gray-400">{num(s.skipped)}</td>
                  <td className="py-1 pr-3 text-right tabular-nums">{num(s.records)}</td>
                  <td className="py-1 pr-3 text-xs text-gray-400">{held(s) ?? "usual"}</td>
                  <td className="py-1 whitespace-nowrap text-xs text-gray-500">{s.started_at ? dateLabel(s.started_at) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <Empty>No scrape ran this night.</Empty>}
      <div className="space-y-1 text-sm">
        {night.builds.map((b, i) => (
          <div key={i} className="text-gray-300">
            <span className="font-medium text-gray-100">{b.this ? "This snapshot's build" : `Build (${b.mode})`}</span> {dateLabel(b.started_at)}, {num(b.seconds)} s:{" "}
            {num(b.fetches)} stored pages ({num(b.parsed)} parsed, {num(b.from_cache)} from the cache{b.unparsed ? <span className="text-amber-300">, {num(b.unparsed)} could not be read</span> : null}), {num(b.records)} records
            {b.snapshot?.cars != null ? `, ${num(b.snapshot.cars)} cars and ${num(b.snapshot.offers)} offers in the snapshot` : ""}
            {b.commit ? <> · code <a className="underline" href={`${REPO}/commit/${b.commit}`} target="_blank" rel="noreferrer">{b.commit}</a></> : null}
          </div>
        ))}
        {!night.builds.length && <div className="text-gray-500">No build logged this night.</div>}
        {night.publishes.map((p) => (
          <div key={p.sha} className="text-gray-300">
            <span className="font-medium text-gray-100">Published</span> {dateLabel(p.at)}: <a className="underline" href={`${REPO}/commit/${p.sha}`} target="_blank" rel="noreferrer">{p.subject}</a>
          </div>
        ))}
        {!night.publishes.length && <div className="text-gray-500">Nothing published this night.</div>}
      </div>
    </div>
  );
}
