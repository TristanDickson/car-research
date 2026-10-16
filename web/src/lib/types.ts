// Shapes of the committed snapshot (web/public/data), produced by
// pipeline/services/snapshot.py. Keep in step with SCHEMA_VERSION there.

export interface SnapshotManifest {
  schema_version: string;
  generated_at: string;
  counts: Record<string, number>;
  runs?: { source: string; capability: string; finished_at: string | null; status: string }[];
}

/** standard = fitted on this trim; pack/option = available for this trim via a
 * named pack or option; none = not available; unknown = not captured. */
export type Tri = "standard" | "pack" | "option" | "listed" | "none" | "unknown";

/** gone = the latest check did not find the offer; expired = past valid_to or
 * the source said so; otherwise the status the source implied when last seen. */
export type OfferState = "live" | "lead" | "derived" | "illustrative" | "campaign" | "expired" | "historical" | "gone";

export interface ObservationPoint {
  observed_at: string;
  /** Last time this exact state was confirmed; null when seen once. */
  confirmed_at?: string | null;
  present: boolean;
  source: string;
  monthly_payment?: number;
  vehicle_price?: number;
  apr?: number;
  gfv?: number;
  initial_rental?: number;
  monthly_rental?: number;
}

export interface Freshness {
  state: OfferState;
  /** Relative to manifest.generated_at. The UI recomputes age from last_seen_at. */
  stale: boolean;
  age_days: number | null;
  first_seen_at: string;
  last_seen_at: string | null;
  last_checked_at: string;
  observations: number;
  present: boolean;
  history: ObservationPoint[];
}

/** One used listing as used.json carries it (every listing ever seen; present = still on sale). */
export interface SnapshotUsed {
  listing_key: string;
  provider: string;
  source?: string | null;
  make?: string | null;
  make_slug?: string | null;
  model?: string | null;
  model_slug?: string | null;
  /** make/model slugs, the subject of the model's used series (added at load). */
  model_key?: string;
  /** model|trim|battery: the cars this listing counts as (SnapshotCar.used_key). */
  used_key?: string | null;
  car_id?: string | null;
  price_gbp: number | null;
  year: number | null;
  mileage: number | null;
  present: boolean;
  first_seen_at: string;
  last_seen_at: string;
  derivative?: string | null;
  town?: string | null;
  url?: string | null;
  image_url?: string | null;
  vrm?: string | null;
  /** The site's finance quote for this car: cinch's in full, Motorpoint's lowest monthly ('lowest'). */
  finance?: UsedFinance | null;
  colour?: string | null;
  drive?: string | null;
  discount_gbp?: number | null;
  previous_price_gbp?: number | null;
  tags?: string[] | null;
  badges?: string[] | null;
  warranty_months_left?: number | null;
  plate_age_id?: string | null;
  price_before_fees?: number | null;
  first_listed_at?: string | null;
  list_price_when_new?: number | null;
  /** Motorpoint's 'coming soon': priced, not yet on its forecourt. */
  coming_soon?: boolean | null;
  /** Carwow: how much its card gave ('card', 'stored-card' from an earlier night, 'price-year' when only the price and year are known). */
  detail?: string | null;
  card_seen_at?: string | null;
  /** Carwow's own state for the car: 'New' for a pre-registered car in its used results. */
  vehicle_state?: string | null;
  /** What cinch says of the car in fields of its own. */
  trim?: string | null;
  seats?: number | null;
  doors?: number | null;
  body?: string | null;
  /** 'Electric', or 'Electric range extender'. */
  fuel?: string | null;
  range_mi?: number | null;
  /** The test the range comes from: 'WLTP', or 'NEDC' (older cars, reads higher). */
  range_test?: string | null;
  /** Whose stock it is on cinch: 'cinch', 'marketplace', 'partner_sourced'. */
  stock_type?: string | null;
}

export interface UsedFinance {
  type: string;
  monthly_payment: number;
  deposit?: number;
  apr?: number;
  num_payments?: number;
  term_months?: number;
  final_payment?: number;
  credit?: number;
  charges?: number;
  annual_mileage?: number;
  excess_mileage_ppm?: number;
  reconciles?: boolean | null;
  /** The site's lowest monthly for the car rather than a full quote. */
  lowest?: boolean;
}

