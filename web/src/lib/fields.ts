// Every field a car carries or costs, once: the label, the unit, the group it sits in and
// how to read it off a car. The Cars table offers each as a column, the search bar each
// number as a min/max, and the car page lists them all. Equipment flags join at run time
// from the snapshot's flag labels (`flagFields`), so a flag the pipeline learns is a column
// without a change here.
import type { CarCosts } from "./costs";
import type { SnapshotCar, Tri } from "./types";

export type FieldKind = "number" | "money" | "text" | "bool" | "tri";

export const GROUPS = ["Price and cost", "Range and efficiency", "Battery and charging", "Performance", "Size and practicality",
  "Wheels", "Safety and warranty", "Equipment", "About"] as const;
export type Group = (typeof GROUPS)[number];

export interface Field {
  /** Column key, and the search bar's `r.<key>` for a number. */
  key: string;
  /** The car record's field, where the value is one: what the pipeline's provenance is keyed by. */
  field?: string;
  label: string;
  /** Column header. */
  short?: string;
  unit?: string;
  group: Group;
  kind: FieldKind;
  digits?: number;
  /** Step for the min/max inputs. */
  step?: number;
  /** A year or a count shown as it is: '2026', not '2,026'. */
  plain?: boolean;
  title?: string;
  value: (c: SnapshotCar, k: CarCosts | null) => number | string | boolean | null | undefined;
  /** For a tri-state field: the pack it comes in, for the badge's tooltip. */
  pack?: (c: SnapshotCar) => string | undefined;
}

type Rec = Record<string, unknown>;
const f = (name: string) => (c: SnapshotCar) => (c as unknown as Rec)[name] as number | string | boolean | null | undefined;
const n = (key: string, field: string, label: string, group: Group, unit = "", digits = 0, step?: number, short?: string): Field =>
  ({ key, field, label, short, unit, group, kind: "number", digits, step, value: f(field) });
const t = (key: string, field: string, label: string, group: Group, short?: string): Field => ({ key, field, label, short, group, kind: "text", value: f(field) });

