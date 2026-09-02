"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import type {
  Opportunity,
  Activity,
  DashboardStats,
  Company,
  VerifierReport,
  PipelineStatusResponse,
  PipelineConfig,
} from "./types";

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

// ── Opportunities ──────────────────────────────────────

export interface OpportunityQueryParams {
  source_type?: "internship" | "freelance" | string | null;
  stage?: string | null;
  company_id?: number | string | null;
  search?: string | null;
  limit?: number | null;
}

export function buildOpportunitiesQuery(params: OpportunityQueryParams) {
  const sp = new URLSearchParams();
  if (params.source_type) sp.set("source_type", params.source_type);
  if (params.stage) sp.set("stage", params.stage);
  if (params.company_id) sp.set("company_id", String(params.company_id));
  if (params.search) sp.set("search", params.search);
  if (params.limit) sp.set("limit", String(params.limit));
  const qs = sp.toString();
  return qs ? `/opportunities?${qs}` : "/opportunities";
}

export function useOpportunities(filters?: OpportunityQueryParams) {
  const path = filters ? buildOpportunitiesQuery(filters) : "/opportunities";
  const queryKey = ["opportunities", filters ?? {}];

  return useQuery<Opportunity[]>({
    queryKey,
    queryFn: () => apiFetch<Opportunity[]>(path),
    staleTime: 30_000,
  });
}

export function useOpportunity(id: string) {
  return useQuery<Opportunity | undefined>({
    queryKey: ["opportunities", id],
    queryFn: () => apiFetch<Opportunity>(`/opportunities/${id}`),
    enabled: !!id,
    staleTime: 30_000,
  });
}

export function useUpdateOpportunityStage() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, stage }: { id: string; stage: string }) => {
      return apiFetch<Opportunity>(`/opportunities/${id}/stage`, {
        method: "PATCH",
        body: JSON.stringify({ stage }),
      });
    },
    onMutate: async ({ id, stage }) => {
      await queryClient.cancelQueries({ queryKey: ["opportunities"] });

      // Snapshot all matching cache queries
      const queryCache = queryClient.getQueryCache();
      const oppQueries = queryCache.findAll({ queryKey: ["opportunities"] });
      const previousSnapshots = oppQueries.map((q) => ({
        queryKey: q.queryKey,
        data: q.state.data as Opportunity[] | undefined,
      }));

      // Optimistically update every active opportunities query list
      oppQueries.forEach((q) => {
        const data = q.state.data as Opportunity[] | undefined;
        if (Array.isArray(data)) {
          queryClient.setQueryData(
            q.queryKey,
            data.map((opp) =>
              opp.id === id ? { ...opp, stage, status: stage } : opp
            )
          );
        }
      });

      return { previousSnapshots };
    },
    onError: (err, newStage, context) => {
      if (context?.previousSnapshots) {
        context.previousSnapshots.forEach(({ queryKey, data }) => {
          queryClient.setQueryData(queryKey, data);
        });
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard", "stats"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard", "activity"] });
    },
  });
}

// ── Dashboard ──────────────────────────────────────────

export function useDashboardStats() {
  return useQuery<DashboardStats>({
    queryKey: ["dashboard", "stats"],
    queryFn: () => apiFetch<DashboardStats>("/dashboard/stats"),
    staleTime: 30_000,
  });
}

export function useRecentActivity() {
  return useQuery<Activity[]>({
    queryKey: ["dashboard", "activity"],
    queryFn: () => apiFetch<Activity[]>("/dashboard/activity"),
    staleTime: 30_000,
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

// ── Resume ─────────────────────────────────────────────

export function useMasterResume() {
  return useQuery<Record<string, unknown>>({
    queryKey: ["resume", "master"],
    queryFn: () => apiFetch<Record<string, unknown>>("/resume/master"),
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

export interface TailorResponse {
  summary: string;
  skills_reordered: string[];
  projects: Array<Record<string, unknown>>;
  education: Array<Record<string, unknown>>;
  verifier_score?: number | null;
}

export function useTailorResume() {
  return useMutation({
    mutationFn: (data: {
      job_title: string;
      company: string;
      job_description: string;
      jd_analysis?: Record<string, unknown>;
    }) =>
      apiFetch<TailorResponse>("/resume/tailor", {
        method: "POST",
        body: JSON.stringify(data),
      }),
  });
}

export function useVerifyResume() {
  return useMutation({
    mutationFn: (data: {
      tailored_resume: Record<string, unknown>;
      source_resume?: Record<string, unknown>;
    }) =>
      apiFetch<VerifierReport>("/resume/verify", {
        method: "POST",
        body: JSON.stringify(data),
      }),
  });
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
        { method: "POST", body: JSON.stringify(data) }
      ),
  });
}

export function useQualityCheck() {
  return useMutation({
    mutationFn: (data: { tailored_resume: Record<string, unknown> }) =>
      apiFetch<{ score: number; issues: string[]; passed: boolean }>(
        "/resume/quality-check",
        { method: "POST", body: JSON.stringify(data) }
      ),
  });
}

// ── Pipeline ───────────────────────────────────────────

export function usePipelineStatus() {
  return useQuery<PipelineStatusResponse>({
    queryKey: ["pipeline", "status"],
    queryFn: () => apiFetch<PipelineStatusResponse>("/pipeline/status"),
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.status === "running" ? 1000 : 4000;
    },
    staleTime: 500,
  });
}

export function usePipelineRunConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (config: PipelineConfig) =>
      apiFetch<{ status: string; run_id: string; message: string; config?: Record<string, unknown> }>(
        "/pipeline/run",
        {
          method: "POST",
          body: JSON.stringify(config),
        }
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline", "status"] });
      queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      queryClient.invalidateQueries({ queryKey: ["companies"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function usePipelineStop() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ status: string; message: string }>("/pipeline/stop", {
        method: "POST",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline", "status"] });
    },
  });
}

export function usePipelineRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (dryRun: boolean = true) =>
      apiFetch<{ status: string; run_id?: string; stage?: string; jobs_found?: number; companies_found?: number; errors?: number }>(
        "/pipeline/run",
        {
          method: "POST",
          body: JSON.stringify({ dry_run: dryRun }),
        }
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline", "status"] });
      queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      queryClient.invalidateQueries({ queryKey: ["companies"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
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
      queryClient.invalidateQueries({ queryKey: ["pipeline", "status"] });
      queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      queryClient.invalidateQueries({ queryKey: ["companies"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function usePipelineRerun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ status: string; items_rerun: number; stage?: string; run_id?: string }>(
        "/pipeline/rerun",
        {
          method: "POST",
        }
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline", "status"] });
      queryClient.invalidateQueries({ queryKey: ["opportunities"] });
      queryClient.invalidateQueries({ queryKey: ["companies"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}