/** The long text a model's cars share (Carwow's review sections, the recall registers' lines), which details.json
 * holds once for the model under `model:<model_key>` (pipeline/services/snapshot.py MODEL_TEXT). A car keeps its own
 * copy where its model's cars differ. */
export type ModelTextField = "recalls" | "us_recalls" | "review_rear_seats" | "review_ride_town" | "review_ride_motorway" | "review_interior" | "review_reliability";

/** What only the car page reads, fetched on demand (details.json, keyed by car id). */
export interface CarDetails {
  id: string;
  /** Only on a model's entry (`model:<model_key>`), which has nothing else. */
  text?: Partial<Record<ModelTextField, string>>;
  specs: CarSpecSummary[];
  /** Where each resolved field came from (services/claims.py). */
  field_sources?: Record<string, string> | null;
  /** Fields the strongest sources disagree on, with both sides; the field stays unknown. */
  disagreements?: Record<string, string[]> | null;
  /** A named, maker or configured claim a stronger one set aside. */
  overruled?: Record<string, string[]> | null;
}

/** One offer observation span as sightings.json carries it: a price one source
 * showed for one derivative over the days it stayed the same, with the payload
 * the browser costs (lib/model). */
export interface SnapshotSighting {
  key: string;
  car_id: string;
  /** make/model slugs. */
  model: string;
  route: FinanceType;
  /** The site (a source id; data.json names it), and the provider that read it. */
  source: string;
  provider: string;
  status: string;
  seller: string | null;
  from: string;
  to: string;
  present: boolean;
  deal: Record<string, unknown>;
}

/** One used listing's asking-price span (used_spans.json). */
export interface SnapshotUsedSpan {
  key: string;
  source: string;
  model: string;
  car_id: string | null;
  /** model|trim|battery: the cars this used car counts as (SnapshotCar.used_key); null when it names no derivative. */
  used_key?: string | null;
  year: number | null;
  price: number | null;
  mileage: number | null;
  vrm: string | null;
  town: string | null;
  from: string;
  to: string;
  present: boolean;
  /** Motorpoint's 'coming soon': priced, not yet on its forecourt. */
  coming_soon?: boolean;
  /** Carwow's own state for the car: 'New' for a pre-registered car in its used results. */
  vehicle_state?: string;
}

