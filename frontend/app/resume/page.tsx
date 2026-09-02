"use client";

import { useState } from "react";
import {
  FileText,
  Sparkles,
  ShieldCheck,
  Mail,
  Check,
  Save,
  RefreshCw,
  Award,
  Download,
  CheckCircle2,
  Copy,
} from "lucide-react";
import { AppLayout } from "@/components/AppLayout";
import {
  useMasterResume,
  useUpdateMasterResume,
  useTailorResume,
  useVerifyResume,
  useCoverLetter,
  useQualityCheck,
} from "@/lib/api";

type ResumeTab = "master" | "tailor" | "verify" | "cover" | "quality";

export default function ResumePage() {
  const [activeTab, setActiveTab] = useState<ResumeTab>("master");

  // Master Resume Data & Form
  const { data: masterResumeData, isLoading: masterLoading, refetch: refetchMaster } = useMasterResume();
  const updateMasterMutation = useUpdateMasterResume();
  const [editedMasterJsonText, setEditedMasterJsonText] = useState<string | null>(null);
  const masterJsonText = editedMasterJsonText ?? (masterResumeData ? JSON.stringify(masterResumeData, null, 2) : "");
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Tailoring State
  const tailorMutation = useTailorResume();
  const [jobTitle, setJobTitle] = useState("Software Engineer Intern");
  const [companyName, setCompanyName] = useState("Acme Labs");
  const [jobDescription, setJobDescription] = useState(
    "Looking for a Backend/DevOps intern with experience in Python, Docker, Kubernetes, CI/CD, and distributed systems."
  );
  const [tailorResult, setTailorResult] = useState<any>(null);

  // Verifier State
  const verifyMutation = useVerifyResume();
  const [verifyResult, setVerifyResult] = useState<any>(null);

  // Cover Letter State
  const coverLetterMutation = useCoverLetter();
  const [applicantName, setApplicantName] = useState("Candidate");
  const [coverResult, setCoverResult] = useState<{ letter: string; humanization_score: number } | null>(null);
  const [copiedCover, setCopiedCover] = useState(false);

  // Quality Check State
  const qualityMutation = useQualityCheck();
  const [qualityResult, setQualityResult] = useState<any>(null);

  // Download DOCX state
  const [downloadingDocx, setDownloadingDocx] = useState(false);

  const handleSaveMaster = async () => {
    try {
      const parsed = JSON.parse(masterJsonText);
      await updateMasterMutation.mutateAsync(parsed);
      setSaveSuccess(true);
      setEditedMasterJsonText(null);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (e) {
      alert("Invalid JSON format in Master Resume.");
    }
  };

  const handleRunTailor = async () => {
    try {
      const res = await tailorMutation.mutateAsync({
        job_title: jobTitle,
        company: companyName,
        job_description: jobDescription,
      });
      setTailorResult(res);
    } catch (e) {
      console.error(e);
    }
  };

  const handleRunVerify = async () => {
    const resumeToVerify = tailorResult || (masterResumeData ? masterResumeData : {});
    try {
      const res = await verifyMutation.mutateAsync({
        tailored_resume: resumeToVerify,
        source_resume: masterResumeData || undefined,
      });
      setVerifyResult(res);
    } catch (e) {
      console.error(e);
    }
  };

  const handleRunCover = async () => {
    try {
      const res = await coverLetterMutation.mutateAsync({
        title: jobTitle,
        company: companyName,
        jd_summary: jobDescription,
        top_skills: tailorResult?.skills_reordered || ["Python", "FastAPI", "Docker", "PostgreSQL"],
        summary: tailorResult?.summary || "Backend engineer focused on distributed systems and APIs.",
        name: applicantName,
      });
      setCoverResult(res);
    } catch (e) {
      console.error(e);
    }
  };

  const handleRunQualityCheck = async () => {
    const resumeToCheck = tailorResult || (masterResumeData ? masterResumeData : {});
    try {
      const res = await qualityMutation.mutateAsync({
        tailored_resume: resumeToCheck,
      });
      setQualityResult(res);
    } catch (e) {
      console.error(e);
    }
  };

  const handleDownloadDocx = async () => {
    if (!tailorResult && !masterResumeData) return;
    setDownloadingDocx(true);
    try {
      const res = await fetch("http://localhost:8000/api/v1/resume/render", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_data: tailorResult || masterResumeData,
          company: companyName,
          job_title: jobTitle,
          output_format: "docx",
        }),
      });
      if (!res.ok) throw new Error("Render failed");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${companyName.replace(/[^a-z0-9]/gi, "_")}_Resume.docx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e) {
      alert("Failed to render DOCX. Make sure pandoc/python-docx is available.");
    } finally {
      setDownloadingDocx(false);
    }
  };

  return (
    <AppLayout>
      <div className="space-y-6 pb-12">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="font-display font-bold text-2xl sm:text-3xl text-[#17171A] tracking-tight">
              Resume & Outreach Suite
            </h1>
            <p className="text-sm text-[#7A7A82] mt-0.5">
              Deterministic verification, ATS-tailoring, and humanized cold email generation.
            </p>
          </div>

          {/* Tab Selection Navigation */}
          <div className="flex items-center gap-1 bg-white p-1 rounded-full border border-[#EBEAE6] shadow-xs overflow-x-auto max-w-full">
            {[
              { id: "master", label: "Master Resume", icon: FileText },
              { id: "tailor", label: "Tailor Engine", icon: Sparkles },
              { id: "verify", label: "Verifier Gate", icon: ShieldCheck },
              { id: "cover", label: "Cover Letter", icon: Mail },
              { id: "quality", label: "Quality Audit", icon: Award },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as ResumeTab)}
                className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-semibold whitespace-nowrap transition-all ${
                  activeTab === tab.id
                    ? "bg-[#17171A] text-white shadow-xs"
                    : "text-[#7A7A82] hover:text-[#17171A] hover:bg-[#F5F4F0]"
                }`}
              >
                <tab.icon size={13} />
                <span>{tab.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Tab 1: Master Resume */}
        {activeTab === "master" && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 eonix-card relative">
              <div className="eonix-floating-pill text-[#17171A] border border-[#EBEAE6]">
                <FileText size={13} className="text-[#7C5CFC]" />
                <span>profile/resume.json</span>
              </div>

              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="font-display font-semibold text-base text-[#17171A]">
                    Master Resume Schema
                  </h2>
                  <p className="text-xs text-[#7A7A82]">
                    The ground truth profile used as the strict non-hallucinatory baseline.
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => refetchMaster()}
                    className="p-2 rounded-full bg-[#F4F4F5] hover:bg-[#EAE9E5] text-[#17171A] transition-colors"
                    title="Reload from disk"
                  >
                    <RefreshCw size={13} />
                  </button>
                  <button
                    onClick={handleSaveMaster}
                    disabled={updateMasterMutation.isPending}
                    className="inline-flex items-center gap-1.5 px-4 py-2 bg-[#7C5CFC] text-white rounded-full text-xs font-semibold shadow-sm hover:bg-[#6847E8] transition-colors disabled:opacity-60"
                  >
                    {saveSuccess ? <Check size={13} /> : <Save size={13} />}
                    <span>{saveSuccess ? "Saved to Disk!" : "Save Changes"}</span>
                  </button>
                </div>
              </div>

              {masterLoading ? (
                <div className="py-16 text-center text-xs font-mono text-[#7A7A82]">
                  Loading profile/resume.json...
                </div>
              ) : (
                <textarea
                  value={masterJsonText}
                  onChange={(e) => setEditedMasterJsonText(e.target.value)}
                  className="w-full h-[520px] bg-[#17171A] text-[#E4E4E7] font-mono text-xs p-4 rounded-2xl border border-white/10 focus:outline-none focus:ring-2 focus:ring-[#7C5CFC]/50 leading-relaxed resize-y"
                  spellCheck={false}
                />
              )}
            </div>

            {/* Master Summary Card */}
            <div className="space-y-6">
              <div className="eonix-card">
                <h3 className="font-display font-semibold text-sm text-[#17171A] mb-2">
                  Master Resume Profile
                </h3>
                {masterResumeData ? (
                  <div className="space-y-3 text-xs">
                    <div>
                      <span className="text-[#7A7A82] block text-[11px]">Applicant</span>
                      <span className="font-bold text-[#17171A]">
                        {String((masterResumeData as any)?.name || "Configured Profile")}
                      </span>
                    </div>
                    <div>
                      <span className="text-[#7A7A82] block text-[11px]">Title</span>
                      <span className="font-medium text-[#17171A]">
                        {String((masterResumeData as any)?.title || "Full Stack / Backend Engineer")}
                      </span>
                    </div>
                    <div>
                      <span className="text-[#7A7A82] block text-[11px]">Primary Skills</span>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {(((masterResumeData as any)?.skills as string[]) || ["Python", "FastAPI", "Docker", "PostgreSQL"]).map(
                          (s: string, i: number) => (
                            <span
                              key={i}
                              className="px-2 py-0.5 rounded-full bg-[#F4F4F5] text-[10px] font-medium text-[#17171A]"
                            >
                              {s}
                            </span>
                          )
                        )}
                      </div>
                    </div>
                  </div>
                ) : (
                  <p className="text-xs text-[#7A7A82]">No master resume loaded.</p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: Tailor Engine */}
        {activeTab === "tailor" && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Input Form */}
            <div className="eonix-card space-y-4">
              <h2 className="font-display font-semibold text-base text-[#17171A]">
                Target Opportunity Parameters
              </h2>

              <div className="space-y-3 text-xs">
                <div>
                  <label className="font-semibold text-[#17171A] block mb-1">Target Role Title</label>
                  <input
                    type="text"
                    value={jobTitle}
                    onChange={(e) => setJobTitle(e.target.value)}
                    className="w-full px-3.5 py-2 bg-[#F4F4F5] rounded-xl text-xs text-[#17171A] border border-transparent focus:bg-white focus:border-[#7C5CFC] focus:outline-none"
                  />
                </div>

                <div>
                  <label className="font-semibold text-[#17171A] block mb-1">Target Company</label>
                  <input
                    type="text"
                    value={companyName}
                    onChange={(e) => setCompanyName(e.target.value)}
                    className="w-full px-3.5 py-2 bg-[#F4F4F5] rounded-xl text-xs text-[#17171A] border border-transparent focus:bg-white focus:border-[#7C5CFC] focus:outline-none"
                  />
                </div>

                <div>
                  <label className="font-semibold text-[#17171A] block mb-1">Job Description</label>
                  <textarea
                    value={jobDescription}
                    onChange={(e) => setJobDescription(e.target.value)}
                    rows={7}
                    className="w-full px-3.5 py-2.5 bg-[#F4F4F5] rounded-xl text-xs text-[#17171A] border border-transparent focus:bg-white focus:border-[#7C5CFC] focus:outline-none resize-none leading-relaxed"
                  />
                </div>

                <button
                  onClick={handleRunTailor}
                  disabled={tailorMutation.isPending}
                  className="w-full inline-flex items-center justify-center gap-2 py-3 bg-[#7C5CFC] text-white rounded-full font-semibold text-xs shadow-md hover:bg-[#6847E8] transition-colors disabled:opacity-60"
                >
                  {tailorMutation.isPending ? (
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  ) : (
                    <Sparkles size={14} />
                  )}
                  <span>Run Deterministic Resume Tailoring</span>
                </button>
              </div>
            </div>

            {/* Tailor Output */}
            <div className="eonix-card relative flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-3">
                  <h2 className="font-display font-semibold text-base text-[#17171A]">
                    Tailored Resume Output
                  </h2>
                  {tailorResult?.verifier_score && (
                    <span className="font-mono text-xs font-bold text-[#059669] bg-[#EAF9F5] px-3 py-1 rounded-full flex items-center gap-1">
                      <ShieldCheck size={12} />
                      <span>Verifier: {tailorResult.verifier_score}%</span>
                    </span>
                  )}
                </div>

                {tailorResult ? (
                  <div className="space-y-4 text-xs">
                    <div>
                      <span className="font-semibold text-[#7A7A82] block text-[11px] uppercase tracking-wider mb-1">
                        Tailored Summary
                      </span>
                      <p className="bg-[#FBFBFA] p-3.5 rounded-2xl border border-[#EBEAE6] leading-relaxed text-[#17171A]">
                        {tailorResult.summary}
                      </p>
                    </div>

                    <div>
                      <span className="font-semibold text-[#7A7A82] block text-[11px] uppercase tracking-wider mb-1">
                        Ranked Skills
                      </span>
                      <div className="flex flex-wrap gap-1.5">
                        {(tailorResult.skills_reordered || []).map((skill: string, idx: number) => (
                          <span
                            key={idx}
                            className="px-2.5 py-1 rounded-full bg-[#F3EFFF] text-[#7C5CFC] font-semibold text-[11px]"
                          >
                            {skill}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="py-16 text-center text-xs text-[#7A7A82]">
                    Input JD parameters on the left and trigger the tailoring engine.
                  </div>
                )}
              </div>

              {tailorResult && (
                <div className="pt-4 mt-4 border-t border-[#F0EFEC]">
                  <button
                    onClick={handleDownloadDocx}
                    disabled={downloadingDocx}
                    className="w-full inline-flex items-center justify-center gap-2 py-2.5 bg-[#17171A] text-white rounded-full font-semibold text-xs hover:bg-[#2C2C30] transition-colors"
                  >
                    <Download size={14} />
                    <span>{downloadingDocx ? "Rendering..." : "Download 1-Page DOCX"}</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Tab 3: Verifier Gate */}
        {activeTab === "verify" && (
          <div className="eonix-card max-w-3xl mx-auto space-y-5">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-display font-semibold text-base text-[#17171A]">
                  Deterministic Resume Verifier
                </h2>
                <p className="text-xs text-[#7A7A82]">
                  Validates strict non-hallucination against master facts, dates, and metrics.
                </p>
              </div>

              <button
                onClick={handleRunVerify}
                disabled={verifyMutation.isPending}
                className="inline-flex items-center gap-2 px-5 py-2.5 bg-[#7C5CFC] text-white rounded-full text-xs font-semibold hover:bg-[#6847E8] transition-colors"
              >
                {verifyMutation.isPending ? (
                  <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                ) : (
                  <ShieldCheck size={14} />
                )}
                <span>Run Verifier Check</span>
              </button>
            </div>

            {verifyResult ? (
              <div className="space-y-4 pt-2">
                <div className="flex items-center gap-3 p-4 rounded-2xl bg-[#EAF9F5] border border-[#A7F3D0]">
                  <CheckCircle2 size={24} className="text-[#2BC7A0]" />
                  <div>
                    <h3 className="font-display font-bold text-sm text-[#065F46]">
                      Verifier Score: {verifyResult.score}%
                    </h3>
                    <p className="text-xs text-[#047857]">
                      {verifyResult.passed ? "PASSED — Zero hallucinations detected." : "Review flagged items below."}
                    </p>
                  </div>
                </div>

                {/* Violations */}
                <div>
                  <h4 className="font-semibold text-xs text-[#7A7A82] uppercase tracking-wider mb-2">
                    Violations ({verifyResult.violations?.length || 0})
                  </h4>
                  {verifyResult.violations && verifyResult.violations.length > 0 ? (
                    <div className="space-y-2">
                      {verifyResult.violations.map((v: any, i: number) => (
                        <div
                          key={i}
                          className="p-3 rounded-xl bg-[#FFF0EE] text-[#DC2626] text-xs font-medium border border-[#FFD0CA]"
                        >
                          {typeof v === "string" ? v : JSON.stringify(v)}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-[#2BC7A0] font-medium bg-[#EAF9F5] p-3 rounded-xl">
                      ✓ No hard violations found.
                    </p>
                  )}
                </div>

                {/* Warnings */}
                <div>
                  <h4 className="font-semibold text-xs text-[#7A7A82] uppercase tracking-wider mb-2">
                    Warnings ({verifyResult.warnings?.length || 0})
                  </h4>
                  {verifyResult.warnings && verifyResult.warnings.length > 0 ? (
                    <div className="space-y-2">
                      {verifyResult.warnings.map((w: any, i: number) => (
                        <div
                          key={i}
                          className="p-3 rounded-xl bg-[#FFF8E6] text-[#B45309] text-xs font-medium border border-[#FDE68A]"
                        >
                          {typeof w === "string" ? w : JSON.stringify(w)}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-[#7A7A82]">No warnings flagged.</p>
                  )}
                </div>
              </div>
            ) : (
              <div className="py-12 text-center text-xs text-[#7A7A82]">
                Click "Run Verifier Check" to inspect the active resume version.
              </div>
            )}
          </div>
        )}

        {/* Tab 4: Cover Letter */}
        {activeTab === "cover" && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="eonix-card space-y-4">
              <h2 className="font-display font-semibold text-base text-[#17171A]">
                Cold Outreach Generator
              </h2>

              <div className="space-y-3 text-xs">
                <div>
                  <label className="font-semibold text-[#17171A] block mb-1">Your Name</label>
                  <input
                    type="text"
                    value={applicantName}
                    onChange={(e) => setApplicantName(e.target.value)}
                    className="w-full px-3.5 py-2 bg-[#F4F4F5] rounded-xl text-xs text-[#17171A] border border-transparent focus:bg-white focus:border-[#7C5CFC] focus:outline-none"
                  />
                </div>

                <div>
                  <label className="font-semibold text-[#17171A] block mb-1">Target Role & Company</label>
                  <input
                    type="text"
                    value={`${jobTitle} @ ${companyName}`}
                    disabled
                    className="w-full px-3.5 py-2 bg-[#F4F4F5] rounded-xl text-xs text-[#7A7A82] border border-transparent cursor-not-allowed"
                  />
                </div>

                <button
                  onClick={handleRunCover}
                  disabled={coverLetterMutation.isPending}
                  className="w-full inline-flex items-center justify-center gap-2 py-3 bg-[#7C5CFC] text-white rounded-full font-semibold text-xs shadow-md hover:bg-[#6847E8] transition-colors disabled:opacity-60"
                >
                  {coverLetterMutation.isPending ? (
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  ) : (
                    <Mail size={14} />
                  )}
                  <span>Generate Humanized Cover Letter</span>
                </button>
              </div>
            </div>

            <div className="eonix-card relative flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-3">
                  <h2 className="font-display font-semibold text-base text-[#17171A]">
                    Generated Outreach Letter
                  </h2>
                  {coverResult && (
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(coverResult.letter);
                        setCopiedCover(true);
                        setTimeout(() => setCopiedCover(false), 2000);
                      }}
                      className="inline-flex items-center gap-1 text-xs font-semibold text-[#7C5CFC] hover:underline"
                    >
                      {copiedCover ? <Check size={12} /> : <Copy size={12} />}
                      <span>{copiedCover ? "Copied!" : "Copy Letter"}</span>
                    </button>
                  )}
                </div>

                {coverResult ? (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-xs">
                      <span className="font-semibold text-[#7A7A82]">Humanization Score:</span>
                      <span className="font-mono font-bold text-[#059669] bg-[#EAF9F5] px-2 py-0.5 rounded-full text-[11px]">
                        {coverResult.humanization_score}/100
                      </span>
                    </div>

                    <pre className="text-xs text-[#17171A] bg-[#FBFBFA] p-4 rounded-2xl border border-[#EBEAE6] font-mono whitespace-pre-wrap leading-relaxed max-h-[380px] overflow-y-auto">
                      {coverResult.letter}
                    </pre>
                  </div>
                ) : (
                  <div className="py-16 text-center text-xs text-[#7A7A82]">
                    Click generate on the left to draft a two-pass humanized cold email.
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Tab 5: Quality Audit */}
        {activeTab === "quality" && (
          <div className="eonix-card max-w-3xl mx-auto space-y-5">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-display font-semibold text-base text-[#17171A]">
                  One-Page & AI-Cliché Quality Audit
                </h2>
                <p className="text-xs text-[#7A7A82]">
                  Validates character lengths, bullet counts, and flags robotic AI phrase patterns.
                </p>
              </div>

              <button
                onClick={handleRunQualityCheck}
                disabled={qualityMutation.isPending}
                className="inline-flex items-center gap-2 px-5 py-2.5 bg-[#7C5CFC] text-white rounded-full text-xs font-semibold hover:bg-[#6847E8] transition-colors"
              >
                {qualityMutation.isPending ? (
                  <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                ) : (
                  <Award size={14} />
                )}
                <span>Run Quality Audit</span>
              </button>
            </div>

            {qualityResult ? (
              <div className="space-y-4 pt-2">
                <div
                  className={`flex items-center gap-3 p-4 rounded-2xl border ${
                    qualityResult.passed
                      ? "bg-[#EAF9F5] border-[#A7F3D0]"
                      : "bg-[#FFF8E6] border-[#FDE68A]"
                  }`}
                >
                  <CheckCircle2
                    size={24}
                    className={qualityResult.passed ? "text-[#2BC7A0]" : "text-[#FFC94A]"}
                  />
                  <div>
                    <h3 className="font-display font-bold text-sm text-[#17171A]">
                      Audit Score: {qualityResult.score}%
                    </h3>
                    <p className="text-xs text-[#7A7A82]">
                      {qualityResult.passed
                        ? "PASSED — Ready for ATS submission."
                        : "Issues identified below."}
                    </p>
                  </div>
                </div>

                <div>
                  <h4 className="font-semibold text-xs text-[#7A7A82] uppercase tracking-wider mb-2">
                    Issues Identified ({qualityResult.issues?.length || 0})
                  </h4>
                  {qualityResult.issues && qualityResult.issues.length > 0 ? (
                    <div className="space-y-2">
                      {qualityResult.issues.map((iss: string, i: number) => (
                        <div
                          key={i}
                          className="p-3 rounded-xl bg-[#FFF8E6] text-[#B45309] text-xs font-medium border border-[#FDE68A]"
                        >
                          {iss}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-[#2BC7A0] font-medium bg-[#EAF9F5] p-3 rounded-xl">
                      ✓ No length or cliché issues detected.
                    </p>
                  )}
                </div>
              </div>
            ) : (
              <div className="py-12 text-center text-xs text-[#7A7A82]">
                Click "Run Quality Audit" to check one-page and ATS compliance.
              </div>
            )}
          </div>
        )}
      </div>
    </AppLayout>
  );
}
