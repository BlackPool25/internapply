export type ApplicationStage =
  | "discovered"
  | "reviewing"
  | "applied"
  | "interviewing"
  | "offer"
  | "rejected"
  | "ongoing"
  | "closed"
  | "cancelled";

export type SourceType = "internship" | "freelance";

export interface Opportunity {
  id: string;
  canonical_id?: string;
  jd_hash?: string;
  company: string;
  companyLogo?: string;
  role: string;
  source: string;
  source_type: SourceType;
  tier: string;
  status: ApplicationStage | string;
  stage: ApplicationStage | string;
  contactName?: string;
  contactEmail?: string;
  matchScore: number;
  verifier_score?: number | null;
  date: string;
  created_at?: string;
  location: string;
  salary?: string;
  stipend_min?: number | null;
  stipend_max?: number | null;
  stipend_raw?: string | null;
  is_paid?: boolean;
  is_remote?: boolean;
  jobUrl?: string;
  notes?: string;
  skills?: string[];
  companyDescription?: string;
  companySize?: string;
  industry?: string;
  researchSummary?: string;
  coverEmail?: {
    id?: string;
    subject?: string;
    body: string;
    status?: string;
  };
}

export interface Activity {
  id: string;
  type: string;
  stage?: string;
  message: string;
  source?: string;
  timestamp: string;
  opportunityId: string;
}

export interface DashboardStats {
  total_opportunities: number;
  total_companies: number;
  pending_review: number;
  batch_ready: number;
  total_internships?: number;
  total_freelance?: number;
  by_stage?: {
    discovered: number;
    reviewing: number;
    applied: number;
    interviewing: number;
    offer: number;
    rejected: number;
    [key: string]: number;
  };
  by_source_tier?: {
    "Tier 0 (ATS)": number;
    "Tier 1 (Portals)": number;
    "Tier 2 (Aggregators)": number;
    "Tier 3 (APIs & RSS)": number;
    [key: string]: number;
  };
  by_source?: Record<string, number>;
}

export interface Company {
  id: string;
  name: string;
  domain?: string | null;
  description?: string | null;
  tech_stack?: string[] | null;
  funding_stage?: string | null;
  funding_total?: string | null;
  recent_news?: Array<{ title?: string; url?: string; date?: string }> | null;
  culture_data?: Record<string, unknown> | null;
  research_notes?: string | null;
  source?: string;
  created_at?: string;
}

export interface VerifierReport {
  passed: boolean;
  score: number;
  violations: Array<string | { check: string; detail: string }>;
  warnings: Array<string | { check: string; detail: string }>;
}