export interface SnapshotCar {
  /** make/model slugs: the model's used stock, the evidence for what a car of each age is worth. */
  model_key?: string;
  /** model|trim|battery: the used cars that count as this car (the buy-used route). */
  used_key?: string | null;
  /** Carwow lists the derivative now, or it has a current price; false = an old price-list version. */
  on_sale?: boolean;
  /** What tells this car apart from others of the same displayed name ('[Heat Pump] · price list Jul 2026'): set by the app when cars load (lib/names.ts), not by the data. */
  name_note?: string;
  id: string;
  /** How many spec rows describe this car (details.json has them). */
  spec_count?: number;
  /** The derivative's CAP name as Carwow's model page prints it, brackets included. */
  cap_name?: string;
  /** Canonical equipment flags merged from the car's spec rows: standard beats option beats unlisted. */
  flags?: Record<string, FlagState>;
  make: string;
  model: string;
  trim: string;
  /** 'spec' (from the Carwow specification page) or 'stub' (only a deals page or the registry printed it). */
  source_kind?: "spec" | "stub";
  variant?: string;
  cap_id?: string;
  make_slug?: string;
  model_slug?: string;
  version_date?: string | null;
  packs?: string[];
  model_year?: number | null;
  /** 'YYYY-MM' this version went on sale (EV Database's variant); a used car registered before it is an earlier one. */
  on_sale_since?: string | null;
  fuel?: string;
  body?: string;
  seats?: number | null;
  battery_kwh?: number | null;
  wltp_range_mi?: number | null;
  real_range_mi?: number | null;
  power_hp?: number | null;
  architecture_v?: number | null;
  dc_peak_kw?: number | null;
  /** Average charging power over a 10-80% rapid charge (EV Database). */
  dc_avg_kw?: number | null;
  dc_10_80_min?: number | null;
  ac_kw?: number | null;
  top_speed_mph?: number | null;
  weight_kg?: number | null;
  tow_kg?: number | null;
  evdb_url?: string | null;
  battery_usable_kwh?: number | null;
  battery_chemistry?: string | null;
  real_range_cold_mi?: number | null;
  real_range_mild_mi?: number | null;
  motorway_range_cold_mi?: number | null;
  motorway_range_mild_mi?: number | null;
  power_kw?: number | null;
  torque_lbft?: number | null;
  drive?: string | null;
  charge_port?: string | null;
  v2l_kw?: number | null;
  isofix_seats?: number | null;
  doors?: number | null;
  frunk_l?: number | null;
  wheelbase_m?: number | null;
  width_mirrors_mm?: number | null;
  gvwr_kg?: number | null;
  payload_kg?: number | null;
  roof_load_kg?: number | null;
  roof_rails?: boolean | null;
  tow_unbraked_kg?: number | null;
  /** Interior space by row, mm, as the maker prints it; rear is the 2nd row. */
  legroom_front_mm?: number | null;
  legroom_rear_mm?: number | null;
  headroom_front_mm?: number | null;
  headroom_rear_mm?: number | null;
  shoulder_front_mm?: number | null;
  shoulder_rear_mm?: number | null;
  /** The wheel size fitted as standard, inches. */
  wheel_in?: number | null;
  /** Other sizes the configurator offers: '19", 20"'. */
  wheel_options?: string | null;
  /** The tyres the derivative is sold on, as CAP's technical data gives them: '215/55 R17'. */
  tyre_front?: string | null;
  tyre_rear?: string | null;
  /** The front tyre's sidewall height, mm: width × profile. */
  sidewall_mm?: number | null;
  /** ADAC's Autotest of the model (German school grades: 0.6 best, 5.5 worst) and what it tested. */
  adac_total?: number | null;
  adac_suspension?: number | null;
  adac_comfort?: number | null;
  adac_build?: number | null;
  adac_boot?: number | null;
  adac_rear_space?: number | null;
  adac_family?: number | null;
  adac_tested?: string | null;
  /** ADAC's own measurements of the car it tested, from the test's PDF: the tyres it was on ('235/45 R19 99V, Nexen N Fera Sport'),
   *  boot (seats up; folded to the roof), turning circle, braking from 62 mph, noise at 81 mph, the test cycle's range (miles,
   *  converted from km) and efficiency, DC 10-80% time and average power, energy for a full charge, 37-62 mph, width with
   *  mirrors, weight and payload. */
  adac_tyres_tested?: string | null;
  adac_boot_measured_l?: number | null;
  adac_boot_max_measured_l?: number | null;
  adac_turning_circle_m?: number | null;
  adac_braking_100_m?: number | null;
  adac_noise_130_db?: number | null;
  adac_ecotest_range_mi?: number | null;
  adac_ecotest_mi_kwh?: number | null;
  adac_dc_10_80_min?: number | null;
  adac_dc_avg_kw?: number | null;
  adac_full_charge_kwh?: number | null;
  adac_60_100_s?: number | null;
  adac_width_mirrors_mm?: number | null;
  adac_weight_kg?: number | null;
  adac_payload_kg?: number | null;
  /** ADAC's breakdown statistics for the model: callouts per 1,000 cars first registered in that year, and its grade. */
  adac_breakdowns?: number | null;
  adac_breakdown_year?: number | null;
  adac_breakdown_rating?: string | null;
  /** What broke down, as ADAC lists it, with the registration years: '12-volt battery (2021-2023); general electrics (2022-2023)'. */
  adac_breakdown_causes?: string | null;
  /** What Car?'s owner reliability rating for the model, and its place and common faults. */
  whatcar_reliability_pct?: number | null;
  whatcar_reliability?: string | null;
  /** From What Car?'s write-up: the share of cars with a fault, of repairs that cost the owner nothing, of faulty cars off the road over a week. */
  whatcar_faulty_pct?: number | null;
  whatcar_repairs_free_pct?: number | null;
  whatcar_off_road_week_pct?: number | null;
  /** What What Car?'s owners and ADAC say of the other models on the car's platform. */
  platform_reliability?: string | null;
  /** DVSA's safety recalls naming the model since 2012: how many, the latest launch date, and one line each, newest first. */
  recalls_count?: number | null;
  recalls_latest?: string | null;
  recalls?: string | null;
  /** Carwow's review of the model, in its words: the verdict lists, the back seats (and what they say of knees,
   * thighs, the floor and the room), the ride in town and on the motorway, the interior, reliability. */
  review_good?: string | null;
  review_not_so_good?: string | null;
  review_rear_seat_notes?: string | null;
  review_rear_seats?: string | null;
  review_ride_town?: string | null;
  review_ride_motorway?: string | null;
  review_interior?: string | null;
  review_reliability?: string | null;
  /** NHTSA's US safety recalls naming the model since model year 2019: how many, the latest report date, one line each, newest first; for a model not sold in the US, a line that says so. */
  us_recalls_count?: number | null;
  us_recalls_latest?: string | null;
  us_recalls?: string | null;
  segment?: string | null;
  platform?: string | null;
  ncap_stars?: number | null;
  ncap_adult_pct?: number | null;
  ncap_child_pct?: number | null;
  ncap_vru_pct?: number | null;
  ncap_assist_pct?: number | null;
  ncap_year?: number | null;
  warranty_years?: number | null;
  warranty_miles?: number | null;
  zero_to_62_s?: number | null;
  length_mm?: number | null;
  width_mm?: number | null;
  height_mm?: number | null;
  turning_circle_m?: number | null;
  boot_l?: number | null;
  boot_max_l?: number | null;
  boot_notes?: string;
  efficiency_mi_kwh?: number | null;
  insurance_group?: string | null;
  heat_pump?: Tri;
  internal_v2l?: Tri;
  external_v2l?: Tri;
  packs_required?: Record<string, string> | null;
  pack_prices_gbp?: Record<string, number> | null;
  powered_sliding_doors?: number | null;
  memory_seats?: boolean;
  glass_roof?: boolean;
  heated_seats?: boolean;
  ventilated_seats?: boolean;
  camera_360?: boolean;
  list_price_gbp?: number | null;
  list_price_breakdown?: Record<string, number>;
  grant_gbp?: number | null;
  used_from_gbp?: number | null;
  expensive_car_supplement?: boolean;
  image_url?: string | null;
  /** Committed photo path (prefix with the base path) or image_url, resolved at export. */
  image?: string | null;
}

