import { useCallback, useEffect, useState } from "react";
import { DISCLAIMER } from "../types";

type CaptureSession = {
  id: number;
  ts_start: string;
  ts_end: string | null;
  n_windows: number;
  is_synthetic: boolean;
  on: boolean;
};

type CaptureState = {
  on: boolean;
  session_id: number | null;
  sessions: CaptureSession[];
};

function when(iso: string | null): string {
  if (!iso) {
    return "still open";
  }
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return iso;
  }
  return parsed.toLocaleString();
}

export default function Session() {
  const [state, setState] = useState<CaptureState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const response = await fetch("/api/capture");
    if (!response.ok) {
      throw new Error(`Capture status failed (${response.status})`);
    }
    setState((await response.json()) as CaptureState);
    setError(null);
  }, []);

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "Cannot reach the backend");
    });
    const timer = window.setInterval(() => {
      void load().catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Cannot reach the backend");
      });
    }, 1500);
    return () => window.clearInterval(timer);
  }, [load]);

  async function setOn(next: boolean) {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/capture", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ on: next }),
      });
      if (!response.ok) {
        throw new Error(`Could not change the session (${response.status})`);
      }
      setState((await response.json()) as CaptureState);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Cannot reach the backend");
    } finally {
      setBusy(false);
    }
  }

  const on = state?.on ?? false;

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h1 className="text-4xl font-bold tracking-tight">TremorBand</h1>
          <p className="text-lg">Session</p>
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
          Turn capture on to open a new session. Windows ingested while it is on belong to that session. Turn it off
          to end the session.
        </p>
        <div className="flex flex-wrap items-center gap-4">
          <button
            type="button"
            className={`min-h-16 min-w-48 rounded-lg px-6 text-2xl font-bold ${
              on ? "bg-[#0b3a82] text-white" : "border-2 border-[#121212] bg-white text-[#121212]"
            }`}
            aria-pressed={on}
            disabled={busy}
            onClick={() => void setOn(!on)}
          >
            {on ? "On" : "Off"}
          </button>
          <p className="text-lg" role="status">
            {on
              ? `Session ${state?.session_id ?? ""} is recording.`
              : "Capture is off. The next time you turn it on, a new session starts."}
          </p>
        </div>
        <section className="flex flex-col gap-3">
          <h2 className="text-2xl font-bold">Sessions</h2>
          {(state?.sessions.length ?? 0) === 0 ? (
            <p className="text-lg">No capture session yet.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {state?.sessions.map((row) => (
                <li key={row.id} className="rounded-lg border-2 border-[#121212] bg-white px-4 py-3 text-lg">
                  <p className="font-semibold">
                    Session {row.id}
                    {row.on ? " · recording" : " · ended"}
                    {row.is_synthetic ? " · Simulated" : ""}
                  </p>
                  <p>
                    Started {when(row.ts_start)}. {row.on ? "Still open." : `Ended ${when(row.ts_end)}.`} Windows{" "}
                    {row.n_windows}.
                  </p>
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
