import type { Metadata } from "next";
import { ColorSchemeScript } from "@mantine/core";
import "@mantine/core/styles.layer.css";
import "mantine-datatable/styles.layer.css";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "InternApply",
  description: "InternApply — Application Tracking Dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <ColorSchemeScript defaultColorScheme="light" />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