export interface UsedListing {
  listing_key: string;
  price_gbp: number;
  year: number | null;
  mileage: number | null;
  derivative: string | null;
  town: string | null;
  url: string | null;
  image_url?: string | null;
  age_days?: number | null;
  /** Which site lists it; 'sources' names every site when the same car is on more than one. */
  source?: string | null;
  sources?: string[] | null;
}

export type FinanceType = "pcp" | "pch" | "cash" | "campaign";
/** A route on the true-monthly footing: the three finance types plus buying used. */
export type Route = "pcp" | "pch" | "cash" | "used";

export interface DealMetrics {
  skipped?: string;
  /** Every route on one footing: present cost at the savings rate, expected end value
   * credited back, spread as an annuity over the agreement. floor = end value at the GFV. */
  true_monthly?: number | null;
  true_monthly_floor?: number | null;
  pv_cost?: number | null;
  expected_value_at_end?: number | null;
  /** used-market (the model's stock at that age), gfv-grown (the lender's floor at the savings rate), assumption */
  residual_source?: string;
  expected_equity?: number | null;
  horizon_months?: number | null;
  /** A campaign (terms only, nothing to cost) keeps its APR for the table. */
  apr?: number | null;
  // pcp
  list_price?: number | null;
  vehicle_price?: number;
  manufacturer_contribution?: number;
  customer_deposit?: number;
  amount_of_credit?: number;
  num_payments?: number;
  term_months?: number;
  monthly_payment?: number;
  apr_stated?: number | null;
  apr_implied?: number | null;
  gfv?: number;
  gfv_pct_of_list?: number | null;
  gfv_pct_of_price?: number | null;
  paid_if_handed_back?: number;
  paid_if_bought?: number;
  cost_of_credit?: number;
  finance_vs_own_cash_price?: number;
  effective_monthly_hand_back?: number;
  monthly_at_0pct_same_gfv?: number;
  interest_per_month?: number;
  /** The monthly its credit, APR and final payment give, and whether the printed one is it (lib/model/dealMath.ts, pcpAddsUp). */
  monthly_at_stated_apr?: number | null;
  adds_up?: boolean | null;
  derived_fields?: string[];
  best_cash_price?: number;
  best_cash_deal_id?: string;
  acquisition_penalty_vs_cash?: number;
  funding_premium_vs_cash?: number;
  effective_rate_vs_cash?: number | null;
  // pch
  initial_rental?: number;
  monthly_rental?: number;
  num_rentals?: number;
  fees?: number;
  total_cost?: number;
  effective_monthly?: number;
  annual_mileage?: number | null;
  // cash
  discount_vs_list?: number | null;
}

