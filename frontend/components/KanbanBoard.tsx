"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import {
  DndContext,
  DragOverlay,
  closestCorners,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragStartEvent,
  DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useQueryState } from "nuqs";
import {
  Search,
  MapPin,
  ExternalLink,
  MoreVertical,
  Sparkles,
  ArrowRight,
  AlertCircle,
  ShieldCheck,
  LayoutGrid,
  ListFilter,
  Columns,
  CheckCircle2,
  XCircle,
  Clock,
  Briefcase,
  SlidersHorizontal,
  FileText,
  Building2,
  DollarSign,
  ChevronRight,
  TrendingUp,
  Inbox,
  Send,
  Award,
} from "lucide-react";
import { Opportunity, ApplicationStage, SourceType } from "@/lib/types";
import { useOpportunities, useUpdateOpportunityStage } from "@/lib/api";

const KANBAN_COLUMNS: Array<{
  id: ApplicationStage;
  title: string;
  tint: string;
  border: string;
  accent: string;
  badgeBg: string;
  badgeText: string;
  icon: typeof Inbox;
}> = [
  {
    id: "discovered",
    title: "Discovered Queue",
    tint: "#F4F4F5",
    border: "#E4E4E7",
    accent: "#7A7A82",
    badgeBg: "#E4E4E7",
    badgeText: "#3F3F46",
    icon: Inbox,
  },
  {
    id: "reviewing",
    title: "In Review",
    tint: "#F3EFFF",
    border: "#E0D7FE",
    accent: "#7C5CFC",
    badgeBg: "#EDE7FE",
    badgeText: "#6542EC",
    icon: Clock,
  },
  {
    id: "applied",
    title: "Applied / Ongoing",
    tint: "#FFF8E6",
    border: "#FDE68A",
    accent: "#FFC94A",
    badgeBg: "#FEF3C7",
    badgeText: "#92400E",
    icon: Send,
  },
  {
    id: "interviewing",
    title: "Interviewing",
    tint: "#EFF4FE",
    border: "#BFDBFE",
    accent: "#5B8DEF",
    badgeBg: "#DBEAFE",
    badgeText: "#1D4ED8",
    icon: Briefcase,
  },
  {
    id: "offer",
    title: "Offer / Closed",
    tint: "#EAF9F5",
    border: "#A7F3D0",
    accent: "#2BC7A0",
    badgeBg: "#D1FAE5",
    badgeText: "#047857",
    icon: Award,
  },
];

// Map arbitrary status into one of the canonical column IDs
function normalizeToColumnId(stage: string | undefined): ApplicationStage {
  if (!stage) return "discovered";
  const s = stage.toLowerCase().trim();
  if (s === "reviewing" || s === "pending_review") return "reviewing";
  if (s === "applied" || s === "batch_ready" || s === "ongoing") return "applied";
  if (s === "interviewing" || s === "interview_scheduled") return "interviewing";
  if (s === "offer" || s === "accepted" || s === "rejected" || s === "closed" || s === "cancelled") return "offer";
  return "discovered";
}

interface KanbanBoardProps {
  sourceType?: SourceType;
  title?: string;
  description?: string;
}

