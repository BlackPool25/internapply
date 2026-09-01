export type ApplicationStatus =
  | "saved"
  | "applied"
  | "pending_review"
  | "batch_ready"
  | "interview_scheduled"
  | "rejected"
  | "offer"
  | "accepted";

export type ApplicationSource =
  | "LinkedIn"
  | "Internshala"
  | "HackerNews"
  | "Seed"
  | "Company Website"
  | "Referral"
  | "Other";

// Extended source_ats values used by backend + new freelance sources
export type SourceATS =
  | "ATS"
  | "greenhouse"
  | "lever"
  | "ashby"
  | "workday"
  | "smartrecruiters"
  | "hirist"
  | "Hirist"
  | "unstop"
  | "Unstop"
  | "internshala"
  | "Internshala"
  | "jobspy"
  | "JobSpy"
  | "linkedin"
  | "LinkedIn"
  | "freelance"
  | "Freelancer"
  | "arbeitnow"
  | "Arbeitnow"
  | "internshala_freelance"
  | "upwork"
  | "Upwork"
  | "999"
  | string;

export type DriftKind = "new" | "changed" | "gone" | null;

export interface ChangeLogEntry {
  status?: DriftKind;
  kind?: DriftKind;
  changed_at?: string;
  jd_hash?: string;
  prev_hash?: string;
}

export interface Opportunity {
  id: string;
  canonical_id?: string;
  company: string;
  companyLogo?: string;
  role: string;
  title?: string;
  source: ApplicationSource | string;
  source_ats?: SourceATS;
  source_ats_label?: string;
  status: ApplicationStatus;
  contactName: string;
  contactEmail: string;
  matchScore: number; // 0-100
  verifier_score?: number | null;
  tier?: string | null;
  stipend?: number | null;
  stipend_gte?: number | null;
  remote?: boolean | null;
  location: string;
  salary?: string;
  jobUrl?: string;
  url?: string;
  notes?: string;
  posted_at?: string;
  date: string; // ISO date
  drift?: DriftKind;
  change_log?: ChangeLogEntry | Record<string, unknown> | null;
  // Detail-only fields
  companyDescription?: string;
  companySize?: string;
  industry?: string;
  researchSummary?: string;
  people?: CompanyContact[];
  resume?: ResumeVersion;
  coverEmail?: CoverEmailVersion;
}

export interface CompanyContact {
  name: string;
  role: string;
  profileUrl?: string;
}

export interface ResumeVersion {
  id: string;
  filename: string;
  content: string;
  uploadedAt: string;
}

export interface CoverEmailVersion {
  id: string;
  subject: string;
  body: string;
  status: "draft" | "approved" | "sent";
}

export interface Activity {
  id: string;
  type: "application" | "status_change" | "note" | "email";
  message: string;
  timestamp: string;
  opportunityId: string;
}

export interface DashboardStats {
  totalOpportunities: number;
  pendingReview: number;
  batchReady: number;
  emailsToSend: number;
  // extended KPIs
  newToday?: number;
  changedJds?: number;
  workingBoards?: number;
  jdHashHitPct?: number;
}

export interface FreelanceOpportunity {
  id: string;
  title: string;
  company?: string;
  source_ats: string;
  url?: string;
  location?: string;
  budget?: string;
  posted_at?: string;
  description?: string;
}

// ── Company types ──────────────────────────────────────

export type FundingStage =
  | "Bootstrapped"
  | "Pre-seed"
  | "Seed"
  | "Series A"
  | "Series B"
  | "Series C"
  | "Series D"
  | "Series E"
  | "Series F"
  | "Public";

export interface CompanyPerson {
  name: string;
  role: string;
  email?: string;
  emailStatus?: "found" | "verified" | "not_found";
  source?: string;
  profileUrl?: string;
}

export interface NewsItem {
  title: string;
  url?: string;
  date: string;
}

export interface Company {
  id: string;
  name: string;
  domain: string;
  description: string;
  techStack: string[];
  fundingStage: FundingStage;
  fundingAmount?: string;
  foundedYear?: number;
  location?: string;
  employees?: string;
  industry?: string;
  people: CompanyPerson[];
  recentNews: NewsItem[];
  researchNotes?: string;
  linkedOpportunityIds: string[];
}
