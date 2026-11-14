import { useEffect, useState } from "react";
import { DISCLAIMER } from "../types";

type ReportRow = {
  id: number;
  created_at: string;
  markdown: string;
  status: string;
  recipient: string | null;
};

type RunList = { id: string };
type RunView = {
  id: string;
  status: string;
  interrupts: { value: { action_requests?: { name: string; args: { report_id?: number; recipient?: string } }[] } }[];
};

function blocks(markdown: string) {
  return markdown.split("\n").map((line, index) => {
    if (line.startsWith("# ")) {
      return (
        <h2 key={index} className="text-2xl font-bold">
          {line.slice(2)}
        </h2>
      );
    }
    if (line.startsWith("## ")) {
      return (
        <h3 key={index} className="text-xl font-bold">
          {line.slice(3)}
        </h3>
      );
    }
    if (!line.trim()) {
      return <div key={index} className="h-2" />;
    }
    return (
      <p key={index} className="text-lg">
        {line}
      </p>
    );
  });
}

export default function Report() {
  const reportId = Number(window.location.hash.split("/")[2] || "0");
  const [reports, setReports] = useState<ReportRow[]>([]);
  const [selectedId, setSelectedId] = useState(reportId);
  const [run, setRun] = useState<RunView | null>(null);
  const [recipient, setRecipient] = useState("clinician");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function load() {
    const response = await fetch("/api/reports");
    if (!response.ok) {
      throw new Error(`Reports failed (${response.status})`);
    }
    const rows = (await response.json()) as ReportRow[];
    setReports(rows);
    const nextId = selectedId || rows[0]?.id || 0;
    if (nextId && nextId !== selectedId) {
      setSelectedId(nextId);
    }
    const runs = await fetch("/api/agent/runs");
    if (!runs.ok) {
      return;
    }
    const listed = (await runs.json()) as RunList[];
    for (const item of listed) {
      const detail = await fetch(`/api/agent/runs/${item.id}`);
      if (!detail.ok) {
        continue;
      }
      const view = (await detail.json()) as RunView;
      const action = view.interrupts[0]?.value.action_requests?.[0];
      if (view.status === "interrupted" && action?.name === "send_report") {
        setRun(view);
        if (action.args.recipient) {
          setRecipient(action.args.recipient);
        }
        return;
      }
    }
  }

  useEffect(() => {
    void load().catch((err: unknown) => setError(err instanceof Error ? err.message : "Cannot reach the backend"));
  }, []);

  const selected = reports.find((row) => row.id === selectedId) ?? reports[0];
  const waiting = run?.interrupts[0]?.value.action_requests?.[0];
  const waitingForThis = waiting?.name === "send_report" && waiting.args.report_id === selected?.id;

  async function resume(decision: { type: string; edited_action?: { name: string; args: Record<string, unknown> }; message?: string }) {
    if (!run) {
      return;
    }
    const response = await fetch("/api/agent/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: run.id, decisions: [decision] }),
    });
    if (!response.ok) {
      setError(`Could not send the decision (${response.status})`);
      return;
    }
    setNotice(decision.type === "reject" ? "The note was not shared." : "Decision sent.");
    window.setTimeout(() => {
      void load().catch(() => undefined);
    }, 1000);
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h1 className="text-4xl font-bold tracking-tight">TremorBand</h1>
          <p className="text-lg">Report</p>
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
        {notice ? <p role="status">{notice}</p> : null}
        <div className="flex flex-wrap gap-2">
          {reports.map((row) => (
            <button
              key={row.id}
              type="button"
              className={`min-h-12 rounded-lg border-2 border-[#121212] px-4 text-lg font-semibold ${
                selected?.id === row.id ? "bg-[#121212] text-white" : "bg-white"
              }`}
              onClick={() => setSelectedId(row.id)}
            >
              Note {row.id} ({row.status})
            </button>
          ))}
        </div>
        {selected ? (
          <article className="flex flex-col gap-3 rounded-lg border-2 border-[#121212] bg-white px-4 py-4">
            <p className="text-lg">
              Status: {selected.status}. Recipient: {selected.recipient ?? "not set"}.
            </p>
            {blocks(selected.markdown)}
            <a className="inline-flex min-h-12 items-center font-semibold underline" href={`/api/reports/${selected.id}/pdf`}>
              Download PDF
            </a>
          </article>
        ) : (
          <p className="text-lg">No notes yet. Run a weekly review from the Agent page.</p>
        )}
        {waitingForThis ? (
          <section className="flex flex-col gap-3">
            <h2 className="text-2xl font-bold">Approval</h2>
            <p className="text-lg">Sharing sends this note to the recipient. It does not change a dose.</p>
            <label className="flex flex-col gap-2 text-lg font-semibold" htmlFor="recipient">
              Recipient
              <input
                id="recipient"
                className="min-h-12 rounded-lg border-2 border-[#121212] bg-white px-3 text-lg font-normal"
                value={recipient}
                onChange={(event) => setRecipient(event.target.value)}
              />
            </label>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="min-h-12 rounded-lg bg-[#0b3a82] px-4 text-lg font-bold text-white"
                onClick={() =>
                  void resume({
                    type: "approve",
                  })
                }
              >
                Approve
              </button>
              <button
                type="button"
                className="min-h-12 rounded-lg border-2 border-[#121212] bg-white px-4 text-lg font-bold"
                onClick={() =>
                  void resume({
                    type: "edit",
                    edited_action: {
                      name: "send_report",
                      args: { report_id: selected?.id, recipient },
                    },
                  })
                }
              >
                Edit and approve
              </button>
              <button
                type="button"
                className="min-h-12 rounded-lg border-2 border-[#6b1d1d] bg-white px-4 text-lg font-bold"
                onClick={() => void resume({ type: "reject", message: "Do not share this note." })}
              >
                Reject
              </button>
            </div>
          </section>
        ) : null}
      </main>
      <footer className="pb-4 text-base">{DISCLAIMER}</footer>
    </div>
  );
}
