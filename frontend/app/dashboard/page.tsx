"use client";

import { useMemo } from "react";
import Link from "next/link";
import { motion } from "motion/react";
import {
  Briefcase,
  Eye,
  Send,
  Building2,
  Calendar,
  Layers,
  ArrowUpRight,
  TrendingUp,
  Clock,
  Sparkles,
  ChevronRight,
  CheckCircle2,
  XCircle,
  Gem,
} from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
  PieChart,
  Pie,
} from "recharts";
import { AppLayout } from "@/components/AppLayout";
import { useDashboardStats, useRecentActivity } from "@/lib/api";

const STAGE_COLORS: Record<string, { solid: string; hatch: string; tint: string; text: string }> = {
  Discovered: { solid: "#7A7A82", hatch: "#7A7A82", tint: "#F4F4F5", text: "#52525B" },
  Reviewing: { solid: "#7C5CFC", hatch: "url(#hatchPatternPurple)", tint: "#F3EFFF", text: "#7C5CFC" },
  Applied: { solid: "#FFC94A", hatch: "url(#hatchPatternYellow)", tint: "#FFF8E6", text: "#B45309" },
  Interviewing: { solid: "#5B8DEF", hatch: "url(#hatchPatternBlue)", tint: "#EFF4FE", text: "#2563EB" },
  Offer: { solid: "#2BC7A0", hatch: "url(#hatchPatternTeal)", tint: "#EAF9F5", text: "#059669" },
  Rejected: { solid: "#FF6B57", hatch: "url(#hatchPatternCoral)", tint: "#FFF0EE", text: "#DC2626" },
};

