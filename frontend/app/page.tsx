import Link from "next/link";

export default function Home() {
  return (
    <main style={{ fontFamily: "system-ui, sans-serif", maxWidth: 640, margin: "64px auto", padding: "0 24px", lineHeight: 1.5 }}>
      <h1 style={{ fontSize: 28, marginBottom: 8 }}>Enrollment automation</h1>
      <p style={{ color: "#444" }}>The review console, and the two practice portals the engine submits to.</p>
      <ul>
        <li><Link href="/console">Enrollment desk: the review console (sign-in needed)</Link></li>
        <li><Link href="/portals/riverside/enroll">Riverside Academy: course application (five steps)</Link></li>
        <li><Link href="/portals/harbour/join">Harbour Sports Club: membership form (one page, plus an API)</Link></li>
      </ul>
    </main>
  );
}