export interface SnapshotOffer {
  id: string;
  car_id: string;
  provider: string;
  freshness: Freshness;
  captured_at: string;
  deal_date?: string;
  finance_type: FinanceType;
  status: string;
  verification?: string;
  source?: string;
  source_url?: string;
  source_ref?: string;
  dealer?: string;
  valid_from?: string;
  valid_to?: string;
  list_price?: number | null;
  vehicle_price?: number | null;
  dealer_discount?: number | null;
  grant_gbp?: number | null;
  saving_stated?: number | null;
  manufacturer_contribution?: number | null;
  customer_deposit?: number | null;
  amount_of_credit?: number | null;
  term_months?: number | null;
  num_payments?: number | null;
  first_payment?: number | null;
  monthly_payment?: number | null;
  apr?: number | null;
  fixed_rate_pa?: number | null;
  gfv?: number | null;
  total_payable_stated?: number | null;
  cost_of_credit_stated?: number | null;
  annual_mileage?: number | null;
  excess_mileage_ppm?: number | null;
  fees_gbp?: number | null;
  profile?: string;
  initial_rental?: number | null;
  num_rentals?: number | null;
  monthly_rental?: number | null;
  total_stated?: number | null;
  mileage?: number | null;
  warranty_remaining?: string;
  notes?: string;
  num_payments_stated?: number | null;
  condition?: string;
  location?: string | null;
  metrics: DealMetrics;
  /** The figure the cards rank by (over the reader's horizon or the deal's own term), and the deal's own-term figure. */
  comparable?: { true_monthly: number | null; horizon_months: number; at_horizon: string; own_true_monthly: number | null; own_horizon_months: number; end_value: number | null } | null;
}

/** An offer as the browser derives it from its spans (lib/model/offers.ts): the
 * latest state, its freshness, and the normalisation under the reader's basis. */
export type SnapshotDeal = SnapshotOffer;

export interface RunRow {
  id: number;
  source: string;
  capability: string;
  target: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  artifacts: number;
  records: number;
  unmapped: number;
  errors?: number;
}

export interface UnmappedTrim {
  source: string;
  source_key: string;
  label: string | null;
  example_url: string | null;
  first_seen_at: string;
  last_seen_at: string;
  status?: "unmapped" | "conflict";
  method?: string | null;
  evidence?: Record<string, unknown> | null;
}

export interface DataPage {
  generated_at: string;
  stale_days: number;
  flag_labels?: Record<string, string>;
  providers: {
    name: string;
    live?: boolean;
    description?: string;
    source?: string;
    capabilities: { name: string; kinds: string[]; parser_version: string }[];
  }[];
  runs: RunRow[];
  unmapped_trims: UnmappedTrim[];
  offer_states: Record<string, number>;
  counts: Record<string, number>;
  /** Source id → display name (several providers read the same site). */
  sources?: Record<string, string>;
  /** How resolved trim-map rows were resolved: manual, cap-id, rrp, bracket, ... */
  resolution_methods?: Record<string, number>;
  /** What each source holds at each level, and what each stage did night by night (pipeline/stages.py). */
  pipeline?: { levels: PipelineLevel[]; nights: PipelineNight[] };
}

