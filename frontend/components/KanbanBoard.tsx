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
  DollarSign,
  ExternalLink,
  MoreVertical,
  CheckCircle2,
  XCircle,
  Clock,
  Sparkles,
  Layers,
  ArrowRight,
  ChevronDown,
  Building2,
  Briefcase,
  AlertCircle,
  Flame,
  ShieldCheck,
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
}> = [
  {
    id: "discovered",
    title: "Discovered",
    tint: "#F4F4F5",
    border: "#E4E4E7",
    accent: "#7A7A82",
    badgeBg: "#E4E4E7",
    badgeText: "#3F3F46",
  },
  {
    id: "reviewing",
    title: "Reviewing",
    tint: "#F3EFFF",
    border: "#E0D7FE",
    accent: "#7C5CFC",
    badgeBg: "#EDE7FE",
    badgeText: "#6542EC",
  },
  {
    id: "applied",
    title: "Applied",
    tint: "#FFF8E6",
    border: "#FDE68A",
    accent: "#FFC94A",
    badgeBg: "#FEF3C7",
    badgeText: "#92400E",
  },
  {
    id: "interviewing",
    title: "Interviewing",
    tint: "#EFF4FE",
    border: "#BFDBFE",
    accent: "#5B8DEF",
    badgeBg: "#DBEAFE",
    badgeText: "#1D4ED8",
  },
  {
    id: "offer",
    title: "Offer / Rejected",
    tint: "#EAF9F5",
    border: "#A7F3D0",
    accent: "#2BC7A0",
    badgeBg: "#D1FAE5",
    badgeText: "#047857",
  },
];

// Map arbitrary status into one of the 5 canonical column IDs
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
  sourceType: SourceType;
  title: string;
  description: string;
}

