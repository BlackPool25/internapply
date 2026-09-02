"use client";

import { ReactNode } from "react";
import { Navbar } from "./Navbar";

export function AppLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-[#F0EFEC] flex flex-col font-sans selection:bg-[#7C5CFC]/20 selection:text-[#7C5CFC]">
      {/* Global SVG Pattern Definitions for Hatch-Textured Charts */}
      <svg className="absolute w-0 h-0 pointer-events-none" aria-hidden="true">
        <defs>
          {/* 45 degree hatch stripe patterns */}
          <pattern
            id="hatchPatternPurple"
            width="8"
            height="8"
            patternTransform="rotate(45 0 0)"
            patternUnits="userSpaceOnUse"
          >
            <rect width="8" height="8" fill="#7C5CFC" />
            <line
              x1="0"
              y1="0"
              x2="0"
              y2="8"
              stroke="#FFFFFF"
              strokeWidth="2.5"
              strokeOpacity="0.45"
            />
          </pattern>

          <pattern
            id="hatchPatternYellow"
            width="8"
            height="8"
            patternTransform="rotate(45 0 0)"
            patternUnits="userSpaceOnUse"
          >
            <rect width="8" height="8" fill="#FFC94A" />
            <line
              x1="0"
              y1="0"
              x2="0"
              y2="8"
              stroke="#FFFFFF"
              strokeWidth="2.5"
              strokeOpacity="0.5"
            />
          </pattern>

          <pattern
            id="hatchPatternTeal"
            width="8"
            height="8"
            patternTransform="rotate(45 0 0)"
            patternUnits="userSpaceOnUse"
          >
            <rect width="8" height="8" fill="#2BC7A0" />
            <line
              x1="0"
              y1="0"
              x2="0"
              y2="8"
              stroke="#FFFFFF"
              strokeWidth="2.5"
              strokeOpacity="0.45"
            />
          </pattern>

          <pattern
            id="hatchPatternCoral"
            width="8"
            height="8"
            patternTransform="rotate(45 0 0)"
            patternUnits="userSpaceOnUse"
          >
            <rect width="8" height="8" fill="#FF6B57" />
            <line
              x1="0"
              y1="0"
              x2="0"
              y2="8"
              stroke="#FFFFFF"
              strokeWidth="2.5"
              strokeOpacity="0.45"
            />
          </pattern>

          <pattern
            id="hatchPatternBlue"
            width="8"
            height="8"
            patternTransform="rotate(45 0 0)"
            patternUnits="userSpaceOnUse"
          >
            <rect width="8" height="8" fill="#5B8DEF" />
            <line
              x1="0"
              y1="0"
              x2="0"
              y2="8"
              stroke="#FFFFFF"
              strokeWidth="2.5"
              strokeOpacity="0.45"
            />
          </pattern>
        </defs>
      </svg>

      <Navbar />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {children}
      </main>
    </div>
  );
}
