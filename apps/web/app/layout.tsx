import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Review Workspace | CoachLens AI",
  description: "Evidence-driven QA diagnosis and human validation.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
