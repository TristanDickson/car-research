"use client";

import type { ReactNode } from "react";

import { useProgress, type Progress } from "@/lib/progress";
import type { Tri } from "@/lib/types";

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-gray-100">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-gray-400">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

export function Card({ title, children, className = "" }: { title?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-gray-800 bg-gray-900 p-4 ${className}`}>
      {title && <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-400">{title}</h2>}
      {children}
    </section>
  );
}

export type Tone = "good" | "bad" | "warn" | "muted" | "info";

const TONE: Record<Tone, string> = {
  good: "bg-emerald-950 text-emerald-300 border-emerald-900",
  bad: "bg-rose-950 text-rose-300 border-rose-900",
  warn: "bg-amber-950 text-amber-300 border-amber-900",
  muted: "bg-gray-800 text-gray-300 border-gray-700",
  info: "bg-blue-950 text-blue-300 border-blue-900",
};

export function Badge({ tone = "muted", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-block whitespace-nowrap rounded border px-1.5 py-0.5 text-xs font-medium ${TONE[tone]}`}>
      {children}
    </span>
  );
}

const TRI_TONE: Record<Tri, Tone> = { standard: "good", pack: "info", option: "info", none: "bad", unknown: "muted" };
const TRI_LABEL: Record<Tri, string> = { standard: "std", pack: "pack", option: "option", none: "no", unknown: "?" };

export function TriBadge({ value, detail }: { value?: Tri; detail?: string }) {
  const v: Tri = value ?? "unknown";
  return <Badge tone={TRI_TONE[v]} title={detail}>{TRI_LABEL[v]}</Badge>;
}

const STATUS_TONE: Record<string, Tone> = {
  live: "good",
  lead: "info",
  derived: "warn",
  illustrative: "warn",
  campaign: "muted",
  expired: "muted",
  historical: "muted",
  gone: "bad",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={STATUS_TONE[status] ?? "muted"}>{status}</Badge>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded border border-dashed border-gray-800 p-6 text-center text-sm text-gray-500">{children}</p>;
}

/** A thin bar with what the data layer is doing (downloading a snapshot, costing every sighting). */
export function ProgressBar({ p, className = "" }: { p: Progress; className?: string }) {
  const pct = p.total > 0 ? Math.round((p.done / p.total) * 100) : 0;
  return (
    <div className={`text-xs text-gray-400 ${className}`} role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={p.label}>
      <div className="mb-1">{p.label}…</div>
      <div className="h-1.5 w-full overflow-hidden rounded bg-gray-800"><div className="h-full bg-sky-500 transition-[width] duration-300" style={{ width: `${Math.max(4, pct)}%` }} /></div>
    </div>
  );
}

export function Loading() {
  const p = useProgress();
  return p ? <div className="max-w-md"><ProgressBar p={p} /></div> : <p className="text-sm text-gray-500">Loading…</p>;
}

export function ErrorNote({ error }: { error: unknown }) {
  return (
    <p className="rounded border border-rose-900 bg-rose-950/40 p-3 text-sm text-rose-300">
      {(error as Error)?.message ?? String(error)}
    </p>
  );
}

/** Age of the last sighting, coloured by staleness. */
export function SeenBadge({ label, stale, gone }: { label: string; stale: boolean; gone?: boolean }) {
  return <Badge tone={gone ? "bad" : stale ? "warn" : "good"}>{gone ? `gone · last seen ${label}` : `seen ${label}`}</Badge>;
}
