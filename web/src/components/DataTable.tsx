"use client";

import { useMemo, useState, type ReactNode } from "react";

import { arrange, isShown, move, readPrefs, toggle, writePrefs, type ColumnPrefs } from "@/lib/columns";

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** The column's name in the column chooser, when the header is not plain text. */
  label?: string;
  render: (row: T) => ReactNode;
  /** Provide to make the column sortable. */
  sortValue?: (row: T) => number | string | null | undefined;
  align?: "left" | "right";
  title?: string;
  /** Always shown, always first, and kept in view when the table scrolls sideways. */
  pinned?: boolean;
  /** Off until the reader turns it on in the column chooser. */
  hidden?: boolean;
}

interface Props<T> {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  defaultSort?: { key: string; dir: "asc" | "desc" };
  dense?: boolean;
  /** Keep the reader's choice of columns and their order in this browser under this name, and offer the chooser. */
  prefsKey?: string;
}

function cmp(a: number | string | null | undefined, b: number | string | null | undefined): number {
  const an = a == null || a === "";
  const bn = b == null || b === "";
  if (an && bn) return 0;
  if (an) return 1; // nulls last
  if (bn) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b));
}

const nameOf = <T,>(c: Column<T>): string => c.label ?? (typeof c.header === "string" ? c.header : c.key);

export function DataTable<T>({ rows, columns, rowKey, defaultSort, dense, prefsKey }: Props<T>) {
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" } | null>(defaultSort ?? null);
  const [prefs, setPrefsState] = useState<ColumnPrefs>(() => (prefsKey ? readPrefs(prefsKey) : { order: [], visible: {} }));
  const [choosing, setChoosing] = useState(false);
  const setPrefs = (p: ColumnPrefs) => {
    setPrefsState(p);
    if (prefsKey) writePrefs(prefsKey, p);
  };

  const ordered = useMemo(() => arrange(columns, prefs), [columns, prefs]);
  const shown = useMemo(() => ordered.filter((c) => isShown(c, prefs)), [ordered, prefs]);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sortValue) return rows;
    const sv = col.sortValue;
    const out = [...rows].sort((a, b) => cmp(sv(a), sv(b)));
    return sort.dir === "desc" ? out.reverse() : out;
  }, [rows, columns, sort]);

  function sortBy(col: Column<T>) {
    if (!col.sortValue) return;
    setSort((s) =>
      s && s.key === col.key ? { key: col.key, dir: s.dir === "asc" ? "desc" : "asc" } : { key: col.key, dir: "asc" },
    );
  }

  const pad = dense ? "px-2 py-1" : "px-3 py-2";
  const stick = (c: Column<T>, head: boolean) => (c.pinned ? `sticky left-0 z-10 ${head ? "bg-gray-900" : "bg-gray-950 group-hover:bg-gray-900"} border-r border-gray-800` : "");
  const movable = ordered.filter((c) => !c.pinned);
  const btn = "rounded border border-gray-700 px-1.5 leading-5 text-gray-300 hover:bg-gray-800 disabled:opacity-30";

  return (
    <div className="space-y-2">
      {prefsKey && (
        <div className="flex flex-wrap items-start justify-end gap-2 text-xs">
          <button type="button" onClick={() => setChoosing((o) => !o)} className="rounded border border-gray-700 px-2 py-1 text-gray-300 hover:text-gray-100" aria-expanded={choosing}>
            {choosing ? "Done" : `Columns · ${shown.length} of ${columns.length}`}
          </button>
          {choosing && (
            <div className="w-full rounded-lg border border-gray-800 bg-gray-900 p-2 sm:w-auto">
              <p className="mb-1 text-gray-500">Tick what to show; the arrows set the order. Kept in this browser.</p>
              <ul className="grid gap-x-4 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
                {movable.map((c, i) => (
                  <li key={c.key} className="flex items-center gap-1.5">
                    <button type="button" className={btn} disabled={i === 0} onClick={() => setPrefs(move(columns, prefs, c.key, -1))} aria-label={`Move ${nameOf(c)} earlier`}>↑</button>
                    <button type="button" className={btn} disabled={i === movable.length - 1} onClick={() => setPrefs(move(columns, prefs, c.key, 1))} aria-label={`Move ${nameOf(c)} later`}>↓</button>
                    <label className="flex items-center gap-1.5 text-gray-200">
                      <input type="checkbox" checked={isShown(c, prefs)} onChange={() => setPrefs(toggle(columns, prefs, c.key))} />
                      {nameOf(c)}
                    </label>
                  </li>
                ))}
              </ul>
              <button type="button" onClick={() => setPrefs({ order: [], visible: {} })} className="mt-2 text-gray-400 underline hover:text-gray-100">reset to the default columns</button>
            </div>
          )}
        </div>
      )}
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-gray-900 text-xs uppercase tracking-wide text-gray-400">
            <tr>
              {shown.map((c) => {
                const active = sort?.key === c.key;
                return (
                  <th
                    key={c.key}
                    title={c.title}
                    onClick={() => sortBy(c)}
                    aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}
                    className={`${pad} whitespace-nowrap font-medium ${c.align === "right" ? "text-right" : ""} ${
                      c.sortValue ? "cursor-pointer select-none hover:text-gray-200" : ""
                    } ${active ? "text-gray-100" : ""} ${stick(c, true)}`}
                  >
                    {c.header}
                    {active && <span className="ml-1">{sort.dir === "asc" ? "↑" : "↓"}</span>}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {sorted.map((row) => (
              <tr key={rowKey(row)} className="group hover:bg-gray-900/60">
                {shown.map((c) => (
                  <td key={c.key} className={`${pad} align-top ${c.align === "right" ? "text-right tabular-nums" : ""} ${stick(c, false)}`}>
                    {c.render(row)}
                  </td>
                ))}
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={shown.length} className="px-3 py-6 text-center text-gray-500">
                  Nothing matches.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
