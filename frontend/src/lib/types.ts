export type Mode = "demo" | "live";

export interface AuthState {
  mode: Mode;
  live_publishing_enabled: boolean;
  needs_setup: boolean;
  authenticated: boolean;
  csrf?: string;
  user?: { id: number; name: string; email: string };
  workspace?: { id: number; name: string; timezone: string };
  role?: "owner" | "editor" | "viewer";
  invite?: { email: string; role: string };
}

export interface Brand {
  id: number;
  name: string;
  description: string;
  positioning: string;
  voice: string;
  tone: string;
  audience: string;
  location: string;
  goals: string;
  website: string;
  colors: string[];
  visual_guidelines: string;
  approved_claims: string[];
  restricted_claims: string[];
  prohibited_messaging: string[];
  constraints: string;
  permitted_sources: string[];
  logo_asset_id: number | null;
  is_synthetic: boolean;
}

export interface Persona {
  id: number;
  name: string;
  description: string;
  goals: string;
  pain_points: string;
  preferred_platforms: string[];
}

export interface Product {
  id: number;
  sku: string;
  name: string;
  category: string;
  collection: string;
  description: string;
  price: number | null;
  currency: string;
  dimensions: string;
  materials: string[];
  finishes: string[];
  verified_attributes: Record<string, string>;
  image_asset_id: number | null;
  is_active: boolean;
  is_synthetic: boolean;
}

export interface Asset {
  id: number;
  kind: string;
  source: string;
  filename: string;
  content_type: string;
  width: number | null;
  height: number | null;
  alt_text: string;
  url: string;
  placeholder: boolean;
  is_synthetic: boolean;
}

export interface Finding {
  id: number;
  topic: string;
  statement: string;
  classification: "verified_observation" | "source_reported" | "inference" | "hypothesis" | "unknown";
  source_type: string;
  source_url: string | null;
  source_title: string;
  evidence_excerpt: string;
  retrieved_at: string;
  is_synthetic: boolean;
  run_id: string | null;
}

export interface Observation {
  id: number;
  competitor_id: number;
  source_type: string;
  source_url: string | null;
  content_format: string;
  theme: string;
  excerpt: string;
  cta: string;
  product_categories: string[];
  visible_engagement: Record<string, number> | null;
  is_synthetic: boolean;
  observed_at: string;
  published_at: string | null;
}

export interface Competitor {
  id: number;
  name: string;
  website: string;
  instagram_url: string;
  notes: string;
  is_synthetic: boolean;
  observation_count: number;
  observations?: Observation[];
}

export interface Check {
  code: string;
  status: "pass" | "warn" | "fail";
  message: string;
  claim: string;
  evidence: string;
}

export interface Validation {
  version: number;
  checked_at: string;
  ok: boolean;
  failures: number;
  warnings: number;
  product_claims: Check[];
  brand: Check[];
  platform: Check[];
}

export interface Revision {
  version: number;
  source: string;
  note: string;
  snapshot: Record<string, unknown>;
  edited_by: number | null;
  created_at: string;
}

export interface Attempt {
  id: number;
  adapter: string;
  live: boolean;
  success: boolean;
  external_id: string | null;
  provider_status: string;
  summary: string;
  error: string | null;
  attempted_at: string;
}

export interface Metric {
  id: number;
  reach: number | null;
  views: number | null;
  likes: number | null;
  comments: number | null;
  shares: number | null;
  saves: number | null;
  source: string;
  captured_at: string;
}

export type ContentStatus =
  | "draft"
  | "in_review"
  | "changes_requested"
  | "approved"
  | "scheduled"
  | "publishing"
  | "published"
  | "failed"
  | "cancelled";

export interface ContentItem {
  id: number;
  campaign_id: number | null;
  campaign_name: string | null;
  experiment_id: number | null;
  variant_label: string;
  run_id: string | null;
  platform: string;
  content_type: string;
  pillar: string;
  title: string;
  hook: string;
  caption: string;
  hashtags: string[];
  cta: string;
  image_brief: string;
  carousel_outline: string[];
  video_script: string;
  product_ids: number[];
  asset_id: number | null;
  slide_asset_ids: number[];
  validation: Validation | null;
  validation_current: boolean;
  status: ContentStatus;
  connection_id: number | null;
  connection_name: string | null;
  connection_adapter: string | null;
  connection_live: boolean;
  generated_by: string;
  rationale: string;
  version: number;
  approved_version: number | null;
  approved_by: number | null;
  publish_authorized: boolean;
  review_note: string;
  external_id: string | null;
  external_url: string | null;
  publish_verified: boolean;
  last_error: string | null;
  is_synthetic: boolean;
  planned_at: string | null;
  scheduled_at: string | null;
  published_at: string | null;
  planned_local: string | null;
  scheduled_local: string | null;
  updated_at: string;
  // detail-only
  revisions?: Revision[];
  attempts?: Attempt[];
  metrics?: Metric[];
  assets?: Asset[];
  products?: Product[];
  final_caption?: string;
  // approval-only
  campaign?: { id: number; name: string; objective: string; success_criteria: Criterion[] };
  hypothesis?: Hypothesis;
  evidence?: Finding[];
  target_connections?: Connection[];
}

