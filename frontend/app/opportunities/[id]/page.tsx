"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  Building2,
  MapPin,
  DollarSign,
  Globe,
  Users,
  FileText,
  Mail,
  ExternalLink,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  Copy,
  Check,
  ShieldCheck,
  Layers,
  Calendar,
} from "lucide-react";
import { AppLayout } from "@/components/AppLayout";
import {
  useOpportunity,
  useUpdateOpportunityStage,
  useTailorResume,
  useCoverLetter,
} from "@/lib/api";

const STAGE_CONFIG: Record<string, { label: string; tint: string; text: string; bg: string }> = {
  discovered: { label: "Discovered", tint: "#F4F4F5", text: "#52525B", bg: "#7A7A82" },
  reviewing: { label: "Reviewing", tint: "#F3EFFF", text: "#7C5CFC", bg: "#7C5CFC" },
  applied: { label: "Applied", tint: "#FFF8E6", text: "#B45309", bg: "#FFC94A" },
  interviewing: { label: "Interviewing", tint: "#EFF4FE", text: "#2563EB", bg: "#5B8DEF" },
  offer: { label: "Offer", tint: "#EAF9F5", text: "#059669", bg: "#2BC7A0" },
  rejected: { label: "Rejected", tint: "#FFF0EE", text: "#DC2626", bg: "#FF6B57" },
};