export const FIELDS: Field[] = [
  // Price and cost: the costs come from the browser's cost model (lib/costs.ts) under the reader's basis.
  { key: "true", label: "True cost per month", short: "True £/mo", group: "Price and cost", kind: "money", step: 10,
    title: "Cheapest way to have the car, on one footing across cash, PCP, lease and used over your term", value: (_, k) => k?.trueCost?.monthly },
  { key: "monthly", label: "Pay monthly, cheapest", short: "Monthly", group: "Price and cost", kind: "money", step: 10, value: (_, k) => k?.monthly },
  { key: "cash", label: "Best cash price", short: "Best cash", group: "Price and cost", kind: "money", step: 500, value: (_, k) => k?.cash?.price },
  { key: "pcp", label: "PCP per month, as printed", short: "PCP £/mo", group: "Price and cost", kind: "money", step: 10, value: (_, k) => k?.byRoute.pcp?.headline },
  { key: "pch", label: "Lease per month, as printed", short: "Lease £/mo", group: "Price and cost", kind: "money", step: 10, value: (_, k) => k?.byRoute.pch?.headline },
  { key: "used", label: "Used, cheapest example", short: "Used from", group: "Price and cost", kind: "money", step: 500, value: (_, k) => k?.byRoute.used?.headline },
  { key: "threeYear", label: "Total over the agreement", short: "Total", group: "Price and cost", kind: "money", step: 500, value: (_, k) => k?.threeYear },
  { key: "fell", label: "Price change, 30 days", short: "30-day change", group: "Price and cost", kind: "money", step: 100, value: (_, k) => k?.trend?.delta },
  { key: "list", field: "list_price_gbp", label: "List price", short: "List", group: "Price and cost", kind: "money", step: 500, value: f("list_price_gbp") },
  { key: "grant", field: "grant_gbp", label: "Government grant", short: "Grant", group: "Price and cost", kind: "money", step: 250, value: f("grant_gbp") },
  { key: "net", label: "List price after grant", short: "List − grant", group: "Price and cost", kind: "money", step: 500,
    value: (c) => (c.list_price_gbp != null ? c.list_price_gbp - (c.grant_gbp ?? 0) : null) },
  { key: "sources", label: "Sources pricing it today", short: "Sources", group: "Price and cost", kind: "number", value: (_, k) => k?.sources },
  t("insurance", "insurance_group", "Insurance group", "Price and cost", "Insurance"),

  // Range and efficiency
  n("range", "wltp_range_mi", "WLTP range", "Range and efficiency", "mi", 0, 10, "WLTP mi"),
  n("real_range", "real_range_mi", "Real range (EV Database)", "Range and efficiency", "mi", 0, 10, "Real mi"),
  n("real_mild", "real_range_mild_mi", "Real range, mild weather", "Range and efficiency", "mi", 0, 10, "Mild mi"),
  n("real_cold", "real_range_cold_mi", "Real range, cold weather", "Range and efficiency", "mi", 0, 10, "Cold mi"),
  n("motorway_mild", "motorway_range_mild_mi", "Motorway range, mild weather", "Range and efficiency", "mi", 0, 10, "Mway mild"),
  n("motorway_cold", "motorway_range_cold_mi", "Motorway range, cold weather", "Range and efficiency", "mi", 0, 10, "Mway cold"),
  n("eff", "efficiency_mi_kwh", "Efficiency", "Range and efficiency", "mi/kWh", 1, 0.1, "mi/kWh"),

  // Battery and charging
  n("battery", "battery_kwh", "Battery, gross", "Battery and charging", "kWh", 1, 1, "kWh"),
  n("usable", "battery_usable_kwh", "Battery, usable", "Battery and charging", "kWh", 1, 1, "Usable kWh"),
  n("volts", "architecture_v", "Architecture", "Battery and charging", "V", 0, 100, "Volts"),
  t("chemistry", "battery_chemistry", "Battery chemistry", "Battery and charging", "Chemistry"),
  n("dc", "dc_peak_kw", "DC charging, peak", "Battery and charging", "kW", 0, 10, "DC peak"),
  n("dc_avg", "dc_avg_kw", "DC charging, 10–80% average", "Battery and charging", "kW", 0, 10, "DC avg"),
  n("charge", "dc_10_80_min", "DC 10–80% time", "Battery and charging", "min", 0, 5, "10–80 min"),
  n("ac", "ac_kw", "AC charging", "Battery and charging", "kW", 1, 1, "AC kW"),
  t("port", "charge_port", "Charge port", "Battery and charging", "Port"),
  n("v2l_kw", "v2l_kw", "V2L output", "Battery and charging", "kW", 1, 0.5, "V2L kW"),

  // Performance
  n("power", "power_hp", "Power", "Performance", "hp", 0, 10, "hp"),
  n("power_kw", "power_kw", "Power (kW)", "Performance", "kW", 0, 10, "kW"),
  n("torque", "torque_lbft", "Torque", "Performance", "lb-ft", 0, 10, "lb-ft"),
  n("accel", "zero_to_62_s", "0–62 mph", "Performance", "s", 1, 0.5, "0–62 s"),
  n("top_speed", "top_speed_mph", "Top speed", "Performance", "mph", 0, 5, "mph"),
  t("drive", "drive", "Drive", "Performance"),

  // Size and practicality
  n("length", "length_mm", "Length", "Size and practicality", "mm", 0, 10, "Length"),
  n("width", "width_mm", "Width", "Size and practicality", "mm", 0, 10, "Width"),
  n("width_mirrors", "width_mirrors_mm", "Width with mirrors", "Size and practicality", "mm", 0, 10, "W. mirrors"),
  n("height", "height_mm", "Height", "Size and practicality", "mm", 0, 10, "Height"),
  n("wheelbase", "wheelbase_m", "Wheelbase", "Size and practicality", "m", 2, 0.05, "Wheelbase"),
  n("turn", "turning_circle_m", "Turning circle", "Size and practicality", "m", 1, 0.1, "Turn m"),
  n("seats", "seats", "Seats", "Size and practicality", "", 0, 1),
  n("isofix", "isofix_seats", "ISOFIX seats", "Size and practicality", "", 0, 1, "ISOFIX"),
  n("doors", "doors", "Doors", "Size and practicality", "", 0, 1),
  n("boot", "boot_l", "Boot, seats up", "Size and practicality", "L", 0, 10, "Boot L"),
  n("boot_max", "boot_max_l", "Boot, seats down", "Size and practicality", "L", 0, 50, "Boot max L"),
  n("frunk", "frunk_l", "Front boot", "Size and practicality", "L", 0, 5, "Frunk L"),
  n("weight", "weight_kg", "Weight, unladen", "Size and practicality", "kg", 0, 50, "Weight"),
  n("gvwr", "gvwr_kg", "Gross vehicle weight", "Size and practicality", "kg", 0, 50, "GVW"),
  n("payload", "payload_kg", "Payload", "Size and practicality", "kg", 0, 25, "Payload"),
  n("roof_load", "roof_load_kg", "Roof load", "Size and practicality", "kg", 0, 5, "Roof kg"),
  { key: "roof_rails", field: "roof_rails", label: "Roof rails", group: "Size and practicality", kind: "bool", value: f("roof_rails") },
  n("tow", "tow_kg", "Towing, braked", "Size and practicality", "kg", 0, 100, "Tow kg"),
  n("tow_unbraked", "tow_unbraked_kg", "Towing, unbraked", "Size and practicality", "kg", 0, 50, "Tow unbr."),

  // Wheels
  n("wheels", "wheel_in", "Wheel size", "Wheels", "in", 0, 1, "Wheels in"),
  t("wheel_options", "wheel_options", "Other wheel sizes offered", "Wheels", "Wheel options"),

  // Safety and warranty
  n("ncap", "ncap_stars", "Euro NCAP stars", "Safety and warranty", "", 0, 1, "NCAP ★"),
  n("ncap_adult", "ncap_adult_pct", "Euro NCAP adult occupant", "Safety and warranty", "%", 0, 5, "Adult %"),
  n("ncap_child", "ncap_child_pct", "Euro NCAP child occupant", "Safety and warranty", "%", 0, 5, "Child %"),
  n("ncap_vru", "ncap_vru_pct", "Euro NCAP vulnerable road users", "Safety and warranty", "%", 0, 5, "VRU %"),
  n("ncap_assist", "ncap_assist_pct", "Euro NCAP safety assist", "Safety and warranty", "%", 0, 5, "Assist %"),
  { ...n("ncap_year", "ncap_year", "Euro NCAP year", "Safety and warranty", "", 0, 1, "NCAP year"), plain: true },
  n("warranty", "warranty_years", "Battery warranty", "Safety and warranty", "years", 0, 1, "Warranty yrs"),
  n("warranty_mi", "warranty_miles", "Battery warranty mileage", "Safety and warranty", "mi", 0, 10000, "Warranty mi"),

  // About
  { ...n("year", "model_year", "Model year", "About", "", 0, 1, "Year"), plain: true },
  t("version", "version_date", "Derivative version", "About", "Version"),
  t("body", "body", "Body", "About"),
  t("segment", "segment", "Segment", "About"),
  t("platform", "platform", "Platform", "About"),
  t("cap_name", "cap_name", "CAP derivative name", "About", "CAP name"),
  { key: "packs", label: "Packs included", short: "Packs", group: "About", kind: "text", value: (c) => (c.packs?.length ? c.packs.join(" + ") : null) },
  { key: "curated", label: "Hand-curated", group: "About", kind: "bool", value: (c) => !c.auto },
];

