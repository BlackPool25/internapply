import type { Metadata } from "next";
import { ColorSchemeScript } from "@mantine/core";
import "@mantine/core/styles.layer.css";
import "./globals.css";
import { Providers } from "./providers";
import { cabinetGrotesk, generalSans, jetbrainsMono } from "./fonts";

export const metadata: Metadata = {
  title: "InternApply — Opportunity Pipeline & Outreach",
  description: "Autonomous internship and freelance opportunity discovery, ranking, and outreach tracker.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${cabinetGrotesk.variable} ${generalSans.variable} ${jetbrainsMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <ColorSchemeScript defaultColorScheme="light" />
      </head>
      <body className="bg-[#F0EFEC] text-[#17171A] font-sans antialiased selection:bg-[#7C5CFC]/20 selection:text-[#7C5CFC]">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
