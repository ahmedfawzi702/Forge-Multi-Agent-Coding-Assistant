import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Forge — Coding workspace",
  description: "Your codebase, with context. A local AI engineering workspace.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
