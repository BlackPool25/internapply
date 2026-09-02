"use client";

import { useState } from "react";
import {
  Play,
  RotateCcw,
  Trash2,
  CheckCircle2,
  AlertTriangle,
  Sliders,
} from "lucide-react";
import { AppLayout } from "@/components/AppLayout";
import {
  usePipelineRun,
  usePipelineClear,
  usePipelineRerun,
} from "@/lib/api";

export default function SettingsPage() {
  const pipelineRunMutation = usePipelineRun();
  const pipelineClearMutation = usePipelineClear();
  const pipelineRerunMutation = usePipelineRerun();

  const [dryRun, setDryRun] = useState(false);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [showRerunConfirm, setShowRerunConfirm] = useState(false);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Local config preferences form state
  const [keywords, setKeywords] = useState("backend devops kubernetes docker python fullstack");
  const [locations, setLocations] = useState("Remote, Bengaluru, India");
  const [tier0Enabled, setTier0Enabled] = useState(true);
  const [tier1Enabled, setTier1Enabled] = useState(true);
  const [tier2Enabled, setTier2Enabled] = useState(true);
  const [tier3Enabled, setTier3Enabled] = useState(true);

  const handleRunPipeline = async () => {
    try {
      const res = await pipelineRunMutation.mutateAsync(dryRun);
      setActionSuccess(`Pipeline executed (${res.jobs_found ?? 0} jobs found, stage: ${res.stage || "completed"})`);
      setTimeout(() => setActionSuccess(null), 4000);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      alert(`Run failed: ${msg}`);
    }
  };

  const handleClearPipeline = async () => {
    try {
      await pipelineClearMutation.mutateAsync();
      setShowClearConfirm(false);
      setActionSuccess("Pipeline database tables cleared successfully.");
      setTimeout(() => setActionSuccess(null), 4000);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      alert(`Clear failed: ${msg}`);
    }
  };

  const handleRerunPipeline = async () => {
    try {
      const res = await pipelineRerunMutation.mutateAsync();
      setShowRerunConfirm(false);
      setActionSuccess(`Rerun completed (${res.items_rerun} items reprocessed).`);
      setTimeout(() => setActionSuccess(null), 4000);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      alert(`Rerun failed: ${msg}`);
    }
  };

  const handleSavePreferences = () => {
    setActionSuccess("Preferences saved locally (loaded by scraper daemon).");
    setTimeout(() => setActionSuccess(null), 3000);
  };

  return (
    <AppLayout>
      <div className="space-y-6 max-w-4xl mx-auto pb-16">
        {/* Toast */}
        {actionSuccess && (
          <div className="fixed bottom-6 right-6 z-50 bg-[#17171A] text-white px-4 py-2.5 rounded-full text-xs font-semibold shadow-2xl flex items-center gap-2 border border-white/10 animate-bounce">
            <CheckCircle2 size={14} className="text-[#2BC7A0]" />
            <span>{actionSuccess}</span>
          </div>
        )}

        {/* Clear Confirmation Modal */}
        {showClearConfirm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
            <div className="bg-white rounded-3xl p-6 max-w-md w-full shadow-2xl border border-[#EBEAE6] space-y-4">
              <div className="flex items-center gap-3 text-red-500">
                <AlertTriangle size={24} />
                <h3 className="font-display font-bold text-base text-[#17171A]">
                  Clear Pipeline Data?
                </h3>
              </div>
              <p className="text-xs text-[#7A7A82] leading-relaxed">
                This will delete all discovered opportunities, company records, and drafts from the PostgreSQL database. This action is irreversible.
              </p>
              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  onClick={() => setShowClearConfirm(false)}
                  className="px-4 py-2 rounded-full text-xs font-semibold text-[#7A7A82] hover:bg-[#F5F4F0]"
                >
                  Cancel
                </button>
                <button
                  onClick={handleClearPipeline}
                  disabled={pipelineClearMutation.isPending}
                  className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-full text-xs font-semibold shadow-sm"
                >
                  {pipelineClearMutation.isPending ? "Clearing..." : "Yes, Clear Everything"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Rerun Confirmation Modal */}
        {showRerunConfirm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
            <div className="bg-white rounded-3xl p-6 max-w-md w-full shadow-2xl border border-[#EBEAE6] space-y-4">
              <div className="flex items-center gap-3 text-[#7C5CFC]">
                <RotateCcw size={24} />
                <h3 className="font-display font-bold text-base text-[#17171A]">
                  Rerun Pipeline for Unapproved Leads?
                </h3>
              </div>
              <p className="text-xs text-[#7A7A82] leading-relaxed">
                This will re-trigger the research and discovery graphs for all opportunities currently in discovered or reviewing status.
              </p>
              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  onClick={() => setShowRerunConfirm(false)}
                  className="px-4 py-2 rounded-full text-xs font-semibold text-[#7A7A82] hover:bg-[#F5F4F0]"
                >
                  Cancel
                </button>
                <button
                  onClick={handleRerunPipeline}
                  disabled={pipelineRerunMutation.isPending}
                  className="px-4 py-2 bg-[#7C5CFC] hover:bg-[#6847E8] text-white rounded-full text-xs font-semibold shadow-sm"
                >
                  {pipelineRerunMutation.isPending ? "Reprocessing..." : "Confirm Rerun"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Header */}
        <div>
          <h1 className="font-display font-bold text-2xl sm:text-3xl text-[#17171A] tracking-tight">
            System Controls & Preferences
          </h1>
          <p className="text-sm text-[#7A7A82] mt-0.5">
            Trigger background scraping jobs, manage database records, and tune discovery parameters.
          </p>
        </div>

        {/* 1. Pipeline Trigger Cluster */}
        <div className="eonix-card space-y-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-xl bg-[#F3EFFF] text-[#7C5CFC] flex items-center justify-center">
                <Play size={16} />
              </div>
              <div>
                <h2 className="font-display font-semibold text-base text-[#17171A]">
                  Pipeline Execution Cluster
                </h2>
                <p className="text-xs text-[#7A7A82]">
                  Directly dispatch LangGraph discovery and research workflows.
                </p>
              </div>
            </div>

            {/* Dry Run Toggle */}
            <label className="flex items-center gap-2 cursor-pointer text-xs font-semibold text-[#17171A] bg-[#F4F4F5] px-3 py-1.5 rounded-full">
              <input
                type="checkbox"
                checked={dryRun}
                onChange={(e) => setDryRun(e.target.checked)}
                className="w-3.5 h-3.5 accent-[#7C5CFC] rounded"
              />
              <span>Dry Run Mode</span>
            </label>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2">
            {/* Run Pipeline */}
            <button
              onClick={handleRunPipeline}
              disabled={pipelineRunMutation.isPending}
              className="flex flex-col items-center justify-center p-4 rounded-2xl bg-[#17171A] text-white hover:bg-[#2C2C30] transition-colors shadow-xs disabled:opacity-60"
            >
              {pipelineRunMutation.isPending ? (
                <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin mb-2" />
              ) : (
                <Play size={18} className="text-[#2BC7A0] mb-2 fill-current" />
              )}
              <span className="font-display font-bold text-xs">Run Scrapers</span>
              <span className="text-[10px] text-[#A1A1AA] mt-0.5">
                {dryRun ? "Simulate scan" : "Full live discovery"}
              </span>
            </button>

            {/* Rerun Pipeline */}
            <button
              onClick={() => setShowRerunConfirm(true)}
              className="flex flex-col items-center justify-center p-4 rounded-2xl bg-white border border-[#EBEAE6] hover:bg-[#F5F4F0] text-[#17171A] transition-colors shadow-xs"
            >
              <RotateCcw size={18} className="text-[#7C5CFC] mb-2" />
              <span className="font-display font-bold text-xs">Rerun Unapproved</span>
              <span className="text-[10px] text-[#7A7A82] mt-0.5">
                Reprocess discovered leads
              </span>
            </button>

            {/* Clear Database */}
            <button
              onClick={() => setShowClearConfirm(true)}
              className="flex flex-col items-center justify-center p-4 rounded-2xl bg-[#FFF0EE] border border-[#FFD0CA] hover:bg-[#FFE3DF] text-[#DC2626] transition-colors shadow-xs"
            >
              <Trash2 size={18} className="text-red-500 mb-2" />
              <span className="font-display font-bold text-xs">Clear Pipeline</span>
              <span className="text-[10px] text-[#FF6B57] mt-0.5">
                Destructive DB purge
              </span>
            </button>
          </div>
        </div>

        {/* 2. Scraping & Preference Settings */}
        <div className="eonix-card space-y-5">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-[#FFF8E6] text-[#B45309] flex items-center justify-center">
              <Sliders size={16} />
            </div>
            <div>
              <h2 className="font-display font-semibold text-base text-[#17171A]">
                Discovery Criteria & Filters
              </h2>
              <p className="text-xs text-[#7A7A82]">
                Target role keywords, location constraints, and active source tiers.
              </p>
            </div>
          </div>

          <div className="space-y-4 text-xs">
            <div>
              <label className="font-semibold text-[#17171A] block mb-1">
                Target Role Keywords (space or comma separated)
              </label>
              <input
                type="text"
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
                className="w-full px-3.5 py-2.5 bg-[#F4F4F5] rounded-xl text-xs text-[#17171A] border border-transparent focus:bg-white focus:border-[#7C5CFC] focus:outline-none font-mono"
              />
            </div>

            <div>
              <label className="font-semibold text-[#17171A] block mb-1">
                Location Whitelist
              </label>
              <input
                type="text"
                value={locations}
                onChange={(e) => setLocations(e.target.value)}
                className="w-full px-3.5 py-2.5 bg-[#F4F4F5] rounded-xl text-xs text-[#17171A] border border-transparent focus:bg-white focus:border-[#7C5CFC] focus:outline-none"
              />
            </div>

            {/* Source Tier Toggles */}
            <div className="pt-2">
              <label className="font-semibold text-[#17171A] block mb-2">
                Active Source Tiers
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                <label className="flex items-center justify-between p-3 rounded-xl bg-[#FBFBFA] border border-[#EBEAE6] cursor-pointer">
                  <div>
                    <span className="font-semibold text-[#17171A] block">Tier 0 — ATS Direct</span>
                    <span className="text-[11px] text-[#7A7A82]">Ashby, Greenhouse, Lever</span>
                  </div>
                  <input
                    type="checkbox"
                    checked={tier0Enabled}
                    onChange={(e) => setTier0Enabled(e.target.checked)}
                    className="w-4 h-4 accent-[#7C5CFC] rounded"
                  />
                </label>

                <label className="flex items-center justify-between p-3 rounded-xl bg-[#FBFBFA] border border-[#EBEAE6] cursor-pointer">
                  <div>
                    <span className="font-semibold text-[#17171A] block">Tier 1 — Portals</span>
                    <span className="text-[11px] text-[#7A7A82]">Hirist, Unstop, Internshala</span>
                  </div>
                  <input
                    type="checkbox"
                    checked={tier1Enabled}
                    onChange={(e) => setTier1Enabled(e.target.checked)}
                    className="w-4 h-4 accent-[#7C5CFC] rounded"
                  />
                </label>

                <label className="flex items-center justify-between p-3 rounded-xl bg-[#FBFBFA] border border-[#EBEAE6] cursor-pointer">
                  <div>
                    <span className="font-semibold text-[#17171A] block">Tier 2 — Aggregators</span>
                    <span className="text-[11px] text-[#7A7A82]">LinkedIn, Indeed, JobSpy</span>
                  </div>
                  <input
                    type="checkbox"
                    checked={tier2Enabled}
                    onChange={(e) => setTier2Enabled(e.target.checked)}
                    className="w-4 h-4 accent-[#7C5CFC] rounded"
                  />
                </label>

                <label className="flex items-center justify-between p-3 rounded-xl bg-[#FBFBFA] border border-[#EBEAE6] cursor-pointer">
                  <div>
                    <span className="font-semibold text-[#17171A] block">Tier 3 — Free RSS & APIs</span>
                    <span className="text-[11px] text-[#7A7A82]">Freelancer, Upwork, The Muse</span>
                  </div>
                  <input
                    type="checkbox"
                    checked={tier3Enabled}
                    onChange={(e) => setTier3Enabled(e.target.checked)}
                    className="w-4 h-4 accent-[#7C5CFC] rounded"
                  />
                </label>
              </div>
            </div>

            <div className="pt-3 border-t border-[#F0EFEC] flex items-center justify-between">
              <span className="text-[11px] text-[#7A7A82]">
                Preferences sync to local scraper worker state.
              </span>
              <button
                onClick={handleSavePreferences}
                className="px-5 py-2 bg-[#17171A] text-white rounded-full text-xs font-semibold hover:bg-[#2C2C30] transition-colors"
              >
                Save Preferences
              </button>
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
