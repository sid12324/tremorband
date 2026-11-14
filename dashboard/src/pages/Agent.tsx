import { useEffect, useState, type FormEvent } from "react";
import { DISCLAIMER } from "../types";

type AgentEvent = {
  id: number;
  type: string;
  payload: Record<string, unknown> | null;
};

type InterruptAction = {
  name: string;
  args: Record<string, unknown>;
};

type RunView = {
  id: string;
  status: string;
  events: AgentEvent[];
  interrupts: { id: string; value: { action_requests?: InterruptAction[] } }[];
};

const STEPS = [
  "Compare with the personal baseline",
  "Check whether another test is useful",
  "Draft the clinician note",
  "Wait for approval before sharing",
];

function actionOf(run: RunView | null): InterruptAction | null {
  return run?.interrupts?.[0]?.value?.action_requests?.[0] ?? null;
}

export default function Agent() {
  const [prompt, setPrompt] = useState("");
  const [run, setRun] = useState<RunView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

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

  async function start(text: string) {
    setError(null);
    setNotice(null);
    const response = await fetch("/api/agent/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: text }),
    });
    if (!response.ok) {
      setError(`Could not start the review (${response.status})`);
      return;
    }
    const created = (await response.json()) as { id: string };
    sessionStorage.setItem("tremorband-run", created.id);
    setRun({ id: created.id, status: "started", events: [], interrupts: [] });
  }

  async function decide(type: "approve" | "reject") {
    if (!run) {
      return;
    }
    const response = await fetch("/api/agent/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        thread_id: run.id,
        decisions: [{ type, message: type === "reject" ? "Leave the line where it is." : undefined }],
      }),
    });
    if (!response.ok) {
      setError(`Could not send the decision (${response.status})`);
      return;
    }
    setNotice(type === "approve" ? "Approval sent." : "Decision sent.");
    setRun({ ...run, status: "resuming", interrupts: [] });
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!prompt.trim()) {
      return;
    }
    await start(prompt.trim());
    setPrompt("");
  }

  const names = (run?.events ?? []).flatMap((item) => {
    const payload = item.payload ?? {};
    if (item.type === "tool" && typeof payload.name === "string") {
      return [payload.name];
    }
    if (item.type === "step") {
      return Object.values(payload).flatMap((value) => (Array.isArray(value) ? value.map(String) : []));
    }
    return [];
  });
  const checks = [
    names.some((name) => name.includes("trend") || name === "get_metrics"),
    names.includes("plan_tests") || names.includes("assessment-scheduler"),
    names.includes("draft_report"),
    run?.status === "interrupted" || names.includes("send_report"),
  ];
  const action = actionOf(run);
  const triggered = (run?.events ?? []).some((item) => item.type === "trigger_test" && item.payload?.queued === true);

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h1 className="text-4xl font-bold tracking-tight">TremorBand</h1>
          <p className="text-lg">Agent</p>
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
        <p className="text-lg">The planner cites recorded numbers. It does not suggest a dose or make a diagnosis.</p>
        <button
          type="button"
          className="min-h-12 rounded-lg bg-[#0b3a82] px-4 text-lg font-bold text-white"
          onClick={() => void start("Run the weekly review.")}
        >
          Run weekly review
        </button>
        <form className="flex flex-col gap-3 sm:flex-row" onSubmit={(event) => void onSubmit(event)}>
          <label className="flex flex-1 flex-col gap-2 text-lg font-semibold" htmlFor="agent-prompt">
            Message
            <input
              id="agent-prompt"
              className="min-h-12 rounded-lg border-2 border-[#121212] bg-white px-3 text-lg font-normal"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
            />
          </label>
          <button type="submit" className="min-h-12 rounded-lg border-2 border-[#121212] bg-white px-4 text-lg font-bold">
            Send
          </button>
        </form>
        <section className="flex flex-col gap-2">
          <h2 className="text-2xl font-bold">To-do</h2>
          <ol className="flex flex-col gap-2 text-lg">
            {STEPS.map((step, index) => (
              <li key={step}>
                {checks[index] ? "Done. " : "Open. "}
                {step}
              </li>
            ))}
          </ol>
        </section>
        {triggered ? (
          <p className="rounded-lg border-2 border-[#121212] bg-white px-4 py-3 text-lg" role="status">
            The band was asked to buzz and run a test.
          </p>
        ) : null}
        {notice ? <p role="status">{notice}</p> : null}
        {action?.name === "update_baseline" ? (
          <section className="flex flex-col gap-3">
            <h2 className="text-2xl font-bold">Approval</h2>
            <p className="text-lg">
              Move the {String(action.args.test_type)} comparison line to {String(action.args.threshold_z)}.{" "}
              {String(action.args.rationale ?? "")}
            </p>
            <div className="flex flex-wrap gap-2">
              <button type="button" className="min-h-12 rounded-lg bg-[#0b3a82] px-4 text-lg font-bold text-white" onClick={() => void decide("approve")}>
                Approve
              </button>
              <button type="button" className="min-h-12 rounded-lg border-2 border-[#121212] bg-white px-4 text-lg font-bold" onClick={() => void decide("reject")}>
                Reject
              </button>
            </div>
          </section>
        ) : null}
        {action?.name === "send_report" ? (
          <p className="text-lg">
            A note is waiting for approval.{" "}
            <a className="font-semibold underline" href={`#/report/${String(action.args.report_id)}`}>
              Open the report
            </a>
          </p>
        ) : null}
        <section className="flex flex-col gap-2">
          <h2 className="text-2xl font-bold">Timeline</h2>
          {run ? <p className="text-lg">Status: {run.status}</p> : <p className="text-lg">No review is running.</p>}
          <ol className="flex flex-col gap-2">
            {(run?.events ?? []).slice(-12).map((item) => (
              <li key={item.id} className="rounded-lg border-2 border-[#121212] bg-white px-4 py-3 text-lg">
                {item.type}
                {item.payload?.name ? `: ${String(item.payload.name)}` : ""}
                {item.payload?.phase ? `: ${String(item.payload.phase)}` : ""}
              </li>
            ))}
          </ol>
        </section>
      </main>
      <footer className="pb-4 text-base">{DISCLAIMER}</footer>
    </div>
  );
}