export default function DashboardPage() {
  const { data: stats, isLoading: statsLoading } = useDashboardStats();
  const { data: activities, isLoading: activityLoading } = useRecentActivity();

  // Funnel chart data mapped directly from stats.by_stage
  const funnelData = useMemo(() => {
    const byStage = stats?.by_stage || {
      discovered: 0,
      reviewing: 0,
      applied: 0,
      interviewing: 0,
      offer: 0,
      rejected: 0,
    };

    return [
      { name: "Discovered", count: byStage.discovered || 0, color: STAGE_COLORS.Discovered.solid, fill: STAGE_COLORS.Discovered.solid },
      { name: "Reviewing", count: byStage.reviewing || 0, color: STAGE_COLORS.Reviewing.solid, fill: STAGE_COLORS.Reviewing.hatch }, // Highlighted series with hatch pattern
      { name: "Applied", count: byStage.applied || 0, color: STAGE_COLORS.Applied.solid, fill: STAGE_COLORS.Applied.solid },
      { name: "Interviewing", count: byStage.interviewing || 0, color: STAGE_COLORS.Interviewing.solid, fill: STAGE_COLORS.Interviewing.solid },
      { name: "Offer", count: byStage.offer || 0, color: STAGE_COLORS.Offer.solid, fill: STAGE_COLORS.Offer.solid },
      { name: "Rejected", count: byStage.rejected || 0, color: STAGE_COLORS.Rejected.solid, fill: STAGE_COLORS.Rejected.solid },
    ];
  }, [stats]);

  // Source Tier Data
  const tierData = useMemo(() => {
    const byTier = stats?.by_source_tier || {
      "Tier 0 (ATS)": 0,
      "Tier 1 (Portals)": 0,
      "Tier 2 (Aggregators)": 0,
      "Tier 3 (APIs & RSS)": 0,
    };

    const total = stats?.total_opportunities || 1;
    return [
      {
        tier: "Tier 0 (ATS)",
        desc: "Ashby, Greenhouse, Lever, SmartRecruiters",
        count: byTier["Tier 0 (ATS)"] || 0,
        pct: Math.round(((byTier["Tier 0 (ATS)"] || 0) / total) * 100),
        color: "#7C5CFC",
        hatch: true,
      },
      {
        tier: "Tier 1 (Portals)",
        desc: "Hirist, Unstop, Internshala",
        count: byTier["Tier 1 (Portals)"] || 0,
        pct: Math.round(((byTier["Tier 1 (Portals)"] || 0) / total) * 100),
        color: "#2BC7A0",
        hatch: false,
      },
      {
        tier: "Tier 2 (Aggregators)",
        desc: "LinkedIn, Indeed, JobSpy",
        count: byTier["Tier 2 (Aggregators)"] || 0,
        pct: Math.round(((byTier["Tier 2 (Aggregators)"] || 0) / total) * 100),
        color: "#FFC94A",
        hatch: false,
      },
      {
        tier: "Tier 3 (APIs & RSS)",
        desc: "Arbeitnow, The Muse, Freelancer, Upwork",
        count: byTier["Tier 3 (APIs & RSS)"] || 0,
        pct: Math.round(((byTier["Tier 3 (APIs & RSS)"] || 0) / total) * 100),
        color: "#5B8DEF",
        hatch: false,
      },
    ];
  }, [stats]);

  // Donut split data (Internships vs Freelance)
  const donutData = useMemo(() => {
    const internships = stats?.total_internships ?? (stats?.total_opportunities || 0);
    const freelance = stats?.total_freelance ?? 0;
    return [
      { name: "Internships", value: internships, color: "#7C5CFC" },
      { name: "Freelance", value: freelance, color: "#2BC7A0" },
    ];
  }, [stats]);

  return (
    <AppLayout>
      <div className="space-y-7 pb-12">
        {/* Page Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h1 className="font-display font-bold text-2xl sm:text-3xl text-[#17171A] tracking-tight">
              Executive Dashboard
            </h1>
            <p className="text-sm text-[#7A7A82] mt-0.5">
              Live telemetry, pipeline funnel conversion, and source tier telemetry.
            </p>
          </div>
          <div className="flex items-center gap-2.5">
            <Link
              href="/internships"
              className="inline-flex items-center gap-1.5 px-4 py-2 bg-[#17171A] text-white rounded-full text-xs font-semibold shadow-sm hover:bg-[#2C2C30] transition-colors"
            >
              <span>View Kanban Board</span>
              <ArrowUpRight size={14} />
            </Link>
          </div>
        </div>

        {/* 1. KPI Metric Row */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {/* Card 1: Total Opportunities */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.05 }}
            className="eonix-card eonix-card-hover group"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-[#7A7A82]">
                Total Discovered
              </span>
              <div className="w-8 h-8 rounded-xl bg-[#F4F4F5] flex items-center justify-center text-[#17171A] group-hover:bg-[#17171A] group-hover:text-white transition-colors">
                <Briefcase size={16} />
              </div>
            </div>
            <div className="mt-3 flex items-baseline gap-2">
              <span className="font-display font-bold text-3xl sm:text-4xl text-[#17171A] tabular-nums">
                {statsLoading ? "—" : stats?.total_opportunities ?? 0}
              </span>
              <span className="text-xs font-medium text-[#2BC7A0] bg-[#EAF9F5] px-2 py-0.5 rounded-full">
                Active
              </span>
            </div>
            <p className="text-xs text-[#7A7A82] mt-2">
              Across all scrapers & active sources
            </p>
          </motion.div>

          {/* Card 2: Pending Review */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.1 }}
            className="eonix-card eonix-card-hover group"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-[#7A7A82]">
                Reviewing
              </span>
              <div className="w-8 h-8 rounded-xl bg-[#F3EFFF] flex items-center justify-center text-[#7C5CFC] group-hover:bg-[#7C5CFC] group-hover:text-white transition-colors">
                <Eye size={16} />
              </div>
            </div>
            <div className="mt-3 flex items-baseline gap-2">
              <span className="font-display font-bold text-3xl sm:text-4xl text-[#7C5CFC] tabular-nums">
                {statsLoading ? "—" : stats?.pending_review ?? stats?.by_stage?.reviewing ?? 0}
              </span>
              <span className="text-xs font-medium text-[#7C5CFC] bg-[#F3EFFF] px-2 py-0.5 rounded-full">
                Focus
              </span>
            </div>
            <p className="text-xs text-[#7A7A82] mt-2">
              Opportunities ready for resume tailoring
            </p>
          </motion.div>

          {/* Card 3: Applied / Outreach */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.15 }}
            className="eonix-card eonix-card-hover group"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-[#7A7A82]">
                Applied & Sent
              </span>
              <div className="w-8 h-8 rounded-xl bg-[#FFF8E6] flex items-center justify-center text-[#B45309] group-hover:bg-[#FFC94A] group-hover:text-[#17171A] transition-colors">
                <Send size={16} />
              </div>
            </div>
            <div className="mt-3 flex items-baseline gap-2">
              <span className="font-display font-bold text-3xl sm:text-4xl text-[#17171A] tabular-nums">
                {statsLoading ? "—" : stats?.batch_ready ?? stats?.by_stage?.applied ?? 0}
              </span>
              <span className="text-xs font-medium text-[#B45309] bg-[#FFF8E6] px-2 py-0.5 rounded-full">
                Sent
              </span>
            </div>
            <p className="text-xs text-[#7A7A82] mt-2">
              Applications submitted or emails dispatched
            </p>
          </motion.div>

          {/* Card 4: Companies */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.2 }}
            className="eonix-card eonix-card-hover group"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-[#7A7A82]">
                Target Companies
              </span>
              <div className="w-8 h-8 rounded-xl bg-[#EFF4FE] flex items-center justify-center text-[#5B8DEF] group-hover:bg-[#5B8DEF] group-hover:text-white transition-colors">
                <Building2 size={16} />
              </div>
            </div>
            <div className="mt-3 flex items-baseline gap-2">
              <span className="font-display font-bold text-3xl sm:text-4xl text-[#17171A] tabular-nums">
                {statsLoading ? "—" : stats?.total_companies ?? 0}
              </span>
              <span className="text-xs font-medium text-[#5B8DEF] bg-[#EFF4FE] px-2 py-0.5 rounded-full">
                Profiles
              </span>
            </div>
            <p className="text-xs text-[#7A7A82] mt-2">
              Aggregated organization dossiers
            </p>
          </motion.div>
        </div>

        {/* Quick Triage & Navigation Banner */}
        <div className="eonix-card py-3 px-5 bg-gradient-to-r from-white via-white to-[#F8F7F4] border border-[#EBEAE6] flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3 shadow-2xs">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-[#17171A] flex items-center justify-center text-white">
              <Sparkles size={15} className="text-[#7C5CFC]" />
            </div>
            <div>
              <span className="font-display font-bold text-xs text-[#17171A] block">
                Workflow Quick Triage
              </span>
              <span className="text-[11px] text-[#7A7A82]">
                Jump straight into focused queues or trigger background discovery.
              </span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Link
              href="/internships"
              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-[#17171A] text-white text-xs font-semibold hover:bg-[#2C2C30] transition-colors"
            >
              <span>Discovered Queue ({stats?.by_stage?.discovered || 0})</span>
            </Link>

            <Link
              href="/internships"
              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-[#F3EFFF] text-[#7C5CFC] text-xs font-semibold hover:bg-[#7C5CFC] hover:text-white transition-colors"
            >
              <span>In Review ({stats?.by_stage?.reviewing || 0})</span>
            </Link>

            <Link
              href="/pipeline"
              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-[#7C5CFC] text-white text-xs font-semibold hover:bg-[#6847E8] transition-colors"
            >
              <Sparkles size={12} />
              <span>Scraper Pipeline</span>
            </Link>
          </div>
        </div>

        {/* 2. Main Visual Charts Grid (Funnel & Source Tiers) */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Pipeline Conversion Funnel (2 Cols) */}
          <div className="lg:col-span-2 eonix-card relative">
            {/* Eonix signature floating pill badge */}
            <div className="eonix-floating-pill text-[#17171A] border border-[#EBEAE6]">
              <Calendar size={13} className="text-[#7C5CFC]" />
              <span>Pipeline · 2026</span>
            </div>

            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="font-display font-semibold text-base text-[#17171A]">
                  Pipeline Stage Funnel
                </h2>
                <p className="text-xs text-[#7A7A82]">
                  Opportunities grouped by Kanban status (capsule blobs, Reviewing hatched)
                </p>
              </div>
            </div>

            {/* Recharts Capsule Bar Chart */}
            <div className="h-64 w-full pt-2">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={funnelData}
                  margin={{ top: 10, right: 10, left: -20, bottom: 20 }}
                  barSize={38}
                >
                  <XAxis
                    dataKey="name"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: "#7A7A82", fontSize: 11, fontWeight: 500 }}
                    dy={8}
                  />
                  <YAxis
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: "#7A7A82", fontSize: 11 }}
                    allowDecimals={false}
                  />
                  <Tooltip
                    cursor={{ fill: "rgba(240, 239, 236, 0.4)", radius: 16 }}
                    content={({ active, payload }) => {
                      if (active && payload && payload.length) {
                        const d = payload[0].payload;
                        return (
                          <div className="bg-[#17171A] text-white px-3.5 py-2 rounded-2xl shadow-xl text-xs space-y-0.5 border border-white/10">
                            <p className="font-semibold text-white">{d.name}</p>
                            <p className="text-[#A1A1AA] font-mono">
                              Count: <span className="text-white font-bold">{d.count}</span>
                            </p>
                          </div>
                        );
                      }
                      return null;
                    }}
                  />
                  <Bar
                    dataKey="count"
                    radius={[999, 999, 999, 999]}
                    animationDuration={800}
                  >
                    {funnelData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Stage Quick Indicator Pills */}
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 mt-4 pt-4 border-t border-[#F0EFEC]">
              {funnelData.map((item) => {
                const conf = STAGE_COLORS[item.name] || STAGE_COLORS.Discovered;
                return (
                  <div
                    key={item.name}
                    className="flex flex-col items-center justify-center p-2 rounded-2xl transition-transform hover:scale-105"
                    style={{ backgroundColor: conf.tint }}
                  >
                    <span className="text-[11px] font-medium" style={{ color: conf.text }}>
                      {item.name}
                    </span>
                    <span className="font-mono font-bold text-sm text-[#17171A]">
                      {item.count}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Opportunity Split Donut (1 Col) */}
          <div className="eonix-card relative flex flex-col justify-between">
            <div className="eonix-floating-pill text-[#17171A] border border-[#EBEAE6]">
              <Sparkles size={13} className="text-[#2BC7A0]" />
              <span>Track Distribution</span>
            </div>

            <div>
              <h2 className="font-display font-semibold text-base text-[#17171A]">
                Opportunity Distribution
              </h2>
              <p className="text-xs text-[#7A7A82]">
                Internships vs Freelance feeds
              </p>
            </div>

            <div className="relative h-48 w-full flex items-center justify-center my-2">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Tooltip
                    content={({ active, payload }) => {
                      if (active && payload && payload.length) {
                        const d = payload[0].payload;
                        return (
                          <div className="bg-[#17171A] text-white px-3 py-1.5 rounded-xl shadow-lg text-xs font-mono">
                            {d.name}: {d.value}
                          </div>
                        );
                      }
                      return null;
                    }}
                  />
                  <Pie
                    data={donutData}
                    innerRadius={55}
                    outerRadius={75}
                    paddingAngle={6}
                    dataKey="value"
                    animationDuration={800}
                  >
                    {donutData.map((entry, index) => (
                      <Cell key={`donut-cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <span className="font-display font-bold text-2xl text-[#17171A] tabular-nums">
                  {stats?.total_opportunities ?? 0}
                </span>
                <span className="text-[10px] uppercase font-semibold text-[#7A7A82] tracking-wider">
                  Total
                </span>
              </div>
            </div>

            <div className="space-y-2 pt-2 border-t border-[#F0EFEC]">
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#7C5CFC]" />
                  <span className="font-medium text-[#17171A]">Internships</span>
                </div>
                <span className="font-mono font-semibold text-[#17171A]">
                  {stats?.total_internships ?? (stats?.total_opportunities || 0)}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#2BC7A0]" />
                  <span className="font-medium text-[#17171A]">Freelance</span>
                </div>
                <span className="font-mono font-semibold text-[#17171A]">
                  {stats?.total_freelance ?? 0}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* 3. Source Tier Breakdown & Recent Activity */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Source Tier Breakdown (2 Cols) */}
          <div className="lg:col-span-2 eonix-card relative">
            <div className="eonix-floating-pill text-[#17171A] border border-[#EBEAE6]">
              <Layers size={13} className="text-[#5B8DEF]" />
              <span>Multi-Source Health</span>
            </div>

            <div className="mb-4">
              <h2 className="font-display font-semibold text-base text-[#17171A]">
                Source Tier Breakdown
              </h2>
              <p className="text-xs text-[#7A7A82]">
                Telemetry from ATS scrapers, portals, aggregators, and free RSS feeds
              </p>
            </div>

            <div className="space-y-4 pt-2">
              {tierData.map((item) => (
                <div key={item.tier} className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs">
                    <div>
                      <span className="font-semibold text-[#17171A]">{item.tier}</span>
                      <span className="text-[#7A7A82] ml-2 text-[11px] hidden sm:inline">
                        ({item.desc})
                      </span>
                    </div>
                    <div className="flex items-center gap-2 font-mono">
                      <span className="text-[#7A7A82]">{item.count} items</span>
                      <span className="font-bold text-[#17171A] bg-[#F4F4F5] px-2 py-0.5 rounded-full text-[11px]">
                        {item.pct}%
                      </span>
                    </div>
                  </div>

                  {/* Capsule Progress Bar */}
                  <div className="h-3.5 w-full bg-[#F0EFEC] rounded-full overflow-hidden p-0.5">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${Math.max(item.pct, item.count > 0 ? 5 : 0)}%` }}
                      transition={{ duration: 0.6, ease: "easeOut" }}
                      className="h-full rounded-full"
                      style={{
                        backgroundColor: item.hatch ? undefined : item.color,
                        backgroundImage: item.hatch ? "url(#hatchPatternPurple)" : undefined,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>

            {/* Active Sources Chips */}
            <div className="mt-6 pt-4 border-t border-[#F0EFEC] flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold text-[#7A7A82]">Scraper feeds:</span>
              {stats?.by_source && Object.keys(stats.by_source).length > 0 ? (
                Object.entries(stats.by_source).map(([src, count]) => (
                  <span
                    key={src}
                    className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#FFFFFF] border border-[#EBEAE6] text-xs font-medium text-[#17171A] shadow-2xs"
                  >
                    <span className="w-1.5 h-1.5 rounded-full bg-[#2BC7A0]" />
                    <span className="capitalize">{src}</span>
                    <span className="font-mono text-[#7A7A82] text-[11px]">({count})</span>
                  </span>
                ))
              ) : (
                <span className="text-xs text-[#7A7A82] italic">Waiting for discovery scan</span>
              )}
            </div>
          </div>

          {/* Recent Activity Feed (1 Col) */}
          <div className="eonix-card relative flex flex-col">
            <div className="eonix-floating-pill text-[#17171A] border border-[#EBEAE6]">
              <Clock size={13} className="text-[#FF6B57]" />
              <span>Realtime Feed</span>
            </div>

            <div className="mb-3">
              <h2 className="font-display font-semibold text-base text-[#17171A]">
                Recent Activity
              </h2>
              <p className="text-xs text-[#7A7A82]">
                Live opportunity discoveries & events
              </p>
            </div>

            <div className="flex-1 overflow-y-auto max-h-[320px] space-y-3 pr-1">
              {activityLoading ? (
                <div className="py-8 text-center text-xs text-[#7A7A82]">Loading activity stream...</div>
              ) : !activities || activities.length === 0 ? (
                <div className="py-8 text-center text-xs text-[#7A7A82]">
                  No recent activity recorded yet.
                </div>
              ) : (
                activities.map((act) => {
                  const stageName = act.stage ? act.stage.charAt(0).toUpperCase() + act.stage.slice(1) : "Discovered";
                  const stageConf = STAGE_COLORS[stageName] || STAGE_COLORS.Discovered;

                  return (
                    <div
                      key={act.id}
                      className="p-3 rounded-2xl bg-[#FBFBFA] border border-[#EBEAE6] transition-all hover:bg-white hover:shadow-xs group"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span
                          className="px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider"
                          style={{ backgroundColor: stageConf.tint, color: stageConf.text }}
                        >
                          {stageName}
                        </span>
                        <span className="font-mono text-[11px] text-[#7A7A82]">
                          {act.timestamp ? act.timestamp.slice(11, 16) || "Just now" : "Recent"}
                        </span>
                      </div>
                      <p className="text-xs font-semibold text-[#17171A] mt-1.5 line-clamp-1">
                        {act.message}
                      </p>
                      <div className="flex items-center justify-between mt-2 pt-1 border-t border-[#F0EFEC]/60">
                        <span className="text-[10px] text-[#7A7A82] uppercase font-mono">
                          {act.source || "Web"}
                        </span>
                        <Link
                          href={`/opportunities/${act.opportunityId}`}
                          className="text-[11px] font-semibold text-[#7C5CFC] flex items-center gap-0.5 group-hover:translate-x-0.5 transition-transform"
                        >
                          <span>Inspect</span>
                          <ChevronRight size={12} />
                        </Link>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
