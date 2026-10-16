// Every field a car carries or costs, once: the label, the unit, the group it sits in and
// how to read it off a car. The Cars table offers each as a column, the search bar each
// number as a min/max, and the car page lists them all. Equipment flags join at run time
// from the snapshot's flag labels (`flagFields`), so a flag the pipeline learns is a column
// without a change here.
import { printed, type CarCosts } from "./costs";
import type { SnapshotCar, Tri } from "./types";

export type FieldKind = "number" | "money" | "text" | "bool" | "tri";

export const GROUPS = ["Price and cost", "Range and efficiency", "Battery and charging", "Performance", "Size and practicality",
  "Wheels", "Safety and warranty", "Tests and reliability", "Equipment", "About"] as const;
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
  { key: "monthly", label: "Lowest monthly payment as printed (deposit not counted)", short: "Lowest monthly", group: "Price and cost", kind: "money", step: 10,
    title: "The smallest monthly payment any PCP or lease prints, whatever deposit or up-front payment it needs; not comparable across cars", value: (_, k) => k?.monthly },
  { key: "cash", label: "Best cash price", short: "Best cash", group: "Price and cost", kind: "money", step: 500, value: (_, k) => k?.cash?.price },
  // Each finance route twice, for the same deal: what it truly costs a month on one footing with the other routes,
  // and the monthly payment the seller advertises.
  { key: "pcp", label: "PCP, true cost per month", short: "PCP true £/mo", group: "Price and cost", kind: "money", step: 10,
    title: "The cheapest PCP's true cost per month over your term: deposit, payments and the car's equity at the end, on the same footing as the other routes",
    value: (_, k) => k?.byRoute.pcp?.monthly },
  { key: "pcpAdvertised", label: "PCP, advertised monthly payment", short: "PCP advertised £/mo", group: "Price and cost", kind: "money", step: 10,
    title: "The monthly payment the seller advertises for the same PCP; its deposit and final payment are in the tooltip",
    value: (_, k) => k?.byRoute.pcp?.headline },
  { key: "pch", label: "Lease, true cost per month", short: "Lease true £/mo", group: "Price and cost", kind: "money", step: 10,
    title: "The cheapest lease's true cost per month over your term, the up-front payment included", value: (_, k) => k?.byRoute.pch?.monthly },
  { key: "pchAdvertised", label: "Lease, advertised monthly payment", short: "Lease advertised £/mo", group: "Price and cost", kind: "money", step: 10,
    title: "The monthly rental the seller advertises for the same lease; its up-front payment is in the tooltip",
    value: (_, k) => k?.byRoute.pch?.headline },
  { key: "used", label: "Used, cheapest of this trim and battery", short: "Used from", group: "Price and cost", kind: "money", step: 500,
    value: (_, k) => k?.byRoute.used?.headline },
  { key: "pcpPrinted", label: "PCP as printed", short: "PCP as printed", group: "Price and cost", kind: "text",
    value: (_, k) => (k?.byRoute.pcp ? printed(k.byRoute.pcp) : null) },
  { key: "pchPrinted", label: "Lease as printed", short: "Lease as printed", group: "Price and cost", kind: "text",
    value: (_, k) => (k?.byRoute.pch ? printed(k.byRoute.pch) : null) },
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
  n("legroom_front", "legroom_front_mm", "Legroom, front", "Size and practicality", "mm", 0, 10, "Leg front"),
  n("legroom_rear", "legroom_rear_mm", "Legroom, rear", "Size and practicality", "mm", 0, 10, "Leg rear"),
  n("headroom_front", "headroom_front_mm", "Headroom, front", "Size and practicality", "mm", 0, 10, "Head front"),
  n("headroom_rear", "headroom_rear_mm", "Headroom, rear", "Size and practicality", "mm", 0, 10, "Head rear"),
  n("shoulder_front", "shoulder_front_mm", "Shoulder room, front", "Size and practicality", "mm", 0, 10, "Shoulder front"),
  n("shoulder_rear", "shoulder_rear_mm", "Shoulder room, rear", "Size and practicality", "mm", 0, 10, "Shoulder rear"),
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
  t("tyres", "tyre_front", "Tyre size, front", "Wheels", "Tyres"),
  t("tyres_rear", "tyre_rear", "Tyre size, rear", "Wheels", "Rear tyres"),
  { ...n("sidewall", "sidewall_mm", "Tyre sidewall height (front)", "Wheels", "mm", 0, 5, "Sidewall mm"),
    title: "Tyre width × profile. Within one model, a taller sidewall usually softens sharp bumps; across models the suspension matters more" },

  // Tests and reliability: ADAC's Autotest of the model, graded as German school marks (lower is better), its breakdown
  // statistics, and What Car?'s survey of owners. Said of the model, from the one car each tested.
  ...(([
    ["adac_ride", "adac_suspension", "ADAC suspension (ride) grade", "ADAC ride"],
    ["adac_build", "adac_build", "ADAC build quality grade", "ADAC build"],
    ["adac_rear", "adac_rear_space", "ADAC rear seat space grade", "ADAC rear space"],
    ["adac_boot", "adac_boot", "ADAC boot space grade", "ADAC boot"],
    ["adac_comfort", "adac_comfort", "ADAC comfort grade", "ADAC comfort"],
    ["adac_family", "adac_family", "ADAC grade for families", "ADAC family"],
    ["adac_total", "adac_total", "ADAC overall grade", "ADAC overall"],
  ] as const).map(([key, field, label, short]): Field =>
    ({ ...n(key, field, label, "Tests and reliability", "", 1, 0.1, short), title: "ADAC's grade, as a German school mark: 0.6 is the best, 5.5 the worst" }))),
  t("adac_tested", "adac_tested", "What ADAC tested", "Tests and reliability", "ADAC tested"),
  // ADAC's own measurements of the car it tested, from the test's PDF.
  t("adac_tyres", "adac_tyres_tested", "Tyres on the car ADAC tested", "Tests and reliability", "ADAC tyres"),
  ...(([
    ["adac_boot_l", "adac_boot_measured_l", "Boot, seats up (ADAC measured)", "l", 0, 10, "ADAC boot l"],
    ["adac_boot_max_l", "adac_boot_max_measured_l", "Boot, seats folded to the roof (ADAC measured)", "l", 0, 50, "ADAC boot max l"],
    ["adac_turning", "adac_turning_circle_m", "Turning circle (ADAC measured)", "m", 1, 0.1, "ADAC turning m"],
    ["adac_braking", "adac_braking_100_m", "Braking from 62 mph (ADAC measured)", "m", 1, 0.5, "ADAC braking m"],
    ["adac_noise", "adac_noise_130_db", "Cabin noise at 81 mph (ADAC measured)", "dB(A)", 1, 0.5, "ADAC noise dB"],
    ["adac_range", "adac_ecotest_range_mi", "Range on ADAC's test cycle, miles (converted from km)", "mi", 0, 10, "ADAC range mi"],
    ["adac_efficiency", "adac_ecotest_mi_kwh", "Efficiency on ADAC's test cycle, charging losses included", "mi/kWh", 2, 0.1, "ADAC mi/kWh"],
    ["adac_dc_10_80", "adac_dc_10_80_min", "DC charge 10-80% (ADAC measured)", "min", 0, 1, "ADAC 10-80% min"],
    ["adac_dc_avg", "adac_dc_avg_kw", "DC average power 10-80% (ADAC measured)", "kW", 0, 5, "ADAC DC avg kW"],
    ["adac_full_charge", "adac_full_charge_kwh", "Energy for a full charge from the socket (ADAC measured)", "kWh", 1, 1, "ADAC full charge kWh"],
    ["adac_60_100", "adac_60_100_s", "37-62 mph (ADAC measured)", "s", 1, 0.1, "ADAC 37-62 s"],
    ["adac_width", "adac_width_mirrors_mm", "Width with mirrors (ADAC measured)", "mm", 0, 10, "ADAC width mm"],
    ["adac_weight", "adac_weight_kg", "Weight as tested (ADAC measured)", "kg", 0, 10, "ADAC weight kg"],
    ["adac_payload", "adac_payload_kg", "Payload as tested (ADAC measured)", "kg", 0, 10, "ADAC payload kg"],
  ] as const).map(([key, field, label, unit, digits, step, short]): Field => n(key, field, label, "Tests and reliability", unit, digits, step, short))),
  { ...n("breakdowns", "adac_breakdowns", "Breakdowns per 1,000 cars (ADAC)", "Tests and reliability", "", 1, 1, "Breakdowns /1,000"),
    title: "ADAC's roadside callouts in Germany per 1,000 cars of the model first registered in the year shown, every powertrain of the model together" },
  { ...n("breakdown_year", "adac_breakdown_year", "Breakdowns: cars first registered in", "Tests and reliability", "", 0, 1, "Breakdowns year"), plain: true },
  t("breakdown_rating", "adac_breakdown_rating", "Breakdowns: ADAC's grade against other cars that age", "Tests and reliability", "Breakdown grade"),
  t("breakdown_causes", "adac_breakdown_causes", "Breakdowns: what broke, and in which years' cars (ADAC)", "Tests and reliability", "Breakdown causes"),
  { ...n("reliability", "whatcar_reliability_pct", "Owners' reliability rating (What Car?)", "Tests and reliability", "%", 1, 1, "Reliability %"),
    title: "What Car?'s survey of owners of cars up to five years old: faults, repair costs and time off the road, as a percentage" },
  t("reliability_note", "whatcar_reliability", "Owners' reliability: place and common faults (What Car?)", "Tests and reliability", "Reliability"),
  { ...n("faulty", "whatcar_faulty_pct", "Cars that had a fault (What Car?)", "Tests and reliability", "%", 0, 1, "Had a fault %"),
    title: "The share of the model's cars in What Car?'s survey that went wrong, as its write-up states it" },
  { ...n("repairs_free", "whatcar_repairs_free_pct", "Repairs that cost the owner nothing (What Car?)", "Tests and reliability", "%", 0, 1, "Free repairs %"),
    title: "Of the faults owners reported, the share whose repair cost them £0" },
  { ...n("off_road_week", "whatcar_off_road_week_pct", "Faulty cars off the road over a week (What Car?)", "Tests and reliability", "%", 0, 1, "Off road >1 wk %"),
    title: "Of the cars that went wrong, the share out of action for more than a week" },
  t("platform_reliability", "platform_reliability", "Reliability of other models on its platform", "Tests and reliability", "Platform siblings"),
  { ...n("recalls", "recalls_count", "UK safety recalls naming the model", "Tests and reliability", "", 0, 1, "Recalls"),
    title: "Every DVSA safety recall since 2012 that names the model, earlier generations included; the car page lists them" },
  t("recalls_latest", "recalls_latest", "Latest UK safety recall", "Tests and reliability", "Latest recall"),
  { ...n("us_recalls", "us_recalls_count", "US safety recalls naming the model", "Tests and reliability", "", 0, 1, "US recalls"),
    title: "Every NHTSA safety recall of the US cars since model year 2019; blank where the model is not sold in the US; the car page lists them" },
  t("us_recalls_latest", "us_recalls_latest", "Latest US safety recall", "Tests and reliability", "Latest US recall"),
  { ...t("rear_seat_notes", "review_rear_seat_notes", "Back seat: knees, thighs, floor and room (Carwow's words)", "Tests and reliability", "Back seat"),
    title: "The sentences of Carwow's review about how a back-seat passenger sits: knees up or not, thigh support, a high floor, the room" },
  t("review_good", "review_good", "What's good (Carwow)", "Tests and reliability", "Good"),
  t("review_not_so_good", "review_not_so_good", "What's not so good (Carwow)", "Tests and reliability", "Not so good"),

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
  { ...t("on_sale_since", "on_sale_since", "On sale since (this version)", "About", "On sale since"),
    title: "When EV Database says this version went on sale; a used car registered before it is an earlier one and is not counted as it" },
  t("version", "version_date", "Derivative version", "About", "Version"),
  t("body", "body", "Body", "About"),
  t("segment", "segment", "Segment", "About"),
  t("platform", "platform", "Platform", "About"),
  t("cap_name", "cap_name", "CAP derivative name", "About", "CAP name"),
  { key: "packs", label: "Packs included", short: "Packs", group: "About", kind: "text", value: (c) => (c.packs?.length ? c.packs.join(" + ") : null) },
  { key: "on_sale", label: "On sale now", short: "On sale", group: "About", kind: "bool", value: (c) => !!c.on_sale },
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

export const triOf = (v: unknown): Tri => (v === "standard" || v === "pack" || v === "option" || v === "listed" || v === "none" ? v : "unknown");
