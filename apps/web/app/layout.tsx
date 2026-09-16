import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CoachLens AI",
  description: "An evidence-driven performance diagnosis and training platform in development.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
