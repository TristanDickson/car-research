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
export type Tri = "standard" | "pack" | "option" | "none" | "unknown";

export interface RequirementCheck {
  passes: boolean;
  failures: string[];
  unknown: string[];
}

export interface DealSummary {
  deals: number;
  active_deals: number;
  best_cash_price: number | null;
  best_cash_deal_id: string | null;
  best_pcp_monthly: number | null;
  best_pcp_deal_id: string | null;
  best_pch_effective_monthly: number | null;
  best_pch_deal_id: string | null;
}

export interface SnapshotCar {
  id: string;
  make: string;
  model: string;
  trim: string;
  packs?: string[];
  model_year?: number | null;
  used?: boolean;
  fuel?: string;
  body?: string;
  seats?: number | null;
  battery_kwh?: number | null;
  wltp_range_mi?: number | null;
  real_range_mi?: number | null;
  power_hp?: number | null;
  architecture_v?: number | null;
  dc_peak_kw?: number | null;
  dc_10_80_min?: number | null;
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
  packs_required?: Record<string, string>;
  pack_prices_gbp?: Record<string, number>;
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
  notes?: string;
  verification?: string;
  requirement_check: RequirementCheck;
  deal_summary: DealSummary;
}

export type FinanceType = "pcp" | "pch" | "cash" | "campaign";

export interface DealMetrics {
  skipped?: string;
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

export interface SnapshotDeal {
  id: string;
  car_id: string;
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
  metrics: DealMetrics;
}

export interface RequirementRule {
  id: string;
  label: string;
  field?: string;
  op?: string;
  value?: unknown;
  weight?: number;
  direction?: string;
  applies_to?: string;
  [k: string]: unknown;
}

export interface Requirements {
  as_of: string;
  household?: Record<string, unknown>;
  quoting_basis?: Record<string, unknown>;
  budget?: Record<string, unknown>;
  hard: RequirementRule[];
  preferences: RequirementRule[];
  wants: RequirementRule[];
  finance_posture?: Record<string, unknown>;
  context?: Record<string, unknown>;
  [k: string]: unknown;
}
