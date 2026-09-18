import type { Metadata } from "next";
import "./globals.css";
import AppShell from "./components/app-shell";

export const metadata: Metadata = {
  title: "CoachLens AI · Command Center",
  description: "Evidence-driven QA diagnosis, semantic evidence review, and human validation.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body className="antialiased">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
