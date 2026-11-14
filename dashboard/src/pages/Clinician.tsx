import { useEffect, useState } from "react";
import { DISCLAIMER } from "../types";

type ReportRow = { id: number; status: string; recipient: string | null; markdown: string };
type Timing = { finding: string; confidence: string };

export default function Clinician() {
  const [reports, setReports] = useState<ReportRow[]>([]);
  const [timing, setTiming] = useState<Timing | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([fetch("/api/reports"), fetch("/api/analytics/wearing-off?days=14")])
      .then(async ([reportResponse, timingResponse]) => {
        if (!reportResponse.ok || !timingResponse.ok) {
          throw new Error("The clinician view could not be loaded.");
        }
        setReports((await reportResponse.json()) as ReportRow[]);
        setTiming((await timingResponse.json()) as Timing);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Cannot reach the backend"));
  }, []);

  const shared = reports.filter((row) => row.status === "approved" || row.status === "sent");

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h1 className="text-4xl font-bold tracking-tight">TremorBand</h1>
          <p className="text-lg">Clinician</p>
        </div>
        <p className="rounded-lg bg-[#121212] px-4 py-3 text-lg font-semibold text-white" role="note">
          {DISCLAIMER}
        </p>
      </header>
      <main className="flex flex-col gap-6">
        {error ? (
          <p className="rounded-lg border-2 border-[#6b1d1d] bg-white px-4 py-3" role="alert">
            {error}
          </p>
        ) : null}
        <p className="text-lg">Read-only. This view shows notes that were approved for sharing and the recorded timing pattern.</p>
        <section>
          <h2 className="text-2xl font-bold">Timing</h2>
          <p className="text-lg">{timing ? `${timing.finding} Confidence: ${timing.confidence}.` : "Loading."}</p>
        </section>
        <section className="flex flex-col gap-3">
          <h2 className="text-2xl font-bold">Shared notes</h2>
          {shared.length === 0 ? <p className="text-lg">No shared notes yet.</p> : null}
          {shared.map((row) => (
            <article key={row.id} className="rounded-lg border-2 border-[#121212] bg-white px-4 py-3">
              <p className="text-lg font-semibold">
                Note {row.id} · {row.status} · {row.recipient ?? "no recipient"}
              </p>
              <p className="whitespace-pre-wrap text-lg">{row.markdown}</p>
              <a className="inline-flex min-h-12 items-center font-semibold underline" href={`/api/reports/${row.id}/pdf`}>
                Download PDF
              </a>
            </article>
          ))}
        </section>
      </main>
      <footer className="pb-4 text-base">{DISCLAIMER}</footer>
    </div>
  );
}
