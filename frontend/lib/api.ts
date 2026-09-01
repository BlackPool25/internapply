"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import type { Opportunity, Activity, DashboardStats, Company, FreelanceOpportunity } from "./types";

// ── API base ───────────────────────────────────────────

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

async function apiFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
    ...options,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`API ${res.status}: ${err}`);
  }
  return res.json() as Promise<T>;
}

// ── Helpers ────────────────────────────────────────────

export function buildOpportunitiesQuery(params: Record<string, string | string[] | number | boolean | null | undefined>) {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v === null || v === undefined || v === "") return;
    if (Array.isArray(v)) {
      if (v.length === 0) return;
      sp.set(k, v.join(","));
    } else {
      sp.set(k, String(v));
    }
  });
  const qs = sp.toString();
  return qs ? `/opportunities?${qs}` : "/opportunities";
}

// ── Resume API hooks ───────────────────────────────────

export function useMasterResume() {
  return useQuery<Record<string, unknown>>({
    queryKey: ["resume", "master"],
    queryFn: () => apiFetch<Record<string, unknown>>("/resume/master"),
    retry: 1,
    staleTime: 30_000,
  });
}

export function useUpdateMasterResume() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (resume: Record<string, unknown>) =>
      apiFetch<{ status: string; path: string }>("/resume/master", {
        method: "PUT",
        body: JSON.stringify({ resume }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["resume", "master"] });
    },
  });
}

// verifier gate: WARN 70-79 yellow, success >=80 green, error <70 red but not blocked except <60
export type TailorResult = {
  summary: string;
  skills_reordered: string[];
  projects: Record<string, unknown>[];
  education: Record<string, unknown>[];
  verifier_score: number | null;
  warn?: boolean;
  status?: "ok" | "warn" | "error";
};

export function useTailorResume() {
  return useMutation({
    mutationFn: (data: {
      job_title: string;
      company: string;
      job_description: string;
      canonical_id?: string;
    }) =>
      apiFetch<TailorResult>("/resume/tailor", {
        method: "POST",
        body: JSON.stringify(data),
      }),
  });
}

export function getVerifierState(score: number | null | undefined): "success" | "warn" | "error" {
  if (score == null) return "error";
  if (score >= 80) return "success";
  if (score >= 70) return "warn";
  return "error";
}

export function useCoverLetter() {
  return useMutation({
    mutationFn: (data: {
      title: string;
      company: string;
      jd_summary: string;
      top_skills: string[];
      summary: string;
      name?: string;
    }) =>
      apiFetch<{ letter: string; humanization_score: number }>(
        "/resume/cover-letter",
        { method: "POST", body: JSON.stringify(data) },
      ),
  });
}

// ── Opportunities ──────────────────────────────────────

export type OpportunityFilters = {
  tier?: string | null;
  source?: string[] | null;
  location?: string | null;
  stipend_gte?: number | null;
  remote?: boolean | null;
  posted_within?: string | null;
  verifier_gte?: number | null;
  q?: string | null;
  page?: number | null;
};

export function useOpportunities(filters?: OpportunityFilters) {
  const hasFilters = filters && Object.values(filters).some((v) => v != null && v !== "" && !(Array.isArray(v) && v.length === 0));
  const queryKey = hasFilters ? ["opportunities", filters] as const : (["opportunities"] as const);
  const path = hasFilters
    ? buildOpportunitiesQuery({
        tier: filters?.tier ?? undefined,
        source: filters?.source?.join(",") ?? undefined,
        location: filters?.location ?? undefined,
        stipend_gte: filters?.stipend_gte ?? undefined,
        remote: filters?.remote ?? undefined,
        posted_within: filters?.posted_within ?? undefined,
        verifier_gte: filters?.verifier_gte ?? undefined,
        q: filters?.q ?? undefined,
        page: filters?.page ?? undefined,
      })
    : "/opportunities";

  return useQuery<Opportunity[]>({
    queryKey,
    queryFn: () => apiFetch<Opportunity[]>(path),
    staleTime: 60_000,
  });
}

export function useOpportunity(id: string) {
  return useQuery<Opportunity | undefined>({
    queryKey: ["opportunities", id],
    queryFn: () => apiFetch<Opportunity>(`/opportunities/${id}`),
    enabled: !!id,
    staleTime: 60_000,
  });
}

// ── Dashboard ──────────────────────────────────────────

export function useDashboardStats() {
  return useQuery<DashboardStats>({
    queryKey: ["dashboard", "stats"],
    queryFn: () => apiFetch<DashboardStats>("/dashboard/stats"),
    staleTime: 60_000,
  });
}

export function useRecentActivity() {
  return useQuery<Activity[]>({
    queryKey: ["dashboard", "activity"],
    queryFn: () => apiFetch<Activity[]>("/dashboard/activity"),
    staleTime: 60_000,
  });
}

export function useFreelanceFeed() {
  return useQuery<FreelanceOpportunity[]>({
    queryKey: ["freelance"],
    queryFn: () => apiFetch<FreelanceOpportunity[]>("/freelance"),
    staleTime: 60_000,
  });
}

// ── Companies ──────────────────────────────────────────

export function useCompanies() {
  return useQuery<Company[]>({
    queryKey: ["companies"],
    queryFn: () => apiFetch<Company[]>("/companies"),
    staleTime: 60_000,
  });
}

export function useCompany(id: string) {
  return useQuery<Company | undefined>({
    queryKey: ["companies", id],
    queryFn: () => apiFetch<Company>(`/companies/${id}`),
    enabled: !!id,
    staleTime: 60_000,
  });
}

// ── Pipeline ───────────────────────────────────────────

export function usePipelineRun() {
  return useMutation({
    mutationFn: (dryRun: boolean) =>
      apiFetch<{ status: string; items: number }>("/pipeline/run", {
        method: "POST",
        body: JSON.stringify({ dry_run: dryRun }),
      }),
  });
}

export function usePipelineClear() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ status: string; tables: number }>("/pipeline/clear", {
        method: "POST",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      queryClient.invalidateQueries({ queryKey: ["companies"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function usePipelineRerun() {
  return useMutation({
    mutationFn: () =>
      apiFetch<{ status: string; items_rerun: number; stage: string }>("/pipeline/rerun", {
        method: "POST",
      }),
  });
}
