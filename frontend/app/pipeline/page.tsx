"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "motion/react";
import {
  Play,
  Square,
  Sparkles,
  Sliders,
  CheckCircle2,
  AlertCircle,
  Clock,
  Briefcase,
  Layers,
  Terminal,
  Copy,
  Check,
  RefreshCw,
  Globe,
  Flame,
  ArrowRight,
  ShieldCheck,
  Building2,
} from "lucide-react";
import { AppLayout } from "@/components/AppLayout";
import {
  usePipelineStatus,
  usePipelineRunConfig,
  usePipelineStop,
} from "@/lib/api";
import { PipelineConfig, PipelineStep, PipelineLog } from "@/lib/types";

const KEYWORD_PRESETS = [
  { label: "Backend & DevOps", value: "backend devops kubernetes docker python fullstack" },
  { label: "Full Stack / React", value: "fullstack react typescript nextjs nodejs python" },
  { label: "AI & ML Engineer", value: "ai ml machine learning python pytorch llm backend" },
  { label: "Systems & Infrastructure", value: "sre devops linux cloud aws distributed systems" },
];

const SOURCE_TIER_CONFIG = [
  {
    tierId: "tier0",
    name: "Tier 0 — Direct ATS Scrapers",
    desc: "~100 direct company career boards with zero bot detection",
    accent: "#7C5CFC",
    sources: [
      { id: "greenhouse", name: "Greenhouse" },
      { id: "lever", name: "Lever" },
      { id: "ashby", name: "Ashby" },
      { id: "smartrecruiters", name: "SmartRecruiters" },
    ],
  },
  {
    tierId: "tier1",
    name: "Tier 1 — Portals & Campus Feeds",
    desc: "Indian tech internship portals & direct student platforms",
    accent: "#2BC7A0",
    sources: [
      { id: "hirist", name: "Hirist" },
      { id: "unstop", name: "Unstop" },
      { id: "internshala", name: "Internshala XHR" },
    ],
  },
  {
    tierId: "tier2",
    name: "Tier 2 — JobSpy Aggregators",
    desc: "Realtime cross-portal scrapers with circuit breaker protection",
    accent: "#FFC94A",
    sources: [
      { id: "jobspy", name: "JobSpy Engine" },
      { id: "linkedin", name: "LinkedIn" },
      { id: "indeed", name: "Indeed" },
    ],
  },
  {
    tierId: "tier3",
    name: "Tier 3 — Freelance RSS & Open APIs",
    desc: "Direct freelance tasks, contracts, and public dev APIs",
    accent: "#5B8DEF",
    sources: [
      { id: "freelancer", name: "Freelancer RSS" },
      { id: "themuse", name: "The Muse" },
      { id: "arbeitnow", name: "Arbeitnow" },
      { id: "upwork", name: "Upwork Webhook" },
    ],
  },
];

