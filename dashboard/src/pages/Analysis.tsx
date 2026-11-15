import { useEffect, useState } from "react";
import { DISCLAIMER } from "../types";

type AgentEvent = {
  id: number;
  type: string;
  payload: Record<string, unknown> | null;
};

type RunView = {
  id: string;
  status: string;
  events: AgentEvent[];
};

type StoredSession = {
  id: number;
  test_type: string;
  ts_start: string;
  ts_end: string | null;
  is_synthetic: boolean;
  summary: Record<string, unknown> | null;
};

function when(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return iso;
  }
  return parsed.toLocaleString();
}

function analysisText(run: RunView | null): string {
  const events = run?.events ?? [];
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.type === "analysis" && typeof event.payload?.text === "string") {
      return event.payload.text;
    }
  }
  return "";
}

export default function Analysis() {
  const [sessions, setSessions] = useState<StoredSession[]>([]);
  const [run, setRun] = useState<RunView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void fetch("/api/sessions?days=366")
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Session list failed (${response.status})`);
        }
        setSessions((await response.json()) as StoredSession[]);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Cannot reach the backend");
      });
  }, []);

  useEffect(() => {
    if (!run || run.status === "finished" || run.status === "error" || run.status === "interrupted") {
      return;
    }
    const timer = window.setInterval(() => {
      void fetch(`/api/agent/runs/${run.id}`)
        .then(async (response) => {
          if (!response.ok) {
            return;
          }
          setRun((await response.json()) as RunView);
        })
        .catch(() => setError("Cannot reach the backend"));
    }, 800);
    return () => window.clearInterval(timer);
  }, [run]);

  async function analyze() {
    setError(null);
    const response = await fetch("/api/agent/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: "Review the stored sessions and analyze the movement." }),
    });
    if (!response.ok) {
      setError(`Could not start the analysis (${response.status})`);
      return;
    }
    const created = (await response.json()) as { id: string };
    setRun({ id: created.id, status: "started", events: [] });
  }

  const text = analysisText(run);
  const running = run !== null && run.status !== "finished" && run.status !== "error" && run.status !== "interrupted";

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h1 className="text-4xl font-bold tracking-tight">TremorBand</h1>
          <p className="text-lg">Analysis</p>
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
        <p className="text-lg">
          The analysis reviews stored sessions and cites their numbers. Simulated sessions stay labeled simulated. It
          does not diagnose and it does not suggest medication.
        </p>
        <button
          type="button"
          className="min-h-12 rounded-lg bg-[#0b3a82] px-4 text-lg font-bold text-white disabled:opacity-60"
          onClick={() => void analyze()}
          disabled={running}
        >
          {running ? "Analyzing movement" : "Analyze movement"}
        </button>
        <section className="flex flex-col gap-3">
          <h2 className="text-2xl font-bold">Movement analysis</h2>
          {text ? (
            <pre className="whitespace-pre-wrap rounded-lg border-2 border-[#121212] bg-white px-4 py-3 font-sans text-lg">
              {text}
            </pre>
          ) : (
            <p className="text-lg">{run ? `Status: ${run.status}` : "No analysis yet."}</p>
          )}
        </section>
        <section className="flex flex-col gap-3">
          <h2 className="text-2xl font-bold">Stored sessions</h2>
          {sessions.length === 0 ? (
            <p className="text-lg">No sessions are stored yet.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {sessions.map((row) => (
                <li key={row.id} className="rounded-lg border-2 border-[#121212] bg-white px-4 py-3 text-lg">
                  <p className="font-semibold">
                    Session {row.id} · {row.test_type}
                    {row.is_synthetic ? " · Simulated" : " · Recorded"}
                  </p>
                  <p>Started {when(row.ts_start)}.</p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </main>
      <footer className="pb-4 text-base">{DISCLAIMER}</footer>
    </div>
  );
}
