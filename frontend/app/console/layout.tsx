import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import type { Metadata } from "next";
import s from "./console.module.css";

export const metadata: Metadata = { title: "Enrollment desk", robots: { index: false } };

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return <div className={s.app}>{children}</div>;
}
