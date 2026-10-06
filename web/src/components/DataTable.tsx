"use client";

import { useMemo, useState, type ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  /** Provide to make the column sortable. */
  sortValue?: (row: T) => number | string | null | undefined;
  align?: "left" | "right";
  title?: string;
}

interface Props<T> {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  defaultSort?: { key: string; dir: "asc" | "desc" };
  dense?: boolean;
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

export function DataTable<T>({ rows, columns, rowKey, defaultSort, dense }: Props<T>) {
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" } | null>(defaultSort ?? null);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sortValue) return rows;
    const sv = col.sortValue;
    const out = [...rows].sort((a, b) => cmp(sv(a), sv(b)));
    return sort.dir === "desc" ? out.reverse() : out;
  }, [rows, columns, sort]);

  function toggle(col: Column<T>) {
    if (!col.sortValue) return;
    setSort((s) =>
      s && s.key === col.key ? { key: col.key, dir: s.dir === "asc" ? "desc" : "asc" } : { key: col.key, dir: "asc" },
    );
  }

  const pad = dense ? "px-2 py-1" : "px-3 py-2";
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-800">
      <table className="w-full text-left text-sm">
        <thead className="bg-gray-900 text-xs uppercase tracking-wide text-gray-400">
          <tr>
            {columns.map((c) => {
              const active = sort?.key === c.key;
              return (
                <th
                  key={c.key}
                  title={c.title}
                  onClick={() => toggle(c)}
                  aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}
                  className={`${pad} whitespace-nowrap font-medium ${c.align === "right" ? "text-right" : ""} ${
                    c.sortValue ? "cursor-pointer select-none hover:text-gray-200" : ""
                  } ${active ? "text-gray-100" : ""}`}
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
            <tr key={rowKey(row)} className="hover:bg-gray-900/60">
              {columns.map((c) => (
                <td key={c.key} className={`${pad} align-top ${c.align === "right" ? "text-right tabular-nums" : ""}`}>
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td colSpan={columns.length} className="px-3 py-6 text-center text-gray-500">
                Nothing matches.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