export interface Criterion {
  metric: string;
  comparator: string;
  target: number;
  variant?: string;
  baseline?: string;
}

export interface Hypothesis {
  id: number;
  campaign_id: number | null;
  statement: string;
  mechanism: string;
  evidence_ids: number[];
  uncertainty: string;
  validation_method: string;
  scores: Record<string, number>;
  total_score: number;
  rank: number;
  selected: boolean;
  status: string;
}

export interface Experiment {
  id: number;
  campaign_id: number | null;
  hypothesis_id: number | null;
  name: string;
  variants: { label: string; description: string }[];
  primary_metric: string;
  success_criteria: Criterion[];
  min_sample_per_variant: number;
  status: string;
  result: {
    per_variant?: Record<string, { n: number; mean_engagement_rate: number | null; posts: number[]; missing_metrics: number }>;
    lift?: number;
    p_value?: number;
    method?: string;
    alpha?: number;
    data_source?: string;
  } | null;
  conclusion: string;
  learnings: string;
  next_recommendation: string;
  data_source: string;
  is_synthetic: boolean;
  created_at: string;
  evaluated_at: string | null;
  hypothesis?: Hypothesis | null;
  variant_posts?: Record<string, number>;
}

export interface Recommendation {
  id: number;
  campaign_id: number | null;
  experiment_id: number | null;
  run_id: string | null;
  title: string;
  detail: string;
  rationale: string;
  evidence: { type: string; ref: string | number; summary: string }[];
  uncertainty: string;
  priority: "high" | "medium" | "low";
  status: string;
  is_synthetic: boolean;
  created_at: string;
}

export interface Campaign {
  id: number;
  brand_id: number;
  run_id: string | null;
  name: string;
  objective: string;
  audience: string;
  geography: string;
  language: string;
  platforms: string[];
  pillars: string[];
  creative_direction: string;
  ctas: string[];
  budget_note: string;
  measurement_plan: string;
  success_criteria: Criterion[];
  risks: string[];
  assumptions: string[];
  product_ids: number[];
  status: string;
  is_synthetic: boolean;
  start_date: string | null;
  end_date: string | null;
  created_at: string;
  counts?: Record<string, number>;
}

export interface Connection {
  id: number;
  adapter: string;
  platform: string;
  name: string;
  account_id: string;
  account_label: string;
  status: string;
  token_expires_at: string | null;
  last_verified_at: string | null;
  last_error: string | null;
  config: { url?: string };
  adapter_info: AdapterInfo | null;
  available_in_mode?: boolean;
}

export interface AdapterInfo {
  key: string;
  label: string;
  platform: string;
  external: boolean;
  maturity: string;
  capabilities: {
    oauth: boolean;
    identity: boolean;
    validation: boolean;
    publish: boolean;
    scheduling: string;
    status_verification: boolean;
    analytics: boolean;
    content_types: string[];
  };
}

export interface Step {
  seq: number;
  phase: "observe" | "plan" | "tool" | "evaluate" | "replan" | "decision" | "approval" | "finish" | "error";
  tool: string | null;
  message: string;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  status: "ok" | "error" | "skipped" | "blocked";
  is_mock: boolean;
  attempt: number;
  duration_ms: number;
  tokens: number;
  created_at: string;
}

export interface PlanStep {
  id: string;
  tool: string;
  purpose: string;
  status: string;
  note?: string;
  inserted?: boolean;
  after_approval?: boolean;
}

export interface Run {
  id: string;
  goal: string;
  intent: string;
  planner: string;
  status: "queued" | "running" | "awaiting_approval" | "completed" | "blocked" | "failed" | "cancelled";
  plan: PlanStep[];
  step_count: number;
  max_steps: number;
  tokens_used: number;
  token_budget: number;
  cancel_requested: boolean;
  outcome_summary: string;
  completion_reason: string;
  blockers: string[];
  error: string | null;
  campaign_id: number | null;
  brand_id: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  outputs: Record<string, unknown>;
  params: Record<string, unknown>;
  steps?: Step[];
}

export interface Group {
  key: string;
  n: number;
  mean_engagement_rate: number;
  min: number;
  max: number;
  reach: number;
  interactions: number;
}

export interface Analytics {
  data_source: "synthetic" | "real" | "mixed" | "none";
  freshness: string | null;
  published: number;
  with_metrics: number;
  missing_metrics: number;
  totals: Record<string, number | null>;
  by_content_type: Group[];
  by_pillar: Group[];
  by_platform: Group[];
  by_campaign: Group[];
  daily: { date: string; reach: number; interactions: number; posts: number }[];
  items: {
    id: number;
    title: string;
    platform: string;
    content_type: string;
    pillar: string;
    variant: string;
    published_at: string | null;
    source: string | null;
    reach: number | null;
    interactions: number | null;
    engagement_rate: number | null;
    saves: number | null;
  }[];
  definitions: Record<string, { label: string; kind: string; definition: string }>;
}

export interface ReportSummary {
  id: number;
  campaign_id: number | null;
  run_id: string | null;
  title: string;
  data_source: string;
  created_at: string;
  markdown?: string;
}
