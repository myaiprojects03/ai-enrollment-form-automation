import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Enrollment automation", robots: { index: false } };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-GB">
      <body>{children}</body>
    </html>
  );
}
