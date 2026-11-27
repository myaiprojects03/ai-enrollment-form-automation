import "@fontsource/public-sans/400.css";
import "@fontsource/public-sans/600.css";
import "@fontsource/public-sans/700.css";
import type { Metadata } from "next";
import s from "./riverside.module.css";

export const metadata: Metadata = { title: "Apply for a course | Riverside Academy" };

export default function RiversideLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className={s.page}>
      <header className={s.header}>
        <div className={s.headerInner}>
          <svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true">
            <rect width="30" height="30" rx="4" fill="#0e6e78" />
            <path d="M5 12c3.3 0 3.3-3 6.7-3s3.3 3 6.6 3 3.4-3 6.7-3M5 19c3.3 0 3.3-3 6.7-3s3.3 3 6.6 3 3.4-3 6.7-3" stroke="#fff" strokeWidth="2.2" fill="none" strokeLinecap="round" />
          </svg>
          <span className={s.brand}>Riverside Academy</span>
          <span className={s.brandSub}>Admissions</span>
        </div>
      </header>
      {children}
    </div>
  );
}
