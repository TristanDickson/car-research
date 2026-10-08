// Which columns a table shows and in what order, chosen by the reader and kept in
// this browser (localStorage, per table), so a phone held sideways can show the
// few that matter first. Pure arrangement here; components/DataTable draws it.

export interface ColumnPrefs {
  /** Column keys in the reader's order; a column not named keeps its default place after them. */
  order: string[];
  /** Shown (true) or not (false); a column not named follows its default. */
  visible: Record<string, boolean>;
}

export const NO_PREFS: ColumnPrefs = { order: [], visible: {} };

export interface Arrangeable {
  key: string;
  /** Always shown, always first. */
  pinned?: boolean;
  /** Off until the reader turns it on. */
  hidden?: boolean;
}

/** Every column in the reader's order: pinned first, then the named order, then the rest in default order. */
export function arrange<C extends Arrangeable>(columns: C[], prefs: ColumnPrefs): C[] {
  const byKey = new Map(columns.map((c) => [c.key, c]));
  const pinned = columns.filter((c) => c.pinned);
  const named = prefs.order.map((k) => byKey.get(k)).filter((c): c is C => !!c && !c.pinned);
  const seen = new Set(named.map((c) => c.key));
  const rest = columns.filter((c) => !c.pinned && !seen.has(c.key));
  return [...pinned, ...named, ...rest];
}

export const isShown = (c: Arrangeable, prefs: ColumnPrefs): boolean => !!c.pinned || (prefs.visible[c.key] ?? !c.hidden);

/** Move a column one place up (-1) or down (+1) among the unpinned ones. */
export function move<C extends Arrangeable>(columns: C[], prefs: ColumnPrefs, key: string, by: -1 | 1): ColumnPrefs {
  const keys = arrange(columns, prefs).filter((c) => !c.pinned).map((c) => c.key);
  const i = keys.indexOf(key);
  const j = i + by;
  if (i < 0 || j < 0 || j >= keys.length) return prefs;
  [keys[i], keys[j]] = [keys[j], keys[i]];
  return { ...prefs, order: keys };
}

export function toggle<C extends Arrangeable>(columns: C[], prefs: ColumnPrefs, key: string): ColumnPrefs {
  const c = columns.find((x) => x.key === key);
  if (!c || c.pinned) return prefs;
  return { ...prefs, visible: { ...prefs.visible, [key]: !isShown(c, prefs) } };
}

const storageKey = (table: string) => `columns:${table}`;

export function readPrefs(table: string): ColumnPrefs {
  try {
    const raw = typeof window === "undefined" ? null : window.localStorage.getItem(storageKey(table));
    if (!raw) return NO_PREFS;
    const p = JSON.parse(raw) as Partial<ColumnPrefs>;
    return { order: Array.isArray(p.order) ? p.order.map(String) : [], visible: p.visible && typeof p.visible === "object" ? p.visible : {} };
  } catch {
    return NO_PREFS;
  }
}

export function writePrefs(table: string, prefs: ColumnPrefs): void {
  try {
    if (prefs.order.length === 0 && Object.keys(prefs.visible).length === 0) window.localStorage.removeItem(storageKey(table));
    else window.localStorage.setItem(storageKey(table), JSON.stringify(prefs));
  } catch {
    /* private window or storage blocked: the choice lasts until the page closes */
  }
}