/** One source at each level: the raw store, the records read from it, those that name a car, the snapshot. */
export interface PipelineLevel {
  provider: string;
  /** Its records describe a model, trim or variant, laid over cars by model and battery: "names a car" does not apply. */
  describes_models: boolean;
  raw?: { fetches: number; responses: number; failed: number; refused: number; wayback: number; bodies: number;
          first_at: string | null; last_at: string | null } | null;
  /** Distinct record keys by kind (offer, used, spec, ...), and how many were first seen on a live page. */
  records?: Record<string, { keys: number; first_seen_live: number }> | null;
  /** By kind (offers, specs, used): how many there are, how many name a car, how many the rules refused to guess. */
  matched?: Record<string, { total: number; matched: number; conflict: number }> | null;
  /** What this snapshot carries from it: offers, used listings on sale, spec rows. */
  in_snapshot: Record<string, number>;
}

/** One source's scrape on one night (its capabilities' runs added together). */
export interface PipelineScrape {
  source: string;
  capabilities: string[];
  runs: number;
  started_at: string | null;
  finished_at: string | null;
  /** The night's worst: error, refused, ok; null when only the index saw it fetch. */
  status: string | null;
  /** Pages asked for (a fetch that combines several pages counts once). */
  fetches: number;
  records: number;
  errors: number;
  /** Guessed pages the site does not have (404). */
  skipped: number;
  /** Not asked: the site refused twice in a row. */
  deferred: number;
  /** Every response kept, the parts of a combined fetch included; failed and refused (429, 403) among them. */
  responses: number;
  failed: number;
  refused: number;
  /** host → [pages allowed tonight, the usual number]: 0 is resting after refusals. */
  allowance: Record<string, [number, number]> | null;
}

export interface PipelineBuild {
  mode: string;
  started_at: string;
  finished_at: string;
  seconds: number;
  commit: string | null;
  fetches: number;
  parsed: number;
  from_cache: number;
  records: number;
  sightings: number;
  record_spans: number;
  /** Stored pages the parsers could not read. */
  unparsed: number;
  snapshot: Record<string, number>;
  /** The build that made this snapshot. */
  this?: boolean;
}

export interface PipelineNight {
  /** The date twelve hours before: the evening's runs and the 03:17 run after them share it. */
  night: string;
  scrapes: PipelineScrape[];
  builds: PipelineBuild[];
  /** The snapshot's commits that night, each a deploy of the site. */
  publishes: { sha: string; at: string; subject: string }[];
}

/** The default settings (data/seed/requirements.json), and the reader's own copy of them in the browser. */
export interface Requirements {
  as_of: string;
  quoting_basis?: Record<string, unknown>;
  /** The reader's budget line; the defaults set none. */
  budget?: Record<string, unknown>;
  [k: string]: unknown;
}


/** standard = fitted; pack = available through a named pack (packs_required says which, pack_prices_gbp what it costs);
 * option = available on its own; listed = standard or an option, the source does not say which (EV Database's index);
 * none = not available; null / absent = no source says. */
export type FlagState = "standard" | "pack" | "option" | "listed" | "none" | null;

/** One scraped variant: a Carwow CAP derivative or a Kia grade × powertrain (× seats). */
export interface SnapshotSpec {
  spec_key: string;
  provider: string;
  source: string;
  source_url: string;
  observed_at: string;
  make: string;
  model: string;
  model_slug: string;
  trim: string;
  variant: string;
  engine?: string;
  powertrain?: string;
  cap_id?: string;
  version_date?: string;
  model_year_hint?: string;
  seats?: number | null;
  car_id: string | null;
  rrp?: number | null;
  carwow_price?: number | null;
  image_url?: string | null;
  description?: string | null;
  features: string[];
  options: string[];
  flags: Record<string, FlagState>;
  numbers: Record<string, number | string | null>;
  first_seen_at: string;
  last_seen_at: string;
  changed_at: string | null;
}

export interface CarSpecSummary {
  spec_key: string;
  provider: string;
  variant: string | null;
  flags: Record<string, FlagState> | null;
  features: number;
  options: number;
  numbers: Record<string, number | string | null> | null;
  last_seen_at: string | null;
}

/** models.json: the catalogue of every electric model Carwow lists. */
export interface SnapshotModel {
  slug: string;
  make: string;
  model: string;
  make_name: string | null;
  model_name: string | null;
  has_deals: boolean;
  has_specs: boolean;
  first_seen_at: string;
  last_seen_at: string;
  derivatives: number;
  cars: number;
  priced: number;
  used?: number;
}