export function KanbanBoard({
  sourceType,
  title = "Application Pipeline",
  description = "Organize, triage, and manage opportunities across each stage of your application lifecycle.",
}: KanbanBoardProps) {
  // Query Filter State
  const [searchQuery, setSearchQuery] = useQueryState("q", { defaultValue: "" });
  const [tierFilter, setTierFilter] = useQueryState("tier", { defaultValue: "all" });
  const [activeStageTab, setActiveStageTab] = useState<string>("discovered");
  const [viewMode, setViewMode] = useState<"grid" | "table" | "kanban">("grid");
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [paidOnly, setPaidOnly] = useState(false);
  const [sortBy, setSortBy] = useState<"match" | "date" | "company">("match");

  // TanStack Query Hooks
  const { data: opportunities = [], isLoading, error } = useOpportunities({
    source_type: sourceType,
  });
  const updateStageMutation = useUpdateOpportunityStage();

  // Drag and Drop Sensors
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 5 },
    }),
    useSensor(KeyboardSensor)
  );

  const [activeId, setActiveId] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Group items by normalized column ID
  const columnItems = useMemo(() => {
    const grouped: Record<ApplicationStage, Opportunity[]> = {
      discovered: [],
      reviewing: [],
      applied: [],
      interviewing: [],
      offer: [],
      rejected: [],
      ongoing: [],
      closed: [],
      cancelled: [],
    };

    opportunities.forEach((item) => {
      const col = normalizeToColumnId(item.stage || item.status);
      grouped[col].push(item);
    });

    return grouped;
  }, [opportunities]);

  // Filtered & Sorted items for active tab / grid view
  const filteredList = useMemo(() => {
    return opportunities.filter((item) => {
      // Stage tab filter
      if (activeStageTab !== "all") {
        const col = normalizeToColumnId(item.stage || item.status);
        if (col !== activeStageTab) return false;
      }

      // Search filter
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchRole = item.role?.toLowerCase().includes(q);
        const matchCompany = item.company?.toLowerCase().includes(q);
        const matchSkills = item.skills?.some((s) => s.toLowerCase().includes(q));
        if (!matchRole && !matchCompany && !matchSkills) return false;
      }

      // Tier filter
      if (tierFilter !== "all" && item.tier !== tierFilter) {
        return false;
      }

      // Remote filter
      if (remoteOnly && !item.is_remote) return false;

      // Paid filter
      if (paidOnly && !item.is_paid) return false;

      return true;
    }).sort((a, b) => {
      if (sortBy === "match") return (b.matchScore || 0) - (a.matchScore || 0);
      if (sortBy === "company") return a.company.localeCompare(b.company);
      return new Date(b.date).getTime() - new Date(a.date).getTime();
    });
  }, [opportunities, activeStageTab, searchQuery, tierFilter, remoteOnly, paidOnly, sortBy]);

  // Stage change handler
  const handleStageChange = async (id: string, stage: ApplicationStage) => {
    try {
      await updateStageMutation.mutateAsync({ id, stage });
      showToast(`Updated to ${stage.charAt(0).toUpperCase() + stage.slice(1)}`);
    } catch {
      showToast("Update failed. Please retry.");
    }
  };

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3000);
  };

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id as string);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    setActiveId(null);
    if (!over) return;

    const draggedOpportunity = opportunities.find((o) => o.id === active.id);
    if (!draggedOpportunity) return;

    let targetStage: ApplicationStage | null = null;
    const overIdStr = String(over.id);

    if (KANBAN_COLUMNS.some((col) => col.id === overIdStr)) {
      targetStage = overIdStr as ApplicationStage;
    } else {
      const overOpportunity = opportunities.find((o) => o.id === overIdStr);
      if (overOpportunity) {
        targetStage = normalizeToColumnId(overOpportunity.stage || overOpportunity.status);
      }
    }

    if (targetStage) {
      const currentStage = normalizeToColumnId(
        draggedOpportunity.stage || draggedOpportunity.status
      );
      if (currentStage !== targetStage) {
        handleStageChange(draggedOpportunity.id, targetStage);
      }
    }
  };

  const activeOpportunity = useMemo(
    () => opportunities.find((o) => o.id === activeId),
    [opportunities, activeId]
  );

  return (
    <div className="space-y-6 w-full pb-16">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#17171A] text-white px-5 py-3 rounded-full text-xs font-semibold shadow-2xl flex items-center gap-2 border border-white/10 animate-bounce">
          <Sparkles size={14} className="text-[#7C5CFC]" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Top Header & Triage Bar */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div>
          <h1 className="font-display font-bold text-2xl sm:text-3xl text-[#17171A] tracking-tight">
            {title}
          </h1>
          <p className="text-sm text-[#7A7A82] mt-0.5">{description}</p>
        </div>

        {/* View Mode & Actions */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* View Mode Switcher */}
          <div className="flex items-center p-1 bg-white border border-[#EBEAE6] rounded-full shadow-2xs">
            <button
              onClick={() => setViewMode("grid")}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-semibold transition-all ${
                viewMode === "grid"
                  ? "bg-[#17171A] text-white shadow-xs"
                  : "text-[#7A7A82] hover:text-[#17171A]"
              }`}
            >
              <LayoutGrid size={13} />
              <span>Cards Queue</span>
            </button>

            <button
              onClick={() => setViewMode("table")}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-semibold transition-all ${
                viewMode === "table"
                  ? "bg-[#17171A] text-white shadow-xs"
                  : "text-[#7A7A82] hover:text-[#17171A]"
              }`}
            >
              <ListFilter size={13} />
              <span>Table</span>
            </button>

            <button
              onClick={() => setViewMode("kanban")}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-semibold transition-all ${
                viewMode === "kanban"
                  ? "bg-[#17171A] text-white shadow-xs"
                  : "text-[#7A7A82] hover:text-[#17171A]"
              }`}
            >
              <Columns size={13} />
              <span>5-Stage Board</span>
            </button>
          </div>

          <Link
            href="/pipeline"
            className="flex items-center gap-1.5 px-4 py-2 rounded-full bg-[#7C5CFC] text-white text-xs font-semibold shadow-sm hover:bg-[#6847E8] transition-colors"
          >
            <Sparkles size={13} />
            <span>Discover More</span>
          </Link>
        </div>
      </div>

      {/* Stage Focus Tabs (Organized Triage Queues) */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 no-scrollbar">
        <button
          onClick={() => setActiveStageTab("discovered")}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-2xl text-xs font-semibold whitespace-nowrap transition-all border ${
            activeStageTab === "discovered"
              ? "bg-[#17171A] text-white border-[#17171A] shadow-sm"
              : "bg-white text-[#17171A] border-[#EBEAE6] hover:bg-[#F5F4F0]"
          }`}
        >
          <Inbox size={14} className={activeStageTab === "discovered" ? "text-[#FFC94A]" : "text-[#7A7A82]"} />
          <span>Discovered Queue</span>
          <span className={`px-2 py-0.5 rounded-full text-[11px] font-mono ${
            activeStageTab === "discovered" ? "bg-white/20 text-white" : "bg-[#F4F4F5] text-[#17171A]"
          }`}>
            {columnItems.discovered.length}
          </span>
        </button>

        <button
          onClick={() => setActiveStageTab("reviewing")}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-2xl text-xs font-semibold whitespace-nowrap transition-all border ${
            activeStageTab === "reviewing"
              ? "bg-[#17171A] text-white border-[#17171A] shadow-sm"
              : "bg-white text-[#17171A] border-[#EBEAE6] hover:bg-[#F5F4F0]"
          }`}
        >
          <Clock size={14} className={activeStageTab === "reviewing" ? "text-[#7C5CFC]" : "text-[#7C5CFC]"} />
          <span>In Review</span>
          <span className={`px-2 py-0.5 rounded-full text-[11px] font-mono ${
            activeStageTab === "reviewing" ? "bg-white/20 text-white" : "bg-[#F4F4F5] text-[#17171A]"
          }`}>
            {columnItems.reviewing.length}
          </span>
        </button>

        <button
          onClick={() => setActiveStageTab("applied")}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-2xl text-xs font-semibold whitespace-nowrap transition-all border ${
            activeStageTab === "applied"
              ? "bg-[#17171A] text-white border-[#17171A] shadow-sm"
              : "bg-white text-[#17171A] border-[#EBEAE6] hover:bg-[#F5F4F0]"
          }`}
        >
          <Send size={14} className={activeStageTab === "applied" ? "text-[#FFC94A]" : "text-[#FFC94A]"} />
          <span>Applied / Ongoing</span>
          <span className={`px-2 py-0.5 rounded-full text-[11px] font-mono ${
            activeStageTab === "applied" ? "bg-white/20 text-white" : "bg-[#F4F4F5] text-[#17171A]"
          }`}>
            {columnItems.applied.length}
          </span>
        </button>

        <button
          onClick={() => setActiveStageTab("interviewing")}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-2xl text-xs font-semibold whitespace-nowrap transition-all border ${
            activeStageTab === "interviewing"
              ? "bg-[#17171A] text-white border-[#17171A] shadow-sm"
              : "bg-white text-[#17171A] border-[#EBEAE6] hover:bg-[#F5F4F0]"
          }`}
        >
          <Briefcase size={14} className={activeStageTab === "interviewing" ? "text-[#5B8DEF]" : "text-[#5B8DEF]"} />
          <span>Interviewing</span>
          <span className={`px-2 py-0.5 rounded-full text-[11px] font-mono ${
            activeStageTab === "interviewing" ? "bg-white/20 text-white" : "bg-[#F4F4F5] text-[#17171A]"
          }`}>
            {columnItems.interviewing.length}
          </span>
        </button>

        <button
          onClick={() => setActiveStageTab("offer")}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-2xl text-xs font-semibold whitespace-nowrap transition-all border ${
            activeStageTab === "offer"
              ? "bg-[#17171A] text-white border-[#17171A] shadow-sm"
              : "bg-white text-[#17171A] border-[#EBEAE6] hover:bg-[#F5F4F0]"
          }`}
        >
          <Award size={14} className={activeStageTab === "offer" ? "text-[#2BC7A0]" : "text-[#2BC7A0]"} />
          <span>Offers & Closed</span>
          <span className={`px-2 py-0.5 rounded-full text-[11px] font-mono ${
            activeStageTab === "offer" ? "bg-white/20 text-white" : "bg-[#F4F4F5] text-[#17171A]"
          }`}>
            {columnItems.offer.length}
          </span>
        </button>

        <button
          onClick={() => setActiveStageTab("all")}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-2xl text-xs font-semibold whitespace-nowrap transition-all border ${
            activeStageTab === "all"
              ? "bg-[#17171A] text-white border-[#17171A] shadow-sm"
              : "bg-white text-[#7A7A82] border-[#EBEAE6] hover:bg-[#F5F4F0]"
          }`}
        >
          <span>All ({opportunities.length})</span>
        </button>
      </div>

      {/* Search & Filter Bar */}
      <div className="eonix-card py-3 px-4 flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3 border border-[#EBEAE6]">
        {/* Search Input */}
        <div className="relative flex-1">
          <Search
            size={15}
            className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#7A7A82]"
          />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search role, company, or skills (e.g. Python, Docker, Stripe)..."
            className="w-full pl-9 pr-4 py-2 bg-[#F4F4F5] rounded-xl text-xs text-[#17171A] placeholder-[#7A7A82] border border-transparent focus:bg-white focus:border-[#7C5CFC] focus:outline-none transition-all"
          />
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Source Tier Filter */}
          <select
            value={tierFilter}
            onChange={(e) => setTierFilter(e.target.value)}
            className="px-3 py-2 bg-[#F4F4F5] rounded-xl text-xs font-semibold text-[#17171A] border-none focus:ring-1 focus:ring-[#7C5CFC] cursor-pointer"
          >
            <option value="all">All Source Tiers</option>
            <option value="Tier 0 (ATS)">Tier 0 — ATS Direct</option>
            <option value="Tier 1 (Portals)">Tier 1 — Portals</option>
            <option value="Tier 2 (Aggregators)">Tier 2 — Aggregators</option>
            <option value="Tier 3 (APIs & RSS)">Tier 3 — Free APIs</option>
          </select>

          {/* Sort Selector */}
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as any)}
            className="px-3 py-2 bg-[#F4F4F5] rounded-xl text-xs font-semibold text-[#17171A] border-none focus:ring-1 focus:ring-[#7C5CFC] cursor-pointer"
          >
            <option value="match">Sort by Match Score</option>
            <option value="date">Sort by Recent</option>
            <option value="company">Sort by Company</option>
          </select>

          {/* Remote Toggle */}
          <button
            onClick={() => setRemoteOnly(!remoteOnly)}
            className={`px-3 py-2 rounded-xl text-xs font-semibold transition-all ${
              remoteOnly
                ? "bg-[#7C5CFC] text-white"
                : "bg-[#F4F4F5] text-[#7A7A82] hover:text-[#17171A]"
            }`}
          >
            Remote
          </button>

          {/* Paid Toggle */}
          <button
            onClick={() => setPaidOnly(!paidOnly)}
            className={`px-3 py-2 rounded-xl text-xs font-semibold transition-all ${
              paidOnly
                ? "bg-[#2BC7A0] text-white"
                : "bg-[#F4F4F5] text-[#7A7A82] hover:text-[#17171A]"
            }`}
          >
            Paid
          </button>
        </div>
      </div>

      {/* Main View Area */}
      {error && (
        <div className="eonix-card bg-[#FFF0EE] border border-[#FF6B57]/20 text-[#DC2626] text-xs p-4 flex items-center gap-2">
          <AlertCircle size={16} />
          <span>Error loading opportunities: {String(error)}</span>
        </div>
      )}

      {isLoading ? (
        <div className="py-24 text-center text-xs font-mono text-[#7A7A82]">
          Loading opportunities pipeline...
        </div>
      ) : viewMode === "kanban" ? (
        /* 5-Column Full Kanban View */
        <DndContext
          sensors={sensors}
          collisionDetection={closestCorners}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
        >
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
            {KANBAN_COLUMNS.map((column) => (
              <KanbanColumn
                key={column.id}
                column={column}
                items={columnItems[column.id]}
                onStageChange={handleStageChange}
              />
            ))}
          </div>

          <DragOverlay>
            {activeOpportunity ? (
              <KanbanCard
                opportunity={activeOpportunity}
                onStageChange={handleStageChange}
                isOverlay
              />
            ) : null}
          </DragOverlay>
        </DndContext>
      ) : viewMode === "table" ? (
        /* High-Density Tabular View */
        <div className="eonix-card p-0 overflow-hidden border border-[#EBEAE6]">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#F8F8F7] border-b border-[#EBEAE6] text-[#7A7A82] font-semibold uppercase text-[10px] tracking-wider">
                <tr>
                  <th className="py-3 px-4">Company</th>
                  <th className="py-3 px-4">Role Title</th>
                  <th className="py-3 px-4">Match</th>
                  <th className="py-3 px-4">Stipend</th>
                  <th className="py-3 px-4">Location</th>
                  <th className="py-3 px-4">Source Tier</th>
                  <th className="py-3 px-4">Current Stage</th>
                  <th className="py-3 px-4 text-right">Quick Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#EBEAE6]">
                {filteredList.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="py-16 text-center text-[#7A7A82]">
                      No opportunities match the current filters.
                    </td>
                  </tr>
                ) : (
                  filteredList.map((opp) => (
                    <tr key={opp.id} className="hover:bg-[#FBFBFA] transition-colors">
                      <td className="py-3 px-4 font-bold text-[#17171A]">
                        <Link href={`/opportunities/${opp.id}`} className="hover:text-[#7C5CFC]">
                          {opp.company}
                        </Link>
                      </td>
                      <td className="py-3 px-4 text-[#17171A] font-medium max-w-[240px] truncate">
                        {opp.role}
                      </td>
                      <td className="py-3 px-4">
                        <span
                          className={`font-mono text-[11px] font-bold px-2 py-0.5 rounded-full ${
                            opp.matchScore >= 80
                              ? "bg-[#EAF9F5] text-[#047857]"
                              : opp.matchScore >= 60
                              ? "bg-[#FFF8E6] text-[#92400E]"
                              : "bg-[#F4F4F5] text-[#7A7A82]"
                          }`}
                        >
                          {opp.matchScore}%
                        </span>
                      </td>
                      <td className="py-3 px-4 font-mono font-medium text-[#17171A]">
                        {opp.stipend_min
                          ? `₹${opp.stipend_min.toLocaleString()}/mo`
                          : opp.salary || "Undisclosed"}
                      </td>
                      <td className="py-3 px-4 text-[#7A7A82]">
                        {opp.location} {opp.is_remote && "• Remote"}
                      </td>
                      <td className="py-3 px-4 text-[#7A7A82]">
                        <span className="px-2 py-0.5 rounded-md bg-[#F4F4F5] text-[10px] font-semibold">
                          {opp.source}
                        </span>
                      </td>
                      <td className="py-3 px-4 capitalize font-semibold text-[#17171A]">
                        {opp.stage || opp.status || "Discovered"}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            onClick={() => handleStageChange(opp.id, "reviewing")}
                            className="px-2.5 py-1 rounded-full bg-[#F3EFFF] text-[#7C5CFC] font-semibold hover:bg-[#7C5CFC] hover:text-white transition-colors"
                            title="Move to Review"
                          >
                            Review
                          </button>
                          <button
                            onClick={() => handleStageChange(opp.id, "applied")}
                            className="px-2.5 py-1 rounded-full bg-[#FFF8E6] text-[#92400E] font-semibold hover:bg-[#FFC94A] hover:text-[#17171A] transition-colors"
                            title="Mark as Applied"
                          >
                            Applied
                          </button>
                          <Link
                            href={`/opportunities/${opp.id}`}
                            className="p-1 rounded-lg text-[#7A7A82] hover:text-[#17171A] hover:bg-[#F4F4F5]"
                          >
                            <ChevronRight size={14} />
                          </Link>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        /* Generous Cards Queue Grid (Organized & Easy to Browse) */
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {filteredList.length === 0 ? (
            <div className="col-span-full eonix-card py-24 text-center space-y-2">
              <Inbox size={32} className="mx-auto text-[#7A7A82] opacity-50" />
              <p className="font-display font-semibold text-base text-[#17171A]">
                No opportunities in this queue
              </p>
              <p className="text-xs text-[#7A7A82]">
                Switch tabs or adjust your filters above.
              </p>
            </div>
          ) : (
            filteredList.map((opp) => (
              <FocusedOpportunityCard
                key={opp.id}
                opportunity={opp}
                onStageChange={handleStageChange}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ── Focused Full Card Component ─────────────────────────────────────────────

function FocusedOpportunityCard({
  opportunity,
  onStageChange,
}: {
  opportunity: Opportunity;
  onStageChange: (id: string, stage: ApplicationStage) => void;
}) {
  const stage = normalizeToColumnId(opportunity.stage || opportunity.status);

  return (
    <div className="eonix-card p-4 hover:shadow-md transition-all duration-200 flex flex-col justify-between space-y-4 border border-[#EBEAE6] bg-white group">
      <div className="space-y-2.5">
        {/* Top Header: Company + Match Pill */}
        <div className="flex items-start justify-between gap-2">
          <div>
            <span className="font-display font-bold text-sm text-[#17171A] block hover:text-[#7C5CFC]">
              {opportunity.company}
            </span>
            <div className="flex items-center gap-1.5 text-[11px] text-[#7A7A82] mt-0.5">
              <MapPin size={11} />
              <span className="truncate max-w-[140px]">{opportunity.location}</span>
              {opportunity.is_remote && (
                <span className="px-1.5 py-0.2 rounded bg-[#EAF9F5] text-[#047857] font-semibold text-[10px]">
                  Remote
                </span>
              )}
            </div>
          </div>

          {/* Match Score Badge */}
          <span
            className={`font-mono text-xs font-bold px-2.5 py-0.5 rounded-full ${
              opportunity.matchScore >= 80
                ? "bg-[#EAF9F5] text-[#047857]"
                : opportunity.matchScore >= 60
                ? "bg-[#FFF8E6] text-[#92400E]"
                : "bg-[#F4F4F5] text-[#7A7A82]"
            }`}
          >
            {opportunity.matchScore}%
          </span>
        </div>

        {/* Role Title */}
        <Link href={`/opportunities/${opportunity.id}`} className="block">
          <h3 className="font-display font-semibold text-sm text-[#17171A] line-clamp-2 leading-snug group-hover:text-[#7C5CFC] transition-colors">
            {opportunity.role}
          </h3>
        </Link>

        {/* Skills Pills */}
        {opportunity.skills && opportunity.skills.length > 0 && (
          <div className="flex flex-wrap gap-1 pt-1">
            {opportunity.skills.slice(0, 3).map((skill, idx) => (
              <span
                key={idx}
                className="px-2 py-0.5 rounded-md bg-[#F4F4F5] text-[10px] font-medium text-[#17171A]"
              >
                {skill}
              </span>
            ))}
            {opportunity.skills.length > 3 && (
              <span className="text-[10px] text-[#7A7A82] self-center">
                +{opportunity.skills.length - 3}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Card Footer & 1-Click Action Buttons */}
      <div className="space-y-3 pt-2 border-t border-[#EBEAE6]">
        <div className="flex items-center justify-between text-[11px] font-mono">
          <span className="font-semibold text-[#17171A]">
            {opportunity.stipend_min
              ? `₹${opportunity.stipend_min.toLocaleString()}/mo`
              : opportunity.salary || "Unpaid / Disclosed"}
          </span>
          <span className="text-[#7A7A82] text-[10px]">
            {opportunity.source}
          </span>
        </div>

        {/* Direct Triage Quick Actions */}
        <div className="grid grid-cols-2 gap-1.5 pt-1">
          {stage === "discovered" ? (
            <>
              <button
                onClick={() => onStageChange(opportunity.id, "reviewing")}
                className="py-1.5 px-3 rounded-xl bg-[#F3EFFF] hover:bg-[#7C5CFC] text-[#7C5CFC] hover:text-white text-xs font-semibold transition-all flex items-center justify-center gap-1"
              >
                <Clock size={12} />
                <span>Review</span>
              </button>

              <button
                onClick={() => onStageChange(opportunity.id, "applied")}
                className="py-1.5 px-3 rounded-xl bg-[#FFF8E6] hover:bg-[#FFC94A] text-[#92400E] hover:text-[#17171A] text-xs font-semibold transition-all flex items-center justify-center gap-1"
              >
                <Send size={12} />
                <span>Applied</span>
              </button>
            </>
          ) : stage === "reviewing" ? (
            <>
              <Link
                href={`/opportunities/${opportunity.id}`}
                className="py-1.5 px-3 rounded-xl bg-[#7C5CFC] hover:bg-[#6847E8] text-white text-xs font-semibold transition-all flex items-center justify-center gap-1 text-center"
              >
                <Sparkles size={12} />
                <span>Tailor</span>
              </Link>

              <button
                onClick={() => onStageChange(opportunity.id, "applied")}
                className="py-1.5 px-3 rounded-xl bg-[#FFF8E6] hover:bg-[#FFC94A] text-[#92400E] hover:text-[#17171A] text-xs font-semibold transition-all flex items-center justify-center gap-1"
              >
                <Send size={12} />
                <span>Applied</span>
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => onStageChange(opportunity.id, "interviewing")}
                className="py-1.5 px-3 rounded-xl bg-[#EFF4FE] hover:bg-[#5B8DEF] text-[#1D4ED8] hover:text-white text-xs font-semibold transition-all flex items-center justify-center gap-1"
              >
                <Briefcase size={12} />
                <span>Interview</span>
              </button>

              <button
                onClick={() => onStageChange(opportunity.id, "offer")}
                className="py-1.5 px-3 rounded-xl bg-[#EAF9F5] hover:bg-[#2BC7A0] text-[#047857] hover:text-white text-xs font-semibold transition-all flex items-center justify-center gap-1"
              >
                <Award size={12} />
                <span>Offer</span>
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Kanban Column Component ─────────────────────────────────────────────────

function KanbanColumn({
  column,
  items,
  onStageChange,
}: {
  column: (typeof KANBAN_COLUMNS)[0];
  items: Opportunity[];
  onStageChange: (id: string, stage: ApplicationStage) => void;
}) {
  const itemIds = useMemo(() => items.map((i) => i.id), [items]);

  return (
    <div
      className="rounded-3xl p-3 flex flex-col min-h-[550px] transition-all border shadow-xs"
      style={{
        backgroundColor: column.tint,
        borderColor: column.border,
      }}
    >
      {/* Column Header */}
      <div className="flex items-center justify-between pb-3 px-1">
        <div className="flex items-center gap-2">
          <span
            className="w-2.5 h-2.5 rounded-full"
            style={{ backgroundColor: column.accent }}
          />
          <h2 className="font-display font-bold text-xs uppercase tracking-wider text-[#17171A]">
            {column.title}
          </h2>
        </div>

        <span
          className="font-mono text-xs font-bold px-2 py-0.5 rounded-full"
          style={{
            backgroundColor: column.badgeBg,
            color: column.badgeText,
          }}
        >
          {items.length}
        </span>
      </div>

      {/* Cards Container */}
      <SortableContext items={itemIds} strategy={verticalListSortingStrategy}>
        <div className="space-y-2.5 flex-1 overflow-y-auto max-h-[calc(100vh-280px)] pr-0.5">
          {items.length === 0 ? (
            <div className="h-36 rounded-2xl border-2 border-dashed border-black/5 flex items-center justify-center text-center p-4">
              <span className="text-[11px] text-[#7A7A82]">
                No opportunities
              </span>
            </div>
          ) : (
            items.map((opportunity) => (
              <KanbanCard
                key={opportunity.id}
                opportunity={opportunity}
                onStageChange={onStageChange}
              />
            ))
          )}
        </div>
      </SortableContext>
    </div>
  );
}

// ── Kanban Card Component ───────────────────────────────────────────────────

function KanbanCard({
  opportunity,
  onStageChange,
  isOverlay = false,
}: {
  opportunity: Opportunity;
  onStageChange: (id: string, stage: ApplicationStage) => void;
  isOverlay?: boolean;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: opportunity.id });

  const [menuOpen, setMenuOpen] = useState(false);

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.3 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      className={`eonix-card p-3.5 bg-white cursor-grab active:cursor-grabbing hover:shadow-md transition-all duration-200 border border-[#EBEAE6] select-none ${
        isOverlay ? "shadow-2xl rotate-2 scale-105 border-[#7C5CFC]" : ""
      }`}
    >
      <div className="space-y-2">
        <div className="flex items-start justify-between gap-1.5">
          <span className="font-display font-bold text-xs text-[#17171A] truncate max-w-[150px]">
            {opportunity.company}
          </span>
          <span
            className={`font-mono text-[10px] font-bold px-1.5 py-0.2 rounded-full ${
              opportunity.matchScore >= 80
                ? "bg-[#EAF9F5] text-[#047857]"
                : opportunity.matchScore >= 60
                ? "bg-[#FFF8E6] text-[#92400E]"
                : "bg-[#F4F4F5] text-[#7A7A82]"
            }`}
          >
            {opportunity.matchScore}%
          </span>
        </div>

        <Link
          href={`/opportunities/${opportunity.id}`}
          className="font-display font-semibold text-xs text-[#17171A] line-clamp-2 leading-snug hover:text-[#7C5CFC]"
        >
          {opportunity.role}
        </Link>

        <div className="flex items-center justify-between text-[10px] font-mono text-[#7A7A82] pt-1">
          <span>{opportunity.location}</span>
          <span className="font-semibold text-[#17171A]">
            {opportunity.stipend_min
              ? `₹${opportunity.stipend_min.toLocaleString()}`
              : "Unpaid"}
          </span>
        </div>
      </div>
    </div>
  );
}