export function KanbanBoard({ sourceType, title, description }: KanbanBoardProps) {
  const [search, setSearch] = useQueryState("q", { defaultValue: "" });
  const [tierFilter, setTierFilter] = useQueryState("tier", { defaultValue: "all" });

  const { data: rawOpportunities = [], isLoading, error } = useOpportunities({
    source_type: sourceType,
  });

  const updateStageMutation = useUpdateOpportunityStage();
  const [activeCard, setActiveCard] = useState<Opportunity | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 5,
      },
    }),
    useSensor(KeyboardSensor)
  );

  // Filter opportunities by search query and tier
  const filteredOpportunities = useMemo(() => {
    return rawOpportunities.filter((opp) => {
      if (search) {
        const q = search.toLowerCase();
        const matchesQuery =
          opp.company.toLowerCase().includes(q) ||
          opp.role.toLowerCase().includes(q) ||
          opp.location.toLowerCase().includes(q) ||
          (opp.skills && opp.skills.some((s) => s.toLowerCase().includes(q)));
        if (!matchesQuery) return false;
      }

      if (tierFilter && tierFilter !== "all") {
        if (opp.tier && !opp.tier.toLowerCase().includes(tierFilter.toLowerCase())) {
          return false;
        }
      }

      return true;
    });
  }, [rawOpportunities, search, tierFilter]);

  // Group into columns
  const columnsData = useMemo(() => {
    const map: Record<ApplicationStage, Opportunity[]> = {
      discovered: [],
      reviewing: [],
      applied: [],
      interviewing: [],
      offer: [],
      ongoing: [],
      closed: [],
      cancelled: [],
      rejected: [],
    };

    filteredOpportunities.forEach((opp) => {
      const colId = normalizeToColumnId(opp.stage || opp.status);
      map[colId].push(opp);
    });

    return map;
  }, [filteredOpportunities]);

  const handleDragStart = (event: DragStartEvent) => {
    const oppId = String(event.active.id);
    const opp = rawOpportunities.find((o) => o.id === oppId);
    if (opp) setActiveCard(opp);
  };

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;
    setActiveCard(null);

    if (!over) return;

    const activeId = String(active.id);
    const overId = String(over.id);

    // Target could be a column or another card
    let targetStage: ApplicationStage = "discovered";
    if (KANBAN_COLUMNS.some((col) => col.id === overId)) {
      targetStage = overId as ApplicationStage;
    } else {
      const overCard = rawOpportunities.find((o) => o.id === overId);
      if (overCard) {
        targetStage = normalizeToColumnId(overCard.stage || overCard.status);
      }
    }

    const currentCard = rawOpportunities.find((o) => o.id === activeId);
    if (currentCard && normalizeToColumnId(currentCard.stage || currentCard.status) !== targetStage) {
      try {
        await updateStageMutation.mutateAsync({
          id: activeId,
          stage: targetStage,
        });
        showToast(`Moved to ${targetStage.charAt(0).toUpperCase() + targetStage.slice(1)}`);
      } catch {
        showToast("Failed to update status. Rolled back.", true);
      }
    }
  };

  const handleQuickMove = async (id: string, stage: string) => {
    try {
      await updateStageMutation.mutateAsync({ id, stage });
      showToast(`Updated to ${stage.charAt(0).toUpperCase() + stage.slice(1)}`);
    } catch {
      showToast("Update failed. Please retry.", true);
    }
  };

  const showToast = (msg: string, isError = false) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3000);
  };

  return (
    <div className="space-y-6">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#17171A] text-white px-4 py-2.5 rounded-full text-xs font-semibold shadow-2xl flex items-center gap-2 border border-white/10 animate-bounce">
          <Sparkles size={14} className="text-[#7C5CFC]" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Header & Filter Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="font-display font-bold text-2xl sm:text-3xl text-[#17171A] tracking-tight">
            {title}
          </h1>
          <p className="text-sm text-[#7A7A82] mt-0.5">{description}</p>
        </div>

        {/* Filter Controls */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* Search Input */}
          <div className="relative">
            <Search
              size={14}
              className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#7A7A82]"
            />
            <input
              type="text"
              placeholder="Search company, title, skills..."
              value={search}
              onChange={(e) => setSearch(e.target.value || null)}
              className="pl-9 pr-4 py-2 bg-white rounded-full text-xs font-medium text-[#17171A] border border-[#EBEAE6] shadow-xs focus:outline-none focus:ring-2 focus:ring-[#7C5CFC]/30 w-56 sm:w-64"
            />
          </div>

          {/* Tier Filter Pills */}
          <div className="flex items-center gap-1 bg-white p-1 rounded-full border border-[#EBEAE6] shadow-xs">
            {["all", "tier 0", "tier 1", "tier 2", "tier 3"].map((t) => (
              <button
                key={t}
                onClick={() => setTierFilter(t === "all" ? null : t)}
                className={`px-3 py-1.5 rounded-full text-xs font-semibold uppercase tracking-wider transition-all ${
                  (tierFilter === t || (t === "all" && (!tierFilter || tierFilter === "all")))
                    ? "bg-[#17171A] text-white"
                    : "text-[#7A7A82] hover:text-[#17171A] hover:bg-[#F5F4F0]"
                }`}
              >
                {t === "all" ? "All Tiers" : t.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Board Container */}
      {isLoading ? (
        <div className="py-24 text-center">
          <div className="w-8 h-8 border-3 border-[#7C5CFC] border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-xs text-[#7A7A82] font-mono">Loading opportunity pipeline...</p>
        </div>
      ) : error ? (
        <div className="p-8 text-center bg-white rounded-3xl border border-red-200">
          <AlertCircle size={24} className="text-red-500 mx-auto mb-2" />
          <p className="text-sm font-semibold text-[#17171A]">Failed to load opportunities</p>
          <p className="text-xs text-[#7A7A82] mt-1">{String(error)}</p>
        </div>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCorners}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
        >
          <div className="flex gap-5 overflow-x-auto pb-8 pt-2 min-h-[680px]">
            {KANBAN_COLUMNS.map((column) => {
              const items = columnsData[column.id] || [];

              return (
                <div
                  key={column.id}
                  id={column.id}
                  className="flex flex-col flex-shrink-0 w-[310px] sm:w-[325px] rounded-[24px] bg-white/70 p-3.5 shadow-[0px_8px_24px_rgba(23,23,26,0.04)] border border-[#EBEAE6]"
                >
                  {/* Column Header with Stage Tint */}
                  <div
                    className="flex items-center justify-between px-3.5 py-2.5 rounded-2xl mb-3.5 border transition-all"
                    style={{
                      backgroundColor: column.tint,
                      borderColor: column.border,
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className="w-2.5 h-2.5 rounded-full"
                        style={{ backgroundColor: column.accent }}
                      />
                      <h3
                        className="font-display font-semibold text-sm tracking-tight"
                        style={{ color: column.badgeText }}
                      >
                        {column.title}
                      </h3>
                    </div>
                    <span
                      className="font-mono text-xs font-bold px-2 py-0.5 rounded-full shadow-2xs"
                      style={{
                        backgroundColor: "#FFFFFF",
                        color: column.badgeText,
                      }}
                    >
                      {items.length}
                    </span>
                  </div>

                  {/* Column Card Stack */}
                  <SortableContext
                    id={column.id}
                    items={items.map((i) => i.id)}
                    strategy={verticalListSortingStrategy}
                  >
                    <div className="flex-1 overflow-y-auto space-y-3.5 pr-0.5 min-h-[200px]">
                      {items.length === 0 ? (
                        <div className="h-32 border-2 border-dashed border-[#E4E3DF] rounded-2xl flex flex-col items-center justify-center text-center p-4">
                          <p className="text-xs text-[#A1A1AA] font-medium">
                            No opportunities in this stage
                          </p>
                          <p className="text-[10px] text-[#C4C4C8] mt-0.5">
                            Drag cards here to advance
                          </p>
                        </div>
                      ) : (
                        items.map((opp) => (
                          <KanbanCardItem
                            key={opp.id}
                            opportunity={opp}
                            onQuickMove={handleQuickMove}
                          />
                        ))
                      )}
                    </div>
                  </SortableContext>
                </div>
              );
            })}
          </div>

          {/* Active Drag Overlay */}
          <DragOverlay>
            {activeCard ? (
              <div className="transform rotate-2 scale-105 opacity-95">
                <KanbanCardItem
                  opportunity={activeCard}
                  isOverlay
                  onQuickMove={() => {}}
                />
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      )}
    </div>
  );
}

// ── Kanban Card Item ────────────────────────────────────────

interface KanbanCardItemProps {
  opportunity: Opportunity;
  isOverlay?: boolean;
  onQuickMove: (id: string, stage: string) => void;
}

function KanbanCardItem({ opportunity, isOverlay, onQuickMove }: KanbanCardItemProps) {
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

  const stage = (opportunity.stage || opportunity.status || "discovered").toLowerCase();

  // Tier badge color helper
  const getTierColor = (tier: string = "") => {
    if (tier.includes("0")) return "#7C5CFC"; // Purple ATS
    if (tier.includes("1")) return "#2BC7A0"; // Teal Portals
    if (tier.includes("2")) return "#FFC94A"; // Yellow Aggregators
    return "#5B8DEF"; // Blue APIs
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`relative bg-white rounded-2xl p-4 shadow-[0px_4px_16px_rgba(23,23,26,0.05)] border border-[#EBEAE6] transition-all hover:shadow-[0px_8px_24px_rgba(23,23,26,0.08)] group ${
        isOverlay ? "cursor-grabbing shadow-2xl border-[#7C5CFC]" : "cursor-grab"
      }`}
      {...attributes}
      {...listeners}
    >
      {/* Top Header: Company + Quick Menu */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-[#F4F4F5] flex items-center justify-center text-[#17171A] font-bold text-xs">
            {opportunity.company.slice(0, 1).toUpperCase()}
          </div>
          <h4 className="font-display font-semibold text-xs text-[#7A7A82] uppercase tracking-wider line-clamp-1">
            {opportunity.company}
          </h4>
        </div>

        {/* Action Menu Toggle */}
        <div className="relative" onPointerDown={(e) => e.stopPropagation()}>
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            className="p-1 rounded-lg text-[#7A7A82] hover:text-[#17171A] hover:bg-[#F4F4F5] transition-colors"
          >
            <MoreVertical size={14} />
          </button>

          {menuOpen && (
            <div
              className="absolute right-0 mt-1 w-44 bg-white rounded-2xl shadow-2xl border border-[#EBEAE6] py-1.5 z-30 text-xs font-semibold"
              onClick={() => setMenuOpen(false)}
            >
              <div className="px-3 py-1 text-[10px] uppercase text-[#7A7A82] tracking-wider">
                Move Stage
              </div>
              <button
                onClick={() => onQuickMove(opportunity.id, "discovered")}
                className="w-full px-3 py-1.5 text-left text-[#17171A] hover:bg-[#F4F4F5] flex items-center gap-2"
              >
                <span className="w-2 h-2 rounded-full bg-[#7A7A82]" />
                Discovered
              </button>
              <button
                onClick={() => onQuickMove(opportunity.id, "reviewing")}
                className="w-full px-3 py-1.5 text-left text-[#7C5CFC] hover:bg-[#F3EFFF] flex items-center gap-2"
              >
                <span className="w-2 h-2 rounded-full bg-[#7C5CFC]" />
                Reviewing
              </button>
              <button
                onClick={() => onQuickMove(opportunity.id, "applied")}
                className="w-full px-3 py-1.5 text-left text-[#B45309] hover:bg-[#FFF8E6] flex items-center gap-2"
              >
                <span className="w-2 h-2 rounded-full bg-[#FFC94A]" />
                Applied / Ongoing
              </button>
              <button
                onClick={() => onQuickMove(opportunity.id, "interviewing")}
                className="w-full px-3 py-1.5 text-left text-[#2563EB] hover:bg-[#EFF4FE] flex items-center gap-2"
              >
                <span className="w-2 h-2 rounded-full bg-[#5B8DEF]" />
                Interviewing
              </button>
              <button
                onClick={() => onQuickMove(opportunity.id, "offer")}
                className="w-full px-3 py-1.5 text-left text-[#059669] hover:bg-[#EAF9F5] flex items-center gap-2"
              >
                <span className="w-2 h-2 rounded-full bg-[#2BC7A0]" />
                Offer
              </button>
              <button
                onClick={() => onQuickMove(opportunity.id, "rejected")}
                className="w-full px-3 py-1.5 text-left text-[#DC2626] hover:bg-[#FFF0EE] flex items-center gap-2"
              >
                <span className="w-2 h-2 rounded-full bg-[#FF6B57]" />
                Rejected / Closed
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Role Title */}
      <h3 className="font-sans font-semibold text-sm text-[#17171A] mt-2 line-clamp-2 leading-snug group-hover:text-[#7C5CFC] transition-colors">
        {opportunity.role}
      </h3>

      {/* Location & Meta */}
      <div className="flex items-center gap-2 mt-2 text-[11px] text-[#7A7A82]">
        <div className="flex items-center gap-1 line-clamp-1">
          <MapPin size={11} className="flex-shrink-0" />
          <span>{opportunity.location || "Remote"}</span>
        </div>
      </div>

      {/* Badges: Stipend & Source Tier */}
      <div className="flex flex-wrap items-center gap-1.5 mt-3 pt-2.5 border-t border-[#F0EFEC]">
        {/* Stipend Pill (JetBrains Mono) */}
        {opportunity.salary && opportunity.salary !== "Not disclosed" ? (
          <span className="font-mono text-[11px] font-semibold text-[#17171A] bg-[#F4F4F5] px-2.5 py-0.5 rounded-full">
            {opportunity.salary}
          </span>
        ) : null}

        {/* Source Tier Pill */}
        <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-[#17171A] bg-[#FFFFFF] border border-[#EBEAE6] px-2 py-0.5 rounded-full shadow-2xs">
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{ backgroundColor: getTierColor(opportunity.tier) }}
          />
          <span className="capitalize">{opportunity.source || "Web"}</span>
        </span>

        {/* Verifier Score Pill if present */}
        {opportunity.matchScore > 0 && (
          <span className="font-mono text-[10px] font-bold text-[#059669] bg-[#EAF9F5] px-2 py-0.5 rounded-full flex items-center gap-1">
            <ShieldCheck size={10} />
            <span>{opportunity.matchScore}%</span>
          </span>
        )}
      </div>

      {/* Bottom Footer Link */}
      <div
        className="flex items-center justify-between mt-3 pt-2 text-[11px] font-semibold text-[#7A7A82]"
        onPointerDown={(e) => e.stopPropagation()}
      >
        <span className="font-mono text-[10px] text-[#A1A1AA]">
          {opportunity.date ? opportunity.date.slice(0, 10) : "Recent"}
        </span>

        <div className="flex items-center gap-2">
          {opportunity.jobUrl && (
            <a
              href={opportunity.jobUrl}
              target="_blank"
              rel="noreferrer"
              className="p-1 text-[#7A7A82] hover:text-[#17171A] hover:bg-[#F4F4F5] rounded-md transition-colors"
              title="Open job source"
            >
              <ExternalLink size={12} />
            </a>
          )}
          <Link
            href={`/opportunities/${opportunity.id}`}
            className="inline-flex items-center gap-0.5 text-[#7C5CFC] hover:underline"
          >
            <span>Details</span>
            <ArrowRight size={11} />
          </Link>
        </div>
      </div>
    </div>
  );
}
