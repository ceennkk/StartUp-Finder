import type { Metadata } from "next";
import type { ReactNode } from "react";
import { LanguageProvider } from "../finder/i18n";
import "../finder/htgf-base.css";
import "../finder/finder-app.css";
import "../collector/collector-dashboard.css";
import "../finder/htgf-brand.css";

export const metadata: Metadata = {
  title: "Pre-Round Startup Finder",
  description: "Discover early-stage technology startups before their first equity round.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0 }}><LanguageProvider>{children}</LanguageProvider></body>
    </html>
  );
}
