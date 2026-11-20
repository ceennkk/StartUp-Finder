import type { Metadata } from "next";
import type { ReactNode } from "react";
import "../finder/htgf-base.css";
import "../finder/finder-app.css";

export const metadata: Metadata = {
  title: "Startup Finder",
  description: "Arbeitsoberfläche für VC-Sourcing in Deutschland.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="de">
      <body style={{ margin: 0 }}>{children}</body>
    </html>
  );
}
