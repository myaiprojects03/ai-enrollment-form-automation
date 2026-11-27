import "@fontsource/barlow/400.css";
import "@fontsource/barlow/600.css";
import "@fontsource/barlow/700.css";
import "@fontsource/barlow-condensed/600.css";
import "@fontsource/barlow-condensed/700.css";
import type { Metadata } from "next";
import s from "./harbour.module.css";

export const metadata: Metadata = { title: "Join | Harbour Sports Club" };

export default function HarbourLayout({ children }: { children: React.ReactNode }) {
  return <div className={s.page}>{children}</div>;
}
