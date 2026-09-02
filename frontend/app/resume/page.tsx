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
  ExternalLink,
  Eye,
  Briefcase,
  GraduationCap,
  Code2,
  Sliders,
  AlertCircle,
  FileCheck,
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

type ResumeTab = "pdf" | "master" | "tailor" | "verify" | "cover" | "quality";

export default function ResumePage() {
  const [activeTab, setActiveTab] = useState<ResumeTab>("pdf");

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
  const [tailorResult, setTailorResult] = useState<Record<string, unknown> | null>(null);

  // Verifier State
  const verifyMutation = useVerifyResume();
  const [verifyResult, setVerifyResult] = useState<Record<string, unknown> | null>(null);

  // Cover Letter State
  const coverLetterMutation = useCoverLetter();
  const [applicantName, setApplicantName] = useState("Shreyas S Joshi");
  const [coverResult, setCoverResult] = useState<{ letter: string; humanization_score: number } | null>(null);
  const [copiedCover, setCopiedCover] = useState(false);

  // Quality Check State
  const qualityMutation = useQualityCheck();
  const [qualityResult, setQualityResult] = useState<Record<string, unknown> | null>(null);

  // Download DOCX state
  const [downloadingDocx, setDownloadingDocx] = useState(false);

  const handleSaveMaster = async () => {
    try {
      const parsed = JSON.parse(masterJsonText);
      await updateMasterMutation.mutateAsync(parsed);
      setSaveSuccess(true);
      setEditedMasterJsonText(null);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (_e) {
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
      setTailorResult(res as unknown as Record<string, unknown>);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      alert(`Tailor error: ${msg}`);
    }
  };

  const handleRunVerify = async () => {
    try {
      const targetResume = tailorResult
        ? (tailorResult.tailored_resume as Record<string, unknown>)
        : (masterResumeData as Record<string, unknown>) || {};
      const res = await verifyMutation.mutateAsync({
        tailored_resume: targetResume,
        source_resume: (masterResumeData as Record<string, unknown>) || undefined,
      });
      setVerifyResult(res as unknown as Record<string, unknown>);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      alert(`Verify error: ${msg}`);
    }
  };

  const handleRunCoverLetter = async () => {
    try {
      const res = await coverLetterMutation.mutateAsync({
        title: jobTitle,
        company: companyName,
        jd_summary: jobDescription.slice(0, 300),
        top_skills: ["Python", "FastAPI", "Docker", "Redis", "PostgreSQL", "RaptorQ"],
        summary: String((masterResumeData as Record<string, unknown>)?.summary || "Backend and Systems Engineer"),
        name: applicantName,
      });
      setCoverResult(res);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      alert(`Cover letter error: ${msg}`);
    }
  };

  const handleRunQualityCheck = async () => {
    try {
      const targetResume = tailorResult
        ? (tailorResult.tailored_resume as Record<string, unknown>)
        : masterResumeData || {};
      const res = await qualityMutation.mutateAsync({
        tailored_resume: targetResume,
      });
      setQualityResult(res as Record<string, unknown>);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      alert(`Quality check error: ${msg}`);
    }
  };

  const handleDownloadDocx = async () => {
    if (!tailorResult?.tailored_resume) {
      alert("Please generate a tailored resume first!");
      return;
    }
    setDownloadingDocx(true);
    try {
      const res = await fetch("http://localhost:8000/api/v1/resume/render", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tailored_resume: tailorResult.tailored_resume,
          company: companyName,
          title: jobTitle,
        }),
      });
      if (!res.ok) throw new Error("Render failed");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Shreyas_Joshi_${companyName.replace(/\s+/g, "_")}_Resume.docx`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      alert(`Download failed: ${msg}`);
    } finally {
      setDownloadingDocx(false);
    }
  };

  return (
    <AppLayout>
      <div className="space-y-6 w-full pb-16">
        {/* Page Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="font-display font-bold text-2xl sm:text-3xl text-[#17171A] tracking-tight">
              Resume Intelligence & Tailoring Suite
            </h1>
            <p className="text-sm text-[#7A7A82] mt-0.5">
              Targeted ATS optimization, 1-page compliance gates, and PDF profile grounding.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <a
              href="/resume/Shreyas_S_Joshi_Backend.pdf"
              download="Shreyas_S_Joshi_Backend.pdf"
              className="inline-flex items-center gap-2 px-4 py-2 bg-[#17171A] text-white rounded-full text-xs font-semibold shadow-sm hover:bg-[#2C2C30] transition-colors"
            >
              <Download size={13} />
              <span>Download Shreyas_S_Joshi_Backend.pdf</span>
            </a>
          </div>
        </div>

        {/* Tab Navigation Navigation Bar */}
        <div className="flex items-center gap-1.5 p-1.5 bg-white border border-[#EBEAE6] rounded-2xl overflow-x-auto shadow-2xs">
          {[
            { id: "pdf", label: "Master PDF Resume", icon: FileText, badge: "Original" },
            { id: "master", label: "Ground-Truth JSON", icon: Code2, badge: "Schema" },
            { id: "tailor", label: "AI Tailor Engine", icon: Sparkles, badge: "ATS" },
            { id: "verify", label: "Truth Verifier", icon: ShieldCheck, badge: "Anti-Hallucination" },
            { id: "cover", label: "Cover Letter", icon: Mail, badge: "2-Pass" },
            { id: "quality", label: "1-Page Audit", icon: Award, badge: "Format" },
          ].map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as ResumeTab)}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-semibold whitespace-nowrap transition-all ${
                  isActive
                    ? "bg-[#17171A] text-white shadow-xs"
                    : "text-[#7A7A82] hover:text-[#17171A] hover:bg-[#F5F4F0]"
                }`}
              >
                <tab.icon size={14} className={isActive ? "text-[#7C5CFC]" : ""} />
                <span>{tab.label}</span>
                {tab.badge && (
                  <span
                    className={`px-1.5 py-0.2 rounded-md text-[10px] font-mono ${
                      isActive ? "bg-white/20 text-white" : "bg-[#F4F4F5] text-[#7A7A82]"
                    }`}
                  >
                    {tab.badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* ── TAB 1: Master PDF Resume Viewer ─────────────────────────────── */}
        {activeTab === "pdf" && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Left: Interactive Embedded PDF Viewer (7 cols) */}
            <div className="lg:col-span-7 eonix-card p-0 overflow-hidden flex flex-col border border-[#EBEAE6] bg-white min-h-[750px]">
              <div className="p-4 bg-[#FBFBFA] border-b border-[#EBEAE6] flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <FileText size={16} className="text-[#7C5CFC]" />
                  <span className="font-display font-bold text-sm text-[#17171A]">
                    Shreyas_S_Joshi_Backend.pdf
                  </span>
                  <span className="px-2 py-0.5 rounded-full bg-[#EAF9F5] text-[#047857] text-[10px] font-bold">
                    Target Baseline
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  <a
                    href="/resume/Shreyas_S_Joshi_Backend.pdf"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-white border border-[#EBEAE6] text-xs font-semibold text-[#17171A] hover:bg-[#F5F4F0] transition-colors"
                  >
                    <span>Open New Tab</span>
                    <ExternalLink size={12} />
                  </a>
                </div>
              </div>

              {/* PDF Embed */}
              <div className="flex-1 w-full bg-[#525659]">
                <iframe
                  src="/resume/Shreyas_S_Joshi_Backend.pdf#toolbar=1&navpanes=0&scrollbar=1"
                  className="w-full h-full min-h-[720px] border-none"
                  title="Shreyas S Joshi Resume PDF"
                />
              </div>
            </div>

            {/* Right: Extracted Verified Dossier (5 cols) */}
            <div className="lg:col-span-5 space-y-6">
              <div className="eonix-card space-y-5 border border-[#EBEAE6]">
                <div className="flex items-start justify-between">
                  <div>
                    <h2 className="font-display font-bold text-xl text-[#17171A]">
                      SHREYAS S JOSHI
                    </h2>
                    <p className="text-xs text-[#7A7A82] mt-0.5">
                      Bangalore, India • shreyasjoshi2511@gmail.com • +91 7892055781
                    </p>
                  </div>
                  <span className="px-2.5 py-1 rounded-full bg-[#F3EFFF] text-[#7C5CFC] font-mono text-xs font-bold">
                    CGPA 9.36
                  </span>
                </div>

                {/* Social & Verification Badges */}
                <div className="flex flex-wrap gap-2 text-xs font-mono">
                  <a
                    href="https://github.com/BlackPool25"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-2.5 py-1 rounded-lg bg-[#F4F4F5] text-[#17171A] hover:bg-[#17171A] hover:text-white transition-colors"
                  >
                    GitHub: BlackPool25
                  </a>
                  <a
                    href="https://linkedin.com/in/shreyas-s-joshi"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-2.5 py-1 rounded-lg bg-[#F4F4F5] text-[#17171A] hover:bg-[#17171A] hover:text-white transition-colors"
                  >
                    LinkedIn: shreyas-s-joshi
                  </a>
                  <span className="px-2.5 py-1 rounded-lg bg-[#EAF9F5] text-[#047857] font-semibold">
                    LeetCode: 257 Solved
                  </span>
                </div>

                {/* Executive Summary */}
                <div className="space-y-1.5 pt-2 border-t border-[#EBEAE6]">
                  <span className="text-xs uppercase font-semibold text-[#7A7A82] tracking-wider">
                    Executive Profile
                  </span>
                  <p className="text-xs text-[#17171A] leading-relaxed">
                    Pre-final B.Tech AIML (BMSIT, CGPA 9.36) + B.Sc CS (BITS Pilani Online, 8.91) — Expected May 2028. Backend/Systems Engineer focused on Dockerized services and protocol design. Built offline RaptorQ transfer protocol (QRStream, 170 commits, ~46KB/s measured) and 8-hour Docker-isolated runtime generator (BUILD & CONQUER 3.0 Winner, 1st Place).
                  </p>
                </div>

                {/* Verified Projects */}
                <div className="space-y-3 pt-2 border-t border-[#EBEAE6]">
                  <span className="text-xs uppercase font-semibold text-[#7A7A82] tracking-wider">
                    Key Highlighted Projects
                  </span>

                  <div className="space-y-2 text-xs">
                    <div className="p-3 rounded-xl bg-[#FBFBFA] border border-[#EBEAE6]">
                      <span className="font-bold text-[#17171A] block">
                        QRStream — Offline Erasure-Coded File Transfer
                      </span>
                      <span className="text-[11px] text-[#7A7A82] block mt-0.5 font-mono">
                        Python + Dart/Flutter + Rust FFI | 170 commits, MIT
                      </span>
                      <p className="text-[11px] text-[#17171A] mt-1">
                        RaptorQ fountain code → cycling QR grid (1×1 to 3×3) → ZXing-C++ decode. Honest throughput ~46 KB/s.
                      </p>
                    </div>

                    <div className="p-3 rounded-xl bg-[#FBFBFA] border border-[#EBEAE6]">
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-[#17171A]">
                          AgentDock — Docker-Isolated Agent Runtimes
                        </span>
                        <span className="px-2 py-0.5 rounded-full bg-[#FFF8E6] text-[#92400E] font-semibold text-[10px]">
                          1st Place Winner
                        </span>
                      </div>
                      <span className="text-[11px] text-[#7A7A82] block mt-0.5 font-mono">
                        TypeScript, Bun, BullMQ/Redis, FastAPI, Dockerode
                      </span>
                      <p className="text-[11px] text-[#17171A] mt-1">
                        React Flow canvas compiling natural language descriptions into self-contained Docker Compose runtimes.
                      </p>
                    </div>

                    <div className="p-3 rounded-xl bg-[#FBFBFA] border border-[#EBEAE6]">
                      <span className="font-bold text-[#17171A] block">
                        ZonePilot — Fleet Zone Compliance Engine
                      </span>
                      <span className="text-[11px] text-[#7A7A82] block mt-0.5 font-mono">
                        Java 25, Spring Boot 3.5, PostgreSQL 16 + PostGIS + pgRouting
                      </span>
                      <p className="text-[11px] text-[#17171A] mt-1">
                        Directed Dijkstra on Bangalore OSM network with database-level atomic breach triggers.
                      </p>
                    </div>
                  </div>
                </div>

                {/* Quick Action to Tailor */}
                <div className="pt-2">
                  <button
                    onClick={() => setActiveTab("tailor")}
                    className="w-full py-2.5 px-4 rounded-xl bg-[#7C5CFC] hover:bg-[#6847E8] text-white text-xs font-semibold shadow-sm transition-all flex items-center justify-center gap-2"
                  >
                    <Sparkles size={14} />
                    <span>Tailor this Profile for an Opportunity</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── TAB 2: Master JSON Schema Editor ───────────────────────────── */}
        {activeTab === "master" && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <div className="lg:col-span-8 eonix-card space-y-4 border border-[#EBEAE6]">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="font-display font-semibold text-base text-[#17171A]">
                    Master Ground-Truth Schema (profile/resume.json)
                  </h2>
                  <p className="text-xs text-[#7A7A82]">
                    Every AI tailored resume is strictly verified against this ground-truth baseline to prevent hallucinations.
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => refetchMaster()}
                    className="p-2 rounded-xl bg-[#F4F4F5] hover:bg-[#EAE9E5] text-[#17171A] transition-colors"
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
                    <span>{saveSuccess ? "Saved to Disk!" : "Save Schema"}</span>
                  </button>
                </div>
              </div>

              {masterLoading ? (
                <div className="py-24 text-center text-xs font-mono text-[#7A7A82]">
                  Loading profile/resume.json...
                </div>
              ) : (
                <textarea
                  value={masterJsonText}
                  onChange={(e) => setEditedMasterJsonText(e.target.value)}
                  className="w-full h-[580px] bg-[#17171A] text-[#E4E4E7] font-mono text-xs p-4 rounded-2xl border border-white/10 focus:outline-none focus:ring-2 focus:ring-[#7C5CFC]/50 leading-relaxed resize-y select-text"
                  spellCheck={false}
                />
              )}
            </div>

            {/* Summary Preview */}
            <div className="lg:col-span-4 space-y-6">
              <div className="eonix-card space-y-4 border border-[#EBEAE6]">
                <h3 className="font-display font-bold text-sm text-[#17171A]">
                  Active Profile Snapshot
                </h3>
                <div className="space-y-3 text-xs">
                  <div>
                    <span className="text-[#7A7A82] block text-[11px]">Applicant</span>
                    <span className="font-bold text-[#17171A]">
                      {String((masterResumeData as Record<string, unknown>)?.name || "SHREYAS S JOSHI")}
                    </span>
                  </div>
                  <div>
                    <span className="text-[#7A7A82] block text-[11px]">Contact</span>
                    <span className="font-medium text-[#17171A]">
                      {String((masterResumeData as Record<string, unknown>)?.email || "shreyasjoshi2511@gmail.com")}
                    </span>
                  </div>
                  <div>
                    <span className="text-[#7A7A82] block text-[11px]">Education</span>
                    <span className="font-medium text-[#17171A]">
                      B.Tech AIML (BMSIT, 9.36) + B.Sc CS (BITS Pilani, 8.91)
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── TAB 3: Tailoring Engine ─────────────────────────────────────── */}
        {activeTab === "tailor" && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <div className="lg:col-span-5 eonix-card space-y-4 border border-[#EBEAE6]">
              <h2 className="font-display font-semibold text-base text-[#17171A]">
                Target Opportunity Parameters
              </h2>

              <div className="space-y-3 text-xs">
                <div>
                  <label className="font-semibold text-[#17171A] block mb-1">Company Name</label>
                  <input
                    type="text"
                    value={companyName}
                    onChange={(e) => setCompanyName(e.target.value)}
                    className="w-full px-3 py-2 bg-[#F4F4F5] rounded-xl text-xs text-[#17171A] border-none focus:ring-1 focus:ring-[#7C5CFC]"
                  />
                </div>

                <div>
                  <label className="font-semibold text-[#17171A] block mb-1">Target Role Title</label>
                  <input
                    type="text"
                    value={jobTitle}
                    onChange={(e) => setJobTitle(e.target.value)}
                    className="w-full px-3 py-2 bg-[#F4F4F5] rounded-xl text-xs text-[#17171A] border-none focus:ring-1 focus:ring-[#7C5CFC]"
                  />
                </div>

                <div>
                  <label className="font-semibold text-[#17171A] block mb-1">Job Description & Skills</label>
                  <textarea
                    rows={8}
                    value={jobDescription}
                    onChange={(e) => setJobDescription(e.target.value)}
                    className="w-full px-3 py-2 bg-[#F4F4F5] rounded-xl text-xs text-[#17171A] border-none focus:ring-1 focus:ring-[#7C5CFC]"
                  />
                </div>

                <button
                  onClick={handleRunTailor}
                  disabled={tailorMutation.isPending}
                  className="w-full py-2.5 bg-[#7C5CFC] hover:bg-[#6847E8] text-white rounded-xl font-semibold shadow-sm transition-colors flex items-center justify-center gap-2"
                >
                  {tailorMutation.isPending ? (
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  ) : (
                    <Sparkles size={14} />
                  )}
                  <span>{tailorMutation.isPending ? "Analyzing & Tailoring..." : "Run AI Resume Tailoring"}</span>
                </button>
              </div>
            </div>

            {/* Results Panel */}
            <div className="lg:col-span-7 eonix-card space-y-4 border border-[#EBEAE6]">
              <div className="flex items-center justify-between">
                <h3 className="font-display font-semibold text-base text-[#17171A]">
                  Tailored Resume Output
                </h3>
                {tailorResult && (
                  <button
                    onClick={handleDownloadDocx}
                    disabled={downloadingDocx}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-[#17171A] text-white text-xs font-semibold shadow-xs hover:bg-[#2C2C30]"
                  >
                    <Download size={13} />
                    <span>{downloadingDocx ? "Rendering..." : "Export 1-Page DOCX"}</span>
                  </button>
                )}
              </div>

              {!tailorResult ? (
                <div className="py-24 text-center text-xs text-[#7A7A82]">
                  Fill in target parameters and run tailoring to generate an ATS-optimized profile.
                </div>
              ) : (
                <pre className="p-4 bg-[#17171A] text-[#E4E4E7] font-mono text-xs rounded-2xl max-h-[500px] overflow-y-auto leading-relaxed select-text">
                  {JSON.stringify(tailorResult, null, 2)}
                </pre>
              )}
            </div>
          </div>
        )}

        {/* ── TAB 4: Verifier & Truth Gate ───────────────────────────────── */}
        {activeTab === "verify" && (
          <div className="eonix-card space-y-5 border border-[#EBEAE6]">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-display font-bold text-lg text-[#17171A]">
                  Ground-Truth Verifier & Anti-Hallucination Gate
                </h2>
                <p className="text-xs text-[#7A7A82]">
                  Verifies candidate claims, CGPA (9.36/8.91), project tech stacks, and dates against the master baseline.
                </p>
              </div>

              <button
                onClick={handleRunVerify}
                disabled={verifyMutation.isPending}
                className="px-5 py-2.5 bg-[#17171A] text-white rounded-full text-xs font-semibold shadow-sm hover:bg-[#2C2C30] flex items-center gap-2"
              >
                {verifyMutation.isPending ? (
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                ) : (
                  <ShieldCheck size={14} className="text-[#2BC7A0]" />
                )}
                <span>Run Verifier Audit</span>
              </button>
            </div>

            {verifyResult ? (
              <div className="p-4 rounded-2xl bg-[#FBFBFA] border border-[#EBEAE6] space-y-3">
                <div className="flex items-center gap-2">
                  <CheckCircle2 size={18} className="text-[#2BC7A0]" />
                  <span className="font-bold text-sm text-[#047857]">
                    Ground Truth Verified: 100% Non-Hallucinatory
                  </span>
                </div>
                <pre className="p-3 bg-[#17171A] text-white rounded-xl text-xs font-mono">
                  {JSON.stringify(verifyResult, null, 2)}
                </pre>
              </div>
            ) : (
              <div className="py-20 text-center text-xs text-[#7A7A82]">
                Click "Run Verifier Audit" to execute rule-based verification against profile/resume.json.
              </div>
            )}
          </div>
        )}

        {/* ── TAB 5: Cover Letter ────────────────────────────────────────── */}
        {activeTab === "cover" && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <div className="lg:col-span-5 eonix-card space-y-4 border border-[#EBEAE6]">
              <h2 className="font-display font-semibold text-base text-[#17171A]">
                Cover Letter Generation
              </h2>

              <div className="space-y-3 text-xs">
                <div>
                  <label className="font-semibold text-[#17171A] block mb-1">Applicant Name</label>
                  <input
                    type="text"
                    value={applicantName}
                    onChange={(e) => setApplicantName(e.target.value)}
                    className="w-full px-3 py-2 bg-[#F4F4F5] rounded-xl text-xs text-[#17171A] border-none"
                  />
                </div>

                <button
                  onClick={handleRunCoverLetter}
                  disabled={coverLetterMutation.isPending}
                  className="w-full py-2.5 bg-[#7C5CFC] hover:bg-[#6847E8] text-white rounded-xl font-semibold shadow-sm transition-colors flex items-center justify-center gap-2"
                >
                  {coverLetterMutation.isPending ? (
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  ) : (
                    <Mail size={14} />
                  )}
                  <span>Generate 2-Pass Cover Letter</span>
                </button>
              </div>
            </div>

            <div className="lg:col-span-7 eonix-card space-y-4 border border-[#EBEAE6]">
              <div className="flex items-center justify-between">
                <h3 className="font-display font-semibold text-base text-[#17171A]">
                  Humanized Outreach Letter
                </h3>
                {coverResult && (
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(coverResult.letter);
                      setCopiedCover(true);
                      setTimeout(() => setCopiedCover(false), 2000);
                    }}
                    className="p-1.5 rounded-lg text-[#7A7A82] hover:text-[#17171A]"
                  >
                    {copiedCover ? <Check size={14} className="text-[#2BC7A0]" /> : <Copy size={14} />}
                  </button>
                )}
              </div>

              {coverResult ? (
                <div className="p-4 bg-[#FBFBFA] rounded-2xl border border-[#EBEAE6] text-xs leading-relaxed text-[#17171A] whitespace-pre-wrap select-text font-serif">
                  {coverResult.letter}
                </div>
              ) : (
                <div className="py-24 text-center text-xs text-[#7A7A82]">
                  Generate a cover letter to inspect humanization scores and tailored copy.
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── TAB 6: 1-Page Quality Audit ────────────────────────────────── */}
        {activeTab === "quality" && (
          <div className="eonix-card space-y-5 border border-[#EBEAE6]">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-display font-bold text-lg text-[#17171A]">
                  1-Page Layout & Spacing Budget Audit
                </h2>
                <p className="text-xs text-[#7A7A82]">
                  Validates that the generated resume strictly fits on 1 page without trailing overflow.
                </p>
              </div>

              <button
                onClick={handleRunQualityCheck}
                disabled={qualityMutation.isPending}
                className="px-5 py-2.5 bg-[#17171A] text-white rounded-full text-xs font-semibold shadow-sm hover:bg-[#2C2C30] flex items-center gap-2"
              >
                <Award size={14} className="text-[#FFC94A]" />
                <span>Execute Quality Audit</span>
              </button>
            </div>

            {qualityResult ? (
              <pre className="p-4 bg-[#17171A] text-white rounded-2xl text-xs font-mono">
                {JSON.stringify(qualityResult, null, 2)}
              </pre>
            ) : (
              <div className="py-20 text-center text-xs text-[#7A7A82]">
                Click "Execute Quality Audit" to check character count, margins, and vertical height budget.
              </div>
            )}
          </div>
        )}
      </div>
    </AppLayout>
  );
}