/** The car record names three flags its own way; packs_required uses those names. */
const PACK_FIELD: Record<string, string> = { v2l_internal: "internal_v2l", v2l_external: "external_v2l" };

/** One tri-state column per equipment flag the snapshot names. */
export function flagFields(flagLabels: Record<string, string>): Field[] {
  return Object.entries(flagLabels).map(([k, label]) => ({
    key: `flag:${k}`, field: k, label, group: "Equipment" as const, kind: "tri" as const,
    value: (c: SnapshotCar) => c.flags?.[k] ?? null,
    pack: (c: SnapshotCar) => c.packs_required?.[PACK_FIELD[k] ?? k] ?? c.packs_required?.[k],
  }));
}

/** The fields a range filter can bound: every number and amount. */
export const RANGE_FIELDS = FIELDS.filter((x) => x.kind === "number" || x.kind === "money");
export const FIELD_BY_KEY = new Map(FIELDS.map((x) => [x.key, x]));

/** A field's value as text: '1,825 mm', '£35,000', 'yes'. */
export function show(x: Field, v: ReturnType<Field["value"]>): string {
  if (v == null || v === "") return "—";
  if (x.kind === "bool") return v ? "yes" : "no";
  if (x.kind === "money" && typeof v === "number") return `${v < 0 ? "−" : ""}£${Math.abs(v).toLocaleString("en-GB", { maximumFractionDigits: 0 })}`;
  if (typeof v === "number") return `${v.toLocaleString("en-GB", { maximumFractionDigits: x.digits ?? 0, useGrouping: !x.plain })}${x.unit ? (x.unit === "%" ? "%" : ` ${x.unit}`) : ""}`;
  return String(v);
}

export const triOf = (v: unknown): Tri => (v === "standard" || v === "pack" || v === "option" || v === "none" ? v : "unknown");
