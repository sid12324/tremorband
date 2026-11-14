import { useCallback, useEffect, useState, type FormEvent } from "react";
import { DISCLAIMER } from "../types";

type Dose = { id: number; ts: string; name: string; dose: string };
type Symptom = { id: number; ts: string; rating: number; note: string | null; tags: string[] };

const TAGS = ["stress", "caffeine", "poor sleep"] as const;

function shortWhen(iso: string): string {
  return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

async function readJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path} failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export default function Log() {
  const [name, setName] = useState("");
  const [dose, setDose] = useState("");
  const [rating, setRating] = useState(0);
  const [tags, setTags] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [doses, setDoses] = useState<Dose[]>([]);
  const [symptoms, setSymptoms] = useState<Symptom[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState<"dose" | "symptom" | null>(null);

  const load = useCallback(async () => {
    const [nextDoses, nextSymptoms] = await Promise.all([
      readJson<Dose[]>("/api/medications?days=14"),
      readJson<Symptom[]>("/api/symptoms?days=14"),
    ]);
    setDoses(nextDoses);
    setSymptoms(nextSymptoms);
  }, []);

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "Cannot reach the backend");
    });
  }, [load]);

  function toggleTag(tag: string) {
    setTags((current) => (current.includes(tag) ? current.filter((item) => item !== tag) : [...current, tag]));
  }

  async function saveDose(event: FormEvent) {
    event.preventDefault();
    setSaving("dose");
    setError(null);
    setNotice(null);
    try {
      const response = await fetch("/api/medications", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, dose }),
      });
      if (!response.ok) {
        throw new Error(`Could not save the dose (${response.status})`);
      }
      setName("");
      setDose("");
      setNotice("Dose saved.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the dose");
    } finally {
      setSaving(null);
    }
  }

  async function saveSymptom(event: FormEvent) {
    event.preventDefault();
    setSaving("symptom");
    setError(null);
    setNotice(null);
    try {
      const response = await fetch("/api/symptoms", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating, tags, note: note.trim() || null }),
      });
      if (!response.ok) {
        throw new Error(`Could not save the symptom log (${response.status})`);
      }
      setNote("");
      setTags([]);
      setRating(0);
      setNotice("Symptom log saved.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the symptom log");
    } finally {
      setSaving(null);
    }
  }

  const synthetic = doses.some((row) => row.dose === "synthetic demo") || symptoms.some((row) => row.note === "Synthetic demo");

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h1 className="text-4xl font-bold tracking-tight">TremorBand</h1>
          <p className="text-lg">Log</p>
        </div>
        <p className="rounded-lg bg-[#121212] px-4 py-3 text-lg font-semibold text-white" role="note">
          {DISCLAIMER}
        </p>
      </header>

      <main className="flex flex-col gap-8">
        {error ? (
          <p className="rounded-lg border-2 border-[#6b1d1d] bg-white px-4 py-3" role="alert">
            {error}
          </p>
        ) : null}
        {notice ? (
          <p className="text-lg" role="status">
            {notice}
          </p>
        ) : null}
        {synthetic ? (
          <p className="rounded-lg border-2 border-[#121212] bg-white px-4 py-3 text-lg font-semibold" role="status">
            Synthetic data
          </p>
        ) : null}

        <form className="flex flex-col gap-4" onSubmit={(event) => void saveDose(event)}>
          <h2 className="text-2xl font-bold">Logged dose</h2>
          <p className="text-lg">Save a dose you already took. This page does not suggest a dose.</p>
          <button
            type="button"
            className="min-h-12 w-full rounded-lg border-2 border-[#121212] bg-white px-4 text-lg font-semibold sm:w-auto"
            onClick={() => {
              setName("Recorded dose");
              setDose("logged");
            }}
          >
            Fill recorded dose
          </button>
          <label className="flex flex-col gap-2 text-lg font-semibold" htmlFor="dose-name">
            Name
            <input
              id="dose-name"
              className="min-h-12 rounded-lg border-2 border-[#121212] bg-white px-3 text-lg font-normal"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
              maxLength={80}
            />
          </label>
          <label className="flex flex-col gap-2 text-lg font-semibold" htmlFor="dose-amount">
            Amount logged
            <input
              id="dose-amount"
              className="min-h-12 rounded-lg border-2 border-[#121212] bg-white px-3 text-lg font-normal"
              value={dose}
              onChange={(event) => setDose(event.target.value)}
              required
              maxLength={80}
            />
          </label>
          <button
            type="submit"
            className="min-h-12 rounded-lg bg-[#0b3a82] px-4 text-lg font-bold text-white disabled:opacity-50"
            disabled={saving === "dose"}
          >
            Save dose
          </button>
        </form>

        <form className="flex flex-col gap-4" onSubmit={(event) => void saveSymptom(event)}>
          <h2 className="text-2xl font-bold">Symptom log</h2>
          <p className="text-lg">A rating you choose. It is not a diagnosis.</p>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Rating from 0 to 4">
            {[0, 1, 2, 3, 4].map((value) => (
              <button
                key={value}
                type="button"
                className={`min-h-12 min-w-12 rounded-lg border-2 border-[#121212] px-4 text-lg font-bold ${
                  rating === value ? "bg-[#121212] text-white" : "bg-white text-[#121212]"
                }`}
                aria-pressed={rating === value}
                onClick={() => setRating(value)}
              >
                {value}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Tags">
            {TAGS.map((tag) => (
              <button
                key={tag}
                type="button"
                className={`min-h-12 rounded-lg border-2 border-[#121212] px-4 text-lg font-semibold ${
                  tags.includes(tag) ? "bg-[#121212] text-white" : "bg-white text-[#121212]"
                }`}
                aria-pressed={tags.includes(tag)}
                onClick={() => toggleTag(tag)}
              >
                {tag}
              </button>
            ))}
          </div>
          <label className="flex flex-col gap-2 text-lg font-semibold" htmlFor="symptom-note">
            Note
            <textarea
              id="symptom-note"
              className="min-h-24 rounded-lg border-2 border-[#121212] bg-white px-3 py-2 text-lg font-normal"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              maxLength={280}
            />
          </label>
          <button
            type="submit"
            className="min-h-12 rounded-lg bg-[#0b3a82] px-4 text-lg font-bold text-white disabled:opacity-50"
            disabled={saving === "symptom"}
          >
            Save symptom log
          </button>
        </form>

        <section className="flex flex-col gap-3">
          <h2 className="text-2xl font-bold">Recent doses</h2>
          {doses.length === 0 ? (
            <p className="text-lg">No doses in the last 14 days.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {[...doses].reverse().map((row) => (
                <li key={row.id} className="rounded-lg border-2 border-[#121212] bg-white px-4 py-3 text-lg">
                  <span className="tabular">{shortWhen(row.ts)}</span> {row.name} ({row.dose})
                  {row.dose === "synthetic demo" ? " · Synthetic" : ""}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-2xl font-bold">Recent symptom logs</h2>
          {symptoms.length === 0 ? (
            <p className="text-lg">No symptom logs in the last 14 days.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {[...symptoms].reverse().map((row) => (
                <li key={row.id} className="rounded-lg border-2 border-[#121212] bg-white px-4 py-3 text-lg">
                  <span className="tabular">{shortWhen(row.ts)}</span> rating {row.rating}
                  {row.tags.length > 0 ? ` · ${row.tags.join(", ")}` : ""}
                  {row.note ? ` · ${row.note}` : ""}
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
