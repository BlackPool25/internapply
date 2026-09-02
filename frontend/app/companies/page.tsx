"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import {
  Building2,
  Globe,
  ExternalLink,
  Search,
  Briefcase,
  Layers,
  ArrowRight,
  TrendingUp,
  Sparkles,
} from "lucide-react";
import { AppLayout } from "@/components/AppLayout";
import { useCompanies, useOpportunities } from "@/lib/api";

export default function CompaniesPage() {
  const [search, setSearch] = useState("");
  const { data: companies = [], isLoading, error } = useCompanies();
  const { data: allOpportunities = [] } = useOpportunities();

  // Aggregate opportunity counts per company name
  const oppCountByCompany = useMemo(() => {
    const map: Record<string, number> = {};
    allOpportunities.forEach((opp) => {
      const c = (opp.company || "").toLowerCase().trim();
      map[c] = (map[c] || 0) + 1;
    });
    return map;
  }, [allOpportunities]);

  // If no companies are in the Track B table yet, synthesize unique company entities from active opportunities!
  const displayCompanies = useMemo(() => {
    if (companies && companies.length > 0) {
      return companies.filter(
        (c) =>
          !search ||
          c.name.toLowerCase().includes(search.toLowerCase()) ||
          (c.domain && c.domain.toLowerCase().includes(search.toLowerCase()))
      );
    }

    // Synthesize companies from opportunities so the user never sees an empty void when scrapers have populated opportunities
    const uniqueMap = new Map<string, any>();
    allOpportunities.forEach((opp) => {
      const cName = opp.company || "Unknown";
      if (!uniqueMap.has(cName.toLowerCase())) {
        uniqueMap.set(cName.toLowerCase(), {
          id: `opp-co-${opp.id}`,
          name: cName,
          domain: opp.company.toLowerCase().replace(/[^a-z0-9]/g, "") + ".com",
          description: opp.companyDescription || `Organization offering opportunities in ${opp.location || "tech"}.`,
          tech_stack: opp.skills?.slice(0, 4) || ["Backend", "Cloud"],
          funding_stage: "Growth / Enterprise",
          source: opp.source,
          synthetic: true,
        });
      }
    });

    const synth = Array.from(uniqueMap.values());
    return synth.filter(
      (c) =>
        !search ||
        c.name.toLowerCase().includes(search.toLowerCase()) ||
        (c.domain && c.domain.toLowerCase().includes(search.toLowerCase()))
    );
  }, [companies, allOpportunities, search]);

  return (
    <AppLayout>
      <div className="space-y-6 pb-12">
        {/* Header & Search */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="font-display font-bold text-2xl sm:text-3xl text-[#17171A] tracking-tight">
              Target Companies
            </h1>
            <p className="text-sm text-[#7A7A82] mt-0.5">
              Aggregated organization dossiers, tech stacks, and linked opportunity volume.
            </p>
          </div>

          <div className="relative">
            <Search
              size={14}
              className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#7A7A82]"
            />
            <input
              type="text"
              placeholder="Search companies..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 pr-4 py-2 bg-white rounded-full text-xs font-medium text-[#17171A] border border-[#EBEAE6] shadow-xs focus:outline-none focus:ring-2 focus:ring-[#7C5CFC]/30 w-64"
            />
          </div>
        </div>

        {/* Loading State */}
        {isLoading ? (
          <div className="py-24 text-center">
            <div className="w-8 h-8 border-3 border-[#7C5CFC] border-t-transparent rounded-full animate-spin mx-auto mb-3" />
            <p className="text-xs text-[#7A7A82] font-mono">Loading company directories...</p>
          </div>
        ) : displayCompanies.length === 0 ? (
          <div className="eonix-card text-center py-16">
            <Building2 size={32} className="text-[#A1A1AA] mx-auto mb-2" />
            <p className="text-sm font-semibold text-[#17171A]">No companies found</p>
            <p className="text-xs text-[#7A7A82] mt-1">
              Run the pipeline scraper from the dashboard to discover organizations.
            </p>
          </div>
        ) : (
          /* Companies Card Grid */
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {displayCompanies.map((company) => {
              const oppCount = oppCountByCompany[company.name.toLowerCase()] || 1;

              return (
                <div
                  key={company.id}
                  className="eonix-card eonix-card-hover flex flex-col justify-between group"
                >
                  <div>
                    {/* Header: Logo + Name + Opp Count Pill */}
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-2xl bg-[#17171A] text-white flex items-center justify-center font-display font-bold text-base shadow-sm">
                          {company.name.slice(0, 1).toUpperCase()}
                        </div>
                        <div>
                          <h3 className="font-display font-bold text-sm text-[#17171A] group-hover:text-[#7C5CFC] transition-colors line-clamp-1">
                            {company.name}
                          </h3>
                          {company.domain && (
                            <span className="text-[11px] font-mono text-[#7A7A82] flex items-center gap-1">
                              <Globe size={10} />
                              <span>{company.domain}</span>
                            </span>
                          )}
                        </div>
                      </div>

                      <span className="font-mono text-xs font-semibold px-2.5 py-1 rounded-full bg-[#F4F4F5] text-[#17171A] whitespace-nowrap shadow-2xs">
                        {oppCount} {oppCount === 1 ? "role" : "roles"}
                      </span>
                    </div>

                    {/* Description */}
                    <p className="text-xs text-[#52525B] mt-3 line-clamp-2 leading-relaxed">
                      {company.description || "Organization profile from opportunity discovery feed."}
                    </p>

                    {/* Tech Stack Pills */}
                    {company.tech_stack && company.tech_stack.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mt-3">
                        {company.tech_stack.slice(0, 3).map((t: string, idx: number) => (
                          <span
                            key={idx}
                            className="px-2 py-0.5 rounded-full bg-[#FFFFFF] border border-[#EBEAE6] text-[10px] font-medium text-[#17171A]"
                          >
                            {t}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Footer */}
                  <div className="mt-4 pt-3 border-t border-[#F0EFEC] flex items-center justify-between text-xs font-semibold">
                    <span className="text-[11px] text-[#7A7A82] capitalize">
                      {company.funding_stage || company.source || "Active"}
                    </span>
                    <Link
                      href={`/internships?q=${encodeURIComponent(company.name)}`}
                      className="inline-flex items-center gap-1 text-[#7C5CFC] hover:underline"
                    >
                      <span>View Opportunities</span>
                      <ArrowRight size={12} />
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </AppLayout>
  );
}
