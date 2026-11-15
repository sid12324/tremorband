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

type ReviewSection = {
  id: string;
  title: string;
  lines: string[];
};

type MovementReview = {
  measure_label: string;
  concerning: boolean;
  sections: ReviewSection[];
  summary: string;
  care_plan: string | null;
};

function isReview(value: unknown): value is MovementReview {
  if (!value || typeof value !== "object") {
    return false;
  }
  const review = value as MovementReview;
  return Array.isArray(review.sections) && review.sections.length === 3 && typeof review.summary === "string";
}

function latestAnalysis(run: RunView | null): MovementReview | null {
  const events = run?.events ?? [];
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.type === "analysis" && isReview(event.payload?.review)) {
      return event.payload.review;
    }
  }
  return null;
}

export default function Analysis() {
  const [run, setRun] = useState<RunView | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  const review = latestAnalysis(run);
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
          The movement review has three sections: the average across stored sessions, the session with the highest
          median log amplitude, and the most recent session. A short summary follows. A care plan is shown only when
          that highest median log amplitude is above the comparison line. It does not diagnose and it does not suggest
          medication.
        </p>
        <button
          type="button"
          className="min-h-12 rounded-lg bg-[#0b3a82] px-4 text-lg font-bold text-white disabled:opacity-60"
          onClick={() => void analyze()}
          disabled={running}
        >
          {running ? "Analyzing movement" : "Analyze movement"}
        </button>
        <section className="flex flex-col gap-4" aria-labelledby="movement-review">
          <h2 id="movement-review" className="text-2xl font-bold">
            Movement review
          </h2>
          {review ? (
            <>
              {review.sections.map((section) => (
                <section
                  key={section.id}
                  className="flex flex-col gap-2 rounded-lg border-2 border-[#121212] bg-white px-4 py-3"
                  aria-labelledby={`review-${section.id}`}
                >
                  <h3 id={`review-${section.id}`} className="text-xl font-bold">
                    {section.title}
                  </h3>
                  {section.lines.map((line, index) => (
                    <p key={`${section.id}-${index}`} className="text-lg">
                      {line}
                    </p>
                  ))}
                </section>
              ))}
              <section
                className="flex flex-col gap-2 rounded-lg border-2 border-[#121212] bg-white px-4 py-3"
                aria-labelledby="findings-summary"
              >
                <h3 id="findings-summary" className="text-xl font-bold">
                  Summary
                </h3>
                <p className="text-lg">{review.summary}</p>
              </section>
              {review.care_plan ? (
                <section
                  className="flex flex-col gap-2 rounded-lg border-2 border-[#121212] bg-white px-4 py-3"
                  aria-labelledby="care-plan"
                >
                  <h3 id="care-plan" className="text-xl font-bold">
                    Care plan
                  </h3>
                  <p className="text-lg">{review.care_plan}</p>
                </section>
              ) : null}
            </>
          ) : (
            <p className="text-lg">{run ? `Status: ${run.status}` : "No analysis yet."}</p>
          )}
        </section>
      </main>
      <footer className="pb-4 text-base">{DISCLAIMER}</footer>
    </div>
  );
}
