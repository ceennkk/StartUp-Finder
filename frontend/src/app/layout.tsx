import type { Metadata } from "next";
import type { ReactNode } from "react";
import "../finder/htgf-base.css";
import "../finder/finder-app.css";
import "../collector/collector-dashboard.css";

export const metadata: Metadata = {
  title: "StartUp Finder",
  description: "Kandidaten entdecken, prüfen und priorisieren.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="de">
      <body style={{ margin: 0 }}>{children}</body>
    </html>
  );
}