export default function OpportunityDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const { data: opportunity, isLoading, error } = useOpportunity(id);
  const updateStageMutation = useUpdateOpportunityStage();

  // Outreach generation state
  const tailorMutation = useTailorResume();
  const coverLetterMutation = useCoverLetter();
  const [tailoredData, setTailoredData] = useState<any>(null);
  const [coverLetter, setCoverLetter] = useState<string>("");
  const [copied, setCopied] = useState(false);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  const handleStageChange = async (newStage: string) => {
    try {
      await updateStageMutation.mutateAsync({ id, stage: newStage });
      setActionSuccess(`Stage updated to ${newStage}`);
      setTimeout(() => setActionSuccess(null), 3000);
    } catch {
      // handled
    }
  };

  const handleGenerateTailoredOutreach = async () => {
    if (!opportunity) return;
    try {
      const tailorRes = await tailorMutation.mutateAsync({
        job_title: opportunity.role,
        company: opportunity.company,
        job_description: opportunity.companyDescription || opportunity.researchSummary || opportunity.notes || opportunity.role,
      });
      setTailoredData(tailorRes);

      const clRes = await coverLetterMutation.mutateAsync({
        title: opportunity.role,
        company: opportunity.company,
        jd_summary: opportunity.companyDescription || opportunity.role,
        top_skills: tailorRes.skills_reordered || [],
        summary: tailorRes.summary || "",
        name: opportunity.contactName || "Hiring Team",
      });
      setCoverLetter(clRes.letter);
      setActionSuccess("Tailored resume & cover letter generated!");
      setTimeout(() => setActionSuccess(null), 3000);
    } catch (err) {
      console.error(err);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (isLoading) {
    return (
      <AppLayout>
        <div className="py-24 text-center">
          <div className="w-8 h-8 border-3 border-[#7C5CFC] border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-xs text-[#7A7A82] font-mono">Loading opportunity details...</p>
        </div>
      </AppLayout>
    );
  }

  if (error || !opportunity) {
    return (
      <AppLayout>
        <div className="max-w-xl mx-auto py-16 text-center">
          <div className="eonix-card">
            <AlertCircle size={32} className="text-red-500 mx-auto mb-3" />
            <h2 className="font-display font-bold text-lg text-[#17171A]">
              Opportunity Not Found
            </h2>
            <p className="text-xs text-[#7A7A82] mt-1 mb-6">
              The opportunity with ID #{id} could not be retrieved from the database.
            </p>
            <Link
              href="/internships"
              className="inline-flex items-center gap-2 px-4 py-2 bg-[#17171A] text-white rounded-full text-xs font-semibold"
            >
              <ArrowLeft size={14} />
              <span>Back to Pipeline</span>
            </Link>
          </div>
        </div>
      </AppLayout>
    );
  }

  const currentStage = (opportunity.stage || opportunity.status || "discovered").toLowerCase();
  const stageConf = STAGE_CONFIG[currentStage] || STAGE_CONFIG.discovered;

  return (
    <AppLayout>
      <div className="space-y-6 pb-12">
        {/* Toast */}
        {actionSuccess && (
          <div className="fixed bottom-6 right-6 z-50 bg-[#17171A] text-white px-4 py-2.5 rounded-full text-xs font-semibold shadow-2xl flex items-center gap-2 border border-white/10 animate-bounce">
            <CheckCircle2 size={14} className="text-[#2BC7A0]" />
            <span>{actionSuccess}</span>
          </div>
        )}

        {/* Back navigation */}
        <div className="flex items-center justify-between">
          <Link
            href="/internships"
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#7A7A82] hover:text-[#17171A] transition-colors"
          >
            <ArrowLeft size={14} />
            <span>Back to Opportunities</span>
          </Link>

          <div className="flex items-center gap-2 font-mono text-xs text-[#7A7A82]">
            <span>ID:</span>
            <span className="bg-white px-2 py-0.5 rounded-md border border-[#EBEAE6]">
              {opportunity.canonical_id ? opportunity.canonical_id.slice(0, 10) : `#${opportunity.id}`}
            </span>
          </div>
        </div>

        {/* Hero Card */}
        <div className="eonix-card relative">
          <div className="eonix-floating-pill text-[#17171A] border border-[#EBEAE6]">
            <span
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: stageConf.bg }}
            />
            <span className="capitalize">{stageConf.label}</span>
          </div>

          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6">
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <div className="w-12 h-12 rounded-2xl bg-[#17171A] text-white flex items-center justify-center font-display font-bold text-xl shadow-md">
                  {opportunity.company.slice(0, 1).toUpperCase()}
                </div>
                <div>
                  <h2 className="font-display font-bold text-xs uppercase tracking-wider text-[#7A7A82]">
                    {opportunity.company}
                  </h2>
                  <h1 className="font-display font-bold text-xl sm:text-2xl text-[#17171A] tracking-tight">
                    {opportunity.role}
                  </h1>
                </div>
              </div>

              {/* Meta Pills */}
              <div className="flex flex-wrap items-center gap-2 pt-1">
                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#F4F4F5] text-xs font-medium text-[#17171A]">
                  <MapPin size={12} className="text-[#7A7A82]" />
                  <span>{opportunity.location || "Remote"}</span>
                </span>

                {opportunity.salary && (
                  <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#F4F4F5] text-xs font-mono font-semibold text-[#17171A]">
                    <DollarSign size={12} className="text-[#2BC7A0]" />
                    <span>{opportunity.salary}</span>
                  </span>
                )}

                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-white border border-[#EBEAE6] text-xs font-medium text-[#17171A]">
                  <Layers size={12} className="text-[#7C5CFC]" />
                  <span className="capitalize">{opportunity.source || "Web"}</span>
                  <span className="text-[#7A7A82] text-[10px]">({opportunity.tier})</span>
                </span>
              </div>
            </div>

            {/* Stage Action Cluster */}
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2.5">
              {opportunity.jobUrl && (
                <a
                  href={opportunity.jobUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center justify-center gap-1.5 px-4 py-2.5 bg-white rounded-full text-xs font-semibold text-[#17171A] border border-[#EBEAE6] hover:bg-[#F5F4F0] shadow-xs transition-colors"
                >
                  <ExternalLink size={13} />
                  <span>Source URL</span>
                </a>
              )}

              <button
                onClick={handleGenerateTailoredOutreach}
                disabled={tailorMutation.isPending || coverLetterMutation.isPending}
                className="inline-flex items-center justify-center gap-2 px-5 py-2.5 bg-[#7C5CFC] text-white rounded-full text-xs font-semibold shadow-md hover:bg-[#6847E8] transition-colors disabled:opacity-60"
              >
                {tailorMutation.isPending || coverLetterMutation.isPending ? (
                  <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                ) : (
                  <Sparkles size={14} />
                )}
                <span>Tailor Resume & Outreach</span>
              </button>
            </div>
          </div>

          {/* Quick Stage Progression Row */}
          <div className="mt-6 pt-5 border-t border-[#F0EFEC] flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-[#7A7A82] mr-1">Move to:</span>
            {Object.keys(STAGE_CONFIG).map((stg) => {
              const conf = STAGE_CONFIG[stg];
              const isSelected = currentStage === stg;
              return (
                <button
                  key={stg}
                  onClick={() => handleStageChange(stg)}
                  className={`px-3 py-1 rounded-full text-xs font-semibold transition-all ${
                    isSelected
                      ? "bg-[#17171A] text-white shadow-xs"
                      : "bg-[#F4F4F5] text-[#7A7A82] hover:text-[#17171A] hover:bg-[#EAE9E5]"
                  }`}
                >
                  {conf.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* 2-Column Content Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left Column: Job Description & Skills (2 Cols) */}
          <div className="lg:col-span-2 space-y-6">
            {/* Job Description Card */}
            <div className="eonix-card">
              <h3 className="font-display font-semibold text-base text-[#17171A] mb-3">
                Job Overview & Details
              </h3>
              <div className="prose prose-sm text-xs text-[#52525B] max-w-none whitespace-pre-line leading-relaxed max-h-[420px] overflow-y-auto pr-2">
                {opportunity.companyDescription ||
                  opportunity.researchSummary ||
                  "No detailed job description captured for this opportunity."}
              </div>

              {/* Skills Tags */}
              {opportunity.skills && opportunity.skills.length > 0 && (
                <div className="mt-6 pt-4 border-t border-[#F0EFEC]">
                  <h4 className="text-xs font-semibold text-[#7A7A82] mb-2 uppercase tracking-wider">
                    Extracted Skills
                  </h4>
                  <div className="flex flex-wrap gap-1.5">
                    {opportunity.skills.map((skill, i) => (
                      <span
                        key={i}
                        className="px-2.5 py-1 rounded-full bg-[#F4F4F5] text-xs font-medium text-[#17171A]"
                      >
                        {skill}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Generated Outreach / Tailored View */}
            {(tailoredData || coverLetter) && (
              <div className="eonix-card relative border-2 border-[#7C5CFC]/20">
                <div className="eonix-floating-pill text-[#7C5CFC] border border-[#EBEAE6]">
                  <Sparkles size={13} />
                  <span>AI Generated Materials</span>
                </div>

                <div className="space-y-4">
                  {tailoredData && (
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <h4 className="font-display font-semibold text-sm text-[#17171A]">
                          Tailored Executive Summary
                        </h4>
                        {tailoredData.verifier_score && (
                          <span className="font-mono text-xs font-bold text-[#059669] bg-[#EAF9F5] px-2.5 py-0.5 rounded-full flex items-center gap-1">
                            <ShieldCheck size={12} />
                            <span>Score: {tailoredData.verifier_score}%</span>
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-[#52525B] bg-[#FBFBFA] p-3.5 rounded-2xl border border-[#EBEAE6] leading-relaxed">
                        {tailoredData.summary}
                      </p>
                    </div>
                  )}

                  {coverLetter && (
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <h4 className="font-display font-semibold text-sm text-[#17171A]">
                          Cold Outreach Letter
                        </h4>
                        <button
                          onClick={() => copyToClipboard(coverLetter)}
                          className="inline-flex items-center gap-1 text-xs font-semibold text-[#7C5CFC] hover:underline"
                        >
                          {copied ? <Check size={12} /> : <Copy size={12} />}
                          <span>{copied ? "Copied!" : "Copy Letter"}</span>
                        </button>
                      </div>
                      <pre className="text-xs text-[#17171A] bg-[#FBFBFA] p-4 rounded-2xl border border-[#EBEAE6] font-mono whitespace-pre-wrap leading-relaxed max-h-72 overflow-y-auto">
                        {coverLetter}
                      </pre>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Right Column: Company & Research Dossier (1 Col) */}
          <div className="space-y-6">
            <div className="eonix-card">
              <h3 className="font-display font-semibold text-base text-[#17171A] mb-3">
                Organization Dossier
              </h3>
              <div className="space-y-3 text-xs">
                <div>
                  <span className="text-[#7A7A82] block text-[11px]">Company Name</span>
                  <span className="font-semibold text-[#17171A]">{opportunity.company}</span>
                </div>
                <div>
                  <span className="text-[#7A7A82] block text-[11px]">Discovery Source</span>
                  <span className="font-mono font-medium text-[#17171A] capitalize">
                    {opportunity.source || "ATS Scraper"}
                  </span>
                </div>
                <div>
                  <span className="text-[#7A7A82] block text-[11px]">First Seen</span>
                  <span className="font-mono text-[#17171A]">
                    {opportunity.date || "Today"}
                  </span>
                </div>
              </div>

              <div className="mt-5 pt-4 border-t border-[#F0EFEC]">
                <Link
                  href="/companies"
                  className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 bg-[#F4F4F5] hover:bg-[#EAE9E5] text-[#17171A] rounded-full text-xs font-semibold transition-colors"
                >
                  <Building2 size={13} />
                  <span>View All Companies</span>
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
