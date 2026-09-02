"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { motion } from "motion/react";
import {
  LayoutDashboard,
  Briefcase,
  Gem,
  Building2,
  FileText,
  Settings,
  Play,
  CheckCircle2,
  Menu,
  X,
  Sparkles,
  Sliders,
  Zap,
} from "lucide-react";
import { usePipelineStatus } from "@/lib/api";

const NAV_ITEMS = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Pipeline", href: "/pipeline", icon: Sparkles },
  { label: "Internships", href: "/internships", icon: Briefcase },
  { label: "Freelance", href: "/freelance", icon: Gem },
  { label: "Companies", href: "/companies", icon: Building2 },
  { label: "Resume", href: "/resume", icon: FileText },
  { label: "Settings", href: "/settings", icon: Settings },
];

export function Navbar() {
  const pathname = usePathname();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const { data: pipelineStatus } = usePipelineStatus();

  const isRunning = pipelineStatus?.status === "running";

  return (
    <header className="sticky top-0 z-40 w-full px-4 sm:px-6 lg:px-8 pt-4 pb-2 bg-[#F0EFEC]/90 backdrop-blur-md">
      <div className="max-w-7xl mx-auto flex items-center justify-between">
        {/* Brand */}
        <Link href="/dashboard" className="flex items-center gap-2.5 group">
          <div className="w-9 h-9 rounded-xl bg-[#17171A] flex items-center justify-center text-white shadow-sm transition-transform group-hover:scale-105">
            <Sparkles size={18} className="text-[#7C5CFC]" />
          </div>
          <div className="flex flex-col">
            <span className="font-display font-bold text-xl tracking-tight text-[#17171A]">
              InternApply
            </span>
          </div>
        </Link>

        {/* Desktop Eonix-Style Pill Nav */}
        <nav className="hidden md:flex items-center gap-1.5 p-1.5 bg-[#FFFFFF] rounded-full shadow-[0px_4px_20px_rgba(23,23,26,0.06)] border border-[#EBEAE6]">
          {NAV_ITEMS.map((item) => {
            const isActive =
              pathname === item.href ||
              (item.href === "/internships" && pathname === "/opportunities") ||
              (item.href !== "/" && pathname.startsWith(item.href + "/"));

            return (
              <Link
                key={item.href}
                href={item.href}
                className={`relative px-3.5 py-2 rounded-full text-xs font-semibold tracking-wide transition-all duration-200 ${
                  isActive
                    ? "text-white bg-[#17171A] shadow-sm"
                    : "text-[#7A7A82] hover:text-[#17171A] hover:bg-[#F5F4F0]"
                }`}
              >
                {isActive && (
                  <motion.div
                    layoutId="activeNavPill"
                    className="absolute inset-0 bg-[#17171A] rounded-full -z-10"
                    transition={{ type: "spring", stiffness: 380, damping: 30 }}
                  />
                )}
                <span className="relative z-10 flex items-center gap-1.5">
                  <item.icon size={13} />
                  {item.label}
                </span>
              </Link>
            );
          })}
        </nav>

        {/* Right Action Cluster */}
        <div className="flex items-center gap-2.5">
          {/* Live Background Progress Pill */}
          {isRunning ? (
            <Link
              href="/pipeline"
              className="flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-[#7C5CFC] text-white text-xs font-semibold shadow-md hover:bg-[#6847E8] transition-all animate-pulse"
            >
              <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
              <span className="font-mono text-[11px]">{pipelineStatus?.progress_pct ?? 0}%</span>
              <span className="hidden sm:inline text-[11px]">Running...</span>
            </Link>
          ) : (
            <Link
              href="/pipeline"
              className="hidden sm:flex items-center gap-2 px-3.5 py-2 rounded-full text-xs font-semibold bg-white text-[#17171A] hover:bg-[#17171A] hover:text-white border border-[#EBEAE6] shadow-2xs transition-all"
            >
              <Zap size={13} className="text-[#7C5CFC]" />
              <span>Launch Scrapers</span>
            </Link>
          )}

          {/* System Status Pill */}
          <div className="hidden lg:flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white text-[11px] font-medium text-[#7A7A82] border border-[#EBEAE6]">
            <span className="w-2 h-2 rounded-full bg-[#2BC7A0] animate-pulse" />
            <span>FastAPI Live</span>
          </div>

          {/* Mobile Menu Toggle */}
          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="md:hidden p-2 rounded-xl bg-white border border-[#EBEAE6] text-[#17171A]"
          >
            {mobileMenuOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
        </div>
      </div>

      {/* Mobile Nav Drawer */}
      {mobileMenuOpen && (
        <div className="md:hidden mt-3 p-3 bg-white rounded-2xl shadow-lg border border-[#EBEAE6] flex flex-col gap-1">
          {NAV_ITEMS.map((item) => {
            const isActive =
              pathname === item.href ||
              (item.href === "/internships" && pathname === "/opportunities") ||
              (item.href !== "/" && pathname.startsWith(item.href + "/"));

            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMobileMenuOpen(false)}
                className={`flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl text-sm font-semibold transition-all ${
                  isActive
                    ? "bg-[#17171A] text-white"
                    : "text-[#7A7A82] hover:bg-[#F5F4F0] hover:text-[#17171A]"
                }`}
              >
                <item.icon size={16} />
                {item.label}
              </Link>
            );
          })}
        </div>
      )}
    </header>
  );
}
