// Cars that share a displayed name (make, model, trim) are different derivatives: another
// price list, a pack Carwow does not name, a seat count. A short note under the name says
// what tells each apart. It is presentation, worked out here from the fields every car
// already carries, so changing it needs no rebuild of the data.
import type { SnapshotCar } from "./types";

type Named = Pick<SnapshotCar, "id" | "make" | "model" | "trim" | "cap_name" | "cap_id" | "seats" | "version_date" | "list_price_gbp">;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** What can tell look-alikes apart, in the order a note tries them; the price only when nothing else does. */
const ASPECTS: ((c: Named) => string | null)[] = [
  (c) => (c.cap_name?.match(/\[[^\]]+\]/g) ?? []).join(" ") || null,
  (c) => (c.seats ? `${c.seats} seats` : null),
  (c) => (c.version_date && c.version_date.length >= 7 ? `price list ${MONTHS[Number(c.version_date.slice(5, 7)) - 1]} ${c.version_date.slice(0, 4)}` : null),
  (c) => (c.list_price_gbp ? `£${c.list_price_gbp.toLocaleString("en-GB", { maximumFractionDigits: 0 })}` : null),
];

/** For each car that shares its displayed name with another, the note that tells it apart. Aspects are
 * taken in order only while the cars are not yet told apart; the CAP id if all else agrees. */
export function nameNotes(cars: Named[]): Map<string, string> {
  const groups = new Map<string, Named[]>();
  for (const c of cars) {
    const k = `${c.make}|${c.model}|${c.trim}`;
    groups.set(k, [...(groups.get(k) ?? []), c]);
  }
  const out = new Map<string, string>();
  for (const members of groups.values()) {
    if (members.length < 2) continue;
    const used: typeof ASPECTS = [];
    for (const a of ASPECTS) {
      if (new Set(members.map(a)).size < 2) continue;
      used.push(a);
      if (new Set(members.map((c) => JSON.stringify(used.map((u) => u(c))))).size === members.length) break;
    }
    const note = (c: Named) => used.map((a) => a(c)).filter(Boolean).join(" · ");
    const unique = new Set(members.map(note)).size === members.length;
    for (const c of members) {
      const n = unique ? note(c) : [note(c), c.cap_id ? `CAP ${c.cap_id}` : null].filter(Boolean).join(" · ");
      if (n) out.set(c.id, n);
    }
  }
  return out;
}

/** The cars with their notes (replacing whatever note the data carried). */
export function withNameNotes<T extends Named & { name_note?: string }>(cars: T[]): T[] {
  const notes = nameNotes(cars);
  return cars.map((c) => {
    const n = notes.get(c.id);
    if (n === c.name_note) return c;
    const out = { ...c };
    if (n) out.name_note = n;
    else delete out.name_note;
    return out;
  });
}