export default function PipelineDiscoveryPage() {
  const { data: statusData, isLoading: statusLoading } = usePipelineStatus();
  const runMutation = usePipelineRunConfig();
  const stopMutation = usePipelineStop();

  // Configuration Form State
  const [dryRun, setDryRun] = useState(false);
  const [keywords, setKeywords] = useState("backend devops kubernetes docker python fullstack");
  const [locations, setLocations] = useState("Remote, Bengaluru, India");
  const [track, setTrack] = useState<string>("all");
  const [selectedTiers, setSelectedTiers] = useState<string[]>(["tier0", "tier1", "tier2", "tier3"]);
  const [selectedSources, setSelectedSources] = useState<string[]>([
    "greenhouse", "lever", "ashby", "smartrecruiters",
    "hirist", "unstop", "internshala",
    "jobspy", "linkedin", "indeed",
    "freelancer", "themuse", "arbeitnow", "upwork"
  ]);

  const [copiedLogs, setCopiedLogs] = useState(false);
  const [autoScrollLogs, setAutoScrollLogs] = useState(true);
  const logsEndRef = useRef<HTMLDivElement | null>(null);

  const isRunning = statusData?.status === "running";

  // Auto scroll logs when new lines arrive
  useEffect(() => {
    if (autoScrollLogs && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [statusData?.logs, autoScrollLogs]);

  // Toggle tier selection
  const handleToggleTier = (tierId: string) => {
    if (selectedTiers.includes(tierId)) {
      setSelectedTiers(selectedTiers.filter((t) => t !== tierId));
    } else {
      setSelectedTiers([...selectedTiers, tierId]);
    }
  };

  // Toggle individual source
  const handleToggleSource = (sourceId: string) => {
    if (selectedSources.includes(sourceId)) {
      setSelectedSources(selectedSources.filter((s) => s !== sourceId));
    } else {
      setSelectedSources([...selectedSources, sourceId]);
    }
  };

  // Launch pipeline
  const handleStartPipeline = async () => {
    const config: PipelineConfig = {
      dry_run: dryRun,
      keywords,
      locations,
      track,
      tiers: selectedTiers,
      sources: selectedSources,
      limit: 100,
    };
    try {
      await runMutation.mutateAsync(config);
    } catch (err: any) {
      alert(`Launch error: ${err.message}`);
    }
  };

  // Stop pipeline
  const handleStopPipeline = async () => {
    try {
      await stopMutation.mutateAsync();
    } catch (err: any) {
      console.error(err);
    }
  };

  // Copy logs
  const handleCopyLogs = () => {
    if (!statusData?.logs) return;
    const text = statusData.logs
      .map((l: PipelineLog) => `[${l.timestamp}] [${l.level.toUpperCase()}] ${l.message}`)
      .join("\n");
    navigator.clipboard.writeText(text);
    setCopiedLogs(true);
    setTimeout(() => setCopiedLogs(false), 2000);
  };

  return (
    <AppLayout>
      <div className="space-y-6 pb-16">
        {/* Page Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="font-display font-bold text-2xl sm:text-3xl text-[#17171A] tracking-tight">
              Discovery Engine & Live Telemetry
            </h1>
            <p className="text-sm text-[#7A7A82] mt-0.5">
              Configure scrapers, dispatch background discovery runs, and monitor live streaming steps.
            </p>
          </div>

          <div className="flex items-center gap-2">
            {isRunning ? (
              <button
                onClick={handleStopPipeline}
                disabled={stopMutation.isPending}
                className="inline-flex items-center gap-2 px-5 py-2.5 bg-red-600 hover:bg-red-700 text-white rounded-full text-xs font-semibold shadow-sm transition-all"
              >
                <Square size={13} className="fill-current" />
                <span>{stopMutation.isPending ? "Stopping..." : "Stop Execution"}</span>
              </button>
            ) : (
              <button
                onClick={handleStartPipeline}
                disabled={runMutation.isPending}
                className="inline-flex items-center gap-2 px-6 py-2.5 bg-[#7C5CFC] hover:bg-[#6847E8] text-white rounded-full text-xs font-semibold shadow-md transition-all hover:scale-[1.02] disabled:opacity-60"
              >
                {runMutation.isPending ? (
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                ) : (
                  <Play size={13} className="fill-current" />
                )}
                <span>{runMutation.isPending ? "Dispatching..." : "Launch Discovery Pipeline"}</span>
              </button>
            )}
          </div>
        </div>

        {/* 1. Live Progress & Telemetry Cards */}
        <div className="eonix-card relative space-y-5 border border-[#EBEAE6]">
          {/* Top Status Overlapping Pill */}
          <div className="eonix-floating-pill text-[#17171A] border border-[#EBEAE6]">
            {isRunning ? (
              <>
                <span className="w-2.5 h-2.5 rounded-full bg-[#7C5CFC] animate-ping" />
                <span className="font-bold text-[#7C5CFC]">Background Active</span>
              </>
            ) : statusData?.status === "completed" ? (
              <>
                <CheckCircle2 size={13} className="text-[#2BC7A0]" />
                <span className="font-bold text-[#047857]">Ready / Completed</span>
              </>
            ) : (
              <>
                <span className="w-2 h-2 rounded-full bg-[#7A7A82]" />
                <span>Idle Standby</span>
              </>
            )}
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <span className="text-xs uppercase font-semibold text-[#7A7A82] tracking-wider">
                Current Execution Phase
              </span>
              <h2 className="font-display font-bold text-lg sm:text-xl text-[#17171A] mt-0.5">
                {statusData?.active_step || "Ready to launch"}
              </h2>
            </div>

            <div className="flex items-center gap-3">
              <div className="text-right">
                <span className="text-[11px] text-[#7A7A82] block font-mono">Progress</span>
                <span className="font-display font-bold text-2xl text-[#17171A] tabular-nums">
                  {statusData?.progress_pct ?? 0}%
                </span>
              </div>
            </div>
          </div>

          {/* Capsule Progress Bar */}
          <div className="h-4 w-full bg-[#F0EFEC] rounded-full overflow-hidden p-0.5">
            <motion.div
              initial={false}
              animate={{ width: `${Math.max(statusData?.progress_pct ?? 0, 3)}%` }}
              transition={{ duration: 0.4, ease: "easeOut" }}
              className="h-full rounded-full transition-all"
              style={{
                backgroundColor: isRunning ? "#7C5CFC" : statusData?.status === "completed" ? "#2BC7A0" : "#7A7A82",
                backgroundImage: isRunning ? "url(#hatchPatternPurple)" : undefined,
              }}
            />
          </div>

          {/* Metric Counter Row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
            <div className="p-3 rounded-2xl bg-[#FBFBFA] border border-[#EBEAE6]">
              <span className="text-[10px] uppercase font-semibold text-[#7A7A82] tracking-wider block">
                Total Found
              </span>
              <span className="font-display font-bold text-xl sm:text-2xl text-[#17171A] tabular-nums">
                {statusData?.jobs_found ?? 0}
              </span>
            </div>

            <div className="p-3 rounded-2xl bg-[#FBFBFA] border border-[#EBEAE6]">
              <span className="text-[10px] uppercase font-semibold text-[#7A7A82] tracking-wider block">
                Active Tier
              </span>
              <span className="font-semibold text-xs sm:text-sm text-[#7C5CFC] line-clamp-1 mt-1">
                {statusData?.current_tier || "All Tiers"}
              </span>
            </div>

            <div className="p-3 rounded-2xl bg-[#FBFBFA] border border-[#EBEAE6]">
              <span className="text-[10px] uppercase font-semibold text-[#7A7A82] tracking-wider block">
                Errors / Skipped
              </span>
              <span className="font-display font-bold text-xl sm:text-2xl text-[#DC2626] tabular-nums">
                {statusData?.errors?.length ?? 0}
              </span>
            </div>

            <div className="p-3 rounded-2xl bg-[#FBFBFA] border border-[#EBEAE6]">
              <span className="text-[10px] uppercase font-semibold text-[#7A7A82] tracking-wider block">
                Execution Mode
              </span>
              <span className="font-semibold text-xs sm:text-sm text-[#17171A] mt-1 block">
                {statusData?.config?.dry_run ? "Simulated Dry-Run" : "Live Scrapers"}
              </span>
            </div>
          </div>
        </div>

        {/* 2. Step-by-Step Interactive Timeline */}
        <div className="eonix-card space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-display font-semibold text-base text-[#17171A]">
                Pipeline Execution Steps
              </h3>
              <p className="text-xs text-[#7A7A82]">
                Live stage transitions across ATS scrapers, portals, aggregators, and database sync.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 pt-1">
            {(statusData?.steps || []).map((step: PipelineStep, idx: number) => {
              const isStepRunning = step.status === "running";
              const isStepCompleted = step.status === "completed";
              const isStepSkipped = step.status === "skipped";

              return (
                <div
                  key={step.id}
                  className={`p-3.5 rounded-2xl border transition-all ${
                    isStepRunning
                      ? "bg-[#F3EFFF] border-[#7C5CFC] shadow-sm"
                      : isStepCompleted
                      ? "bg-[#EAF9F5] border-[#A7F3D0]"
                      : isStepSkipped
                      ? "bg-[#F4F4F5]/60 border-[#E4E4E7] opacity-60"
                      : "bg-[#FFFFFF] border-[#EBEAE6]"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[10px] font-semibold text-[#7A7A82]">
                      0{idx + 1}
                    </span>
                    {isStepRunning ? (
                      <span className="w-2 h-2 rounded-full bg-[#7C5CFC] animate-ping" />
                    ) : isStepCompleted ? (
                      <CheckCircle2 size={14} className="text-[#2BC7A0]" />
                    ) : (
                      <span className="w-2 h-2 rounded-full bg-[#D4D4D8]" />
                    )}
                  </div>

                  <h4 className="font-display font-semibold text-xs text-[#17171A] mt-2 line-clamp-2 leading-snug">
                    {step.label}
                  </h4>

                  <div className="mt-2.5 pt-2 border-t border-black/5 flex items-center justify-between text-[11px] font-mono">
                    <span className="capitalize text-[#7A7A82]">
                      {isStepRunning ? "Processing..." : step.status}
                    </span>
                    {step.count > 0 && (
                      <span className="font-bold text-[#17171A] bg-white px-2 py-0.5 rounded-full shadow-2xs">
                        +{step.count}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 3. Main 2-Column Section: Config Form & Live Console */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column: Full Configuration Panel (5 cols) */}
          <div className="lg:col-span-5 space-y-6">
            <div className="eonix-card space-y-5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Sliders size={16} className="text-[#7C5CFC]" />
                  <h3 className="font-display font-semibold text-base text-[#17171A]">
                    Run Parameters
                  </h3>
                </div>

                {/* Dry Run Toggle */}
                <label className="flex items-center gap-2 text-xs font-semibold cursor-pointer bg-[#F4F4F5] px-3 py-1.5 rounded-full">
                  <input
                    type="checkbox"
                    checked={dryRun}
                    onChange={(e) => setDryRun(e.target.checked)}
                    disabled={isRunning}
                    className="w-3.5 h-3.5 accent-[#7C5CFC] rounded"
                  />
                  <span>Dry Run</span>
                </label>
              </div>

              {/* Target Role Keywords */}
              <div className="space-y-1.5 text-xs">
                <label className="font-semibold text-[#17171A] block">
                  Search Keywords
                </label>
                <input
                  type="text"
                  value={keywords}
                  onChange={(e) => setKeywords(e.target.value)}
                  disabled={isRunning}
                  className="w-full px-3.5 py-2.5 bg-[#F4F4F5] rounded-xl text-xs text-[#17171A] border border-transparent focus:bg-white focus:border-[#7C5CFC] focus:outline-none font-mono"
                />

                {/* Preset Chips */}
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {KEYWORD_PRESETS.map((p) => (
                    <button
                      key={p.label}
                      onClick={() => setKeywords(p.value)}
                      disabled={isRunning}
                      className="px-2 py-0.5 rounded-full bg-white border border-[#EBEAE6] text-[10px] font-medium text-[#7A7A82] hover:text-[#17171A] hover:bg-[#F5F4F0] transition-colors"
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Locations */}
              <div className="space-y-1.5 text-xs">
                <label className="font-semibold text-[#17171A] block">
                  Location Constraints
                </label>
                <input
                  type="text"
                  value={locations}
                  onChange={(e) => setLocations(e.target.value)}
                  disabled={isRunning}
                  className="w-full px-3.5 py-2.5 bg-[#F4F4F5] rounded-xl text-xs text-[#17171A] border border-transparent focus:bg-white focus:border-[#7C5CFC] focus:outline-none"
                />
              </div>

              {/* Track Scope */}
              <div className="space-y-1.5 text-xs">
                <label className="font-semibold text-[#17171A] block">
                  Opportunity Scope
                </label>
                <div className="grid grid-cols-3 gap-1.5 bg-[#F4F4F5] p-1 rounded-xl">
                  {[
                    { id: "all", label: "All Leads" },
                    { id: "internship", label: "Internships" },
                    { id: "freelance", label: "Freelance" },
                  ].map((t) => (
                    <button
                      key={t.id}
                      onClick={() => setTrack(t.id)}
                      disabled={isRunning}
                      className={`py-1.5 rounded-lg text-xs font-semibold transition-all ${
                        track === t.id
                          ? "bg-white text-[#17171A] shadow-xs"
                          : "text-[#7A7A82] hover:text-[#17171A]"
                      }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Source Tiers & Checkboxes */}
              <div className="space-y-3 pt-2">
                <label className="font-semibold text-xs text-[#17171A] block">
                  Target Scraper Tiers
                </label>

                <div className="space-y-2.5">
                  {SOURCE_TIER_CONFIG.map((tier) => {
                    const isTierActive = selectedTiers.includes(tier.tierId);

                    return (
                      <div
                        key={tier.tierId}
                        className={`p-3 rounded-2xl border transition-all ${
                          isTierActive
                            ? "bg-[#FFFFFF] border-[#EBEAE6] shadow-2xs"
                            : "bg-[#FBFBFA] border-transparent opacity-60"
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <label className="flex items-center gap-2 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={isTierActive}
                              onChange={() => handleToggleTier(tier.tierId)}
                              disabled={isRunning}
                              className="w-3.5 h-3.5 accent-[#7C5CFC] rounded"
                            />
                            <span className="font-semibold text-xs text-[#17171A]">
                              {tier.name}
                            </span>
                          </label>
                          <span
                            className="w-2 h-2 rounded-full"
                            style={{ backgroundColor: tier.accent }}
                          />
                        </div>

                        <p className="text-[11px] text-[#7A7A82] mt-1 pl-5">
                          {tier.desc}
                        </p>

                        {/* Individual Source Pills */}
                        {isTierActive && (
                          <div className="flex flex-wrap gap-1.5 mt-2.5 pl-5">
                            {tier.sources.map((s) => {
                              const isSourceSelected = selectedSources.includes(s.id);
                              return (
                                <button
                                  key={s.id}
                                  onClick={() => handleToggleSource(s.id)}
                                  disabled={isRunning}
                                  className={`px-2 py-0.5 rounded-full text-[10px] font-semibold transition-colors ${
                                    isSourceSelected
                                      ? "bg-[#17171A] text-white"
                                      : "bg-[#F4F4F5] text-[#7A7A82] hover:bg-[#EAE9E5]"
                                  }`}
                                >
                                  {s.name}
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>

          {/* Right Column: Live Streaming Terminal Console (7 cols) */}
          <div className="lg:col-span-7 space-y-6">
            <div className="eonix-card h-full flex flex-col justify-between p-0 overflow-hidden bg-[#17171A] border border-white/10 shadow-2xl">
              {/* Terminal Header */}
              <div className="px-4 py-3 bg-[#202024] border-b border-white/10 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="flex items-center gap-1.5">
                    <span className="w-3 h-3 rounded-full bg-[#FF5F56]" />
                    <span className="w-3 h-3 rounded-full bg-[#FFBD2E]" />
                    <span className="w-3 h-3 rounded-full bg-[#27C93F]" />
                  </div>
                  <span className="font-mono text-xs text-[#A1A1AA] ml-2 flex items-center gap-1.5">
                    <Terminal size={12} />
                    <span>pipeline-daemon.stdout</span>
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  <label className="flex items-center gap-1.5 text-[11px] font-mono text-[#A1A1AA] cursor-pointer">
                    <input
                      type="checkbox"
                      checked={autoScrollLogs}
                      onChange={(e) => setAutoScrollLogs(e.target.checked)}
                      className="accent-[#7C5CFC] rounded"
                    />
                    <span>Auto-scroll</span>
                  </label>

                  <button
                    onClick={handleCopyLogs}
                    className="p-1.5 rounded-lg text-[#A1A1AA] hover:text-white hover:bg-white/10 transition-colors"
                    title="Copy console logs"
                  >
                    {copiedLogs ? <Check size={13} className="text-[#2BC7A0]" /> : <Copy size={13} />}
                  </button>
                </div>
              </div>

              {/* Console Body */}
              <div className="p-4 flex-1 font-mono text-xs overflow-y-auto max-h-[580px] min-h-[420px] space-y-2 select-text leading-relaxed">
                {!statusData?.logs || statusData.logs.length === 0 ? (
                  <div className="py-24 text-center text-[#7A7A82]">
                    [System idle] Click "Launch Discovery Pipeline" to start live execution telemetry.
                  </div>
                ) : (
                  statusData.logs.map((log: PipelineLog, idx: number) => {
                    let levelColor = "text-[#A1A1AA]";
                    if (log.level === "success") levelColor = "text-[#2BC7A0]";
                    if (log.level === "warn") levelColor = "text-[#FFC94A]";
                    if (log.level === "error") levelColor = "text-[#FF6B57]";

                    return (
                      <div key={idx} className="flex items-start gap-2.5">
                        <span className="text-[#52525B] text-[11px] flex-shrink-0 select-none">
                          {log.timestamp}
                        </span>
                        <span className={`uppercase text-[10px] font-bold px-1.5 py-0.2 rounded ${levelColor} bg-white/5 flex-shrink-0`}>
                          {log.level}
                        </span>
                        <span className={`break-words ${log.level === "error" ? "text-[#FF6B57]" : log.level === "success" ? "text-white font-medium" : "text-[#D4D4D8]"}`}>
                          {log.message}
                        </span>
                      </div>
                    );
                  })
                )}
                <div ref={logsEndRef} />
              </div>

              {/* Terminal Footer */}
              <div className="px-4 py-2 bg-[#202024] border-t border-white/10 flex items-center justify-between text-[11px] font-mono text-[#7A7A82]">
                <div className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#2BC7A0]" />
                  <span>Daemon active</span>
                </div>
                <div>
                  <span>Log lines: {statusData?.logs?.length ?? 0}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
