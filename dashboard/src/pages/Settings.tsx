import { useEffect, useState, type FormEvent } from "react";
import { DISCLAIMER } from "../types";

type Settings = {
  transport: "wifi" | "serial" | "simulator";
  ms_mode: boolean;
  sleep_start_hour: number;
  sleep_end_hour: number;
  haptic_intensity: number;
};

const STEPS = [
  "Open Trends and read the 3 to 5 hour comparison.",
  "Open Log and save a rating you choose.",
  "Open Agent and run the weekly review.",
  "Open Report and approve, edit, or reject the note.",
];

export default function Settings() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [demo, setDemo] = useState(() => window.localStorage.getItem("tremorband-demo") === "on");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    void fetch("/api/settings")
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Settings failed (${response.status})`);
        }
        setSettings((await response.json()) as Settings);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Cannot reach the backend"));
  }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!settings) {
      return;
    }
    const response = await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    });
    if (!response.ok) {
      setError(`Could not save settings (${response.status})`);
      return;
    }
    setSettings((await response.json()) as Settings);
    setNotice("Settings saved.");
  }

  async function enableDemo() {
    const response = await fetch("/api/demo/reset", { method: "POST" });
    if (!response.ok) {
      setError(`Could not load the synthetic week (${response.status})`);
      return;
    }
    window.localStorage.setItem("tremorband-demo", "on");
    setDemo(true);
    setNotice("Synthetic week loaded.");
  }

  async function removeData(event: FormEvent) {
    event.preventDefault();
    const response = await fetch("/api/data", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm }),
    });
    if (!response.ok) {
      setError("Type delete my data to remove the stored rows.");
      return;
    }
    setConfirm("");
    setNotice("Stored rows were deleted.");
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h1 className="text-4xl font-bold tracking-tight">TremorBand</h1>
          <p className="text-lg">Settings</p>
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
        {notice ? <p role="status">{notice}</p> : null}
        {settings ? (
          <form className="flex flex-col gap-4" onSubmit={(event) => void save(event)}>
            <h2 className="text-2xl font-bold">Preferences</h2>
            <label className="flex flex-col gap-2 text-lg font-semibold" htmlFor="transport">
              Transport
              <select
                id="transport"
                className="min-h-12 rounded-lg border-2 border-[#121212] bg-white px-3 text-lg"
                value={settings.transport}
                onChange={(event) =>
                  setSettings({ ...settings, transport: event.target.value as Settings["transport"] })
                }
              >
                <option value="simulator">Simulator</option>
                <option value="wifi">Wi-Fi</option>
                <option value="serial">Serial</option>
              </select>
            </label>
            <label className="flex min-h-12 items-center gap-3 text-lg font-semibold" htmlFor="ms-mode">
              <input
                id="ms-mode"
                type="checkbox"
                className="h-6 w-6"
                checked={settings.ms_mode}
                onChange={(event) => setSettings({ ...settings, ms_mode: event.target.checked })}
              />
              MS mode
            </label>
            <label className="flex flex-col gap-2 text-lg font-semibold" htmlFor="sleep-start">
              Sleep starts (hour)
              <input
                id="sleep-start"
                type="number"
                min={0}
                max={23}
                className="min-h-12 rounded-lg border-2 border-[#121212] bg-white px-3 text-lg"
                value={settings.sleep_start_hour}
                onChange={(event) => setSettings({ ...settings, sleep_start_hour: Number(event.target.value) })}
              />
            </label>
            <label className="flex flex-col gap-2 text-lg font-semibold" htmlFor="sleep-end">
              Sleep ends (hour)
              <input
                id="sleep-end"
                type="number"
                min={0}
                max={23}
                className="min-h-12 rounded-lg border-2 border-[#121212] bg-white px-3 text-lg"
                value={settings.sleep_end_hour}
                onChange={(event) => setSettings({ ...settings, sleep_end_hour: Number(event.target.value) })}
              />
            </label>
            <label className="flex flex-col gap-2 text-lg font-semibold" htmlFor="haptic">
              Haptic intensity ({settings.haptic_intensity})
              <input
                id="haptic"
                type="range"
                min={0}
                max={100}
                className="min-h-12"
                value={settings.haptic_intensity}
                onChange={(event) => setSettings({ ...settings, haptic_intensity: Number(event.target.value) })}
              />
            </label>
            <button type="submit" className="min-h-12 rounded-lg bg-[#0b3a82] px-4 text-lg font-bold text-white">
              Save settings
            </button>
          </form>
        ) : null}
        <section className="flex flex-col gap-3">
          <h2 className="text-2xl font-bold">Demo mode</h2>
          <p className="text-lg">Loads seven synthetic days. The script walks the pages. It is not a diagnosis.</p>
          <button type="button" className="min-h-12 rounded-lg border-2 border-[#121212] bg-white px-4 text-lg font-bold" onClick={() => void enableDemo()}>
            {demo ? "Reload synthetic week" : "Turn on demo mode"}
          </button>
          {demo ? (
            <ol className="flex flex-col gap-2 text-lg">
              {STEPS.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          ) : null}
        </section>
        <section className="flex flex-col gap-3">
          <h2 className="text-2xl font-bold">Your data</h2>
          <a className="inline-flex min-h-12 items-center text-lg font-semibold underline" href="/api/export.csv">
            Export CSV
          </a>
          <form className="flex flex-col gap-3" onSubmit={(event) => void removeData(event)}>
            <label className="flex flex-col gap-2 text-lg font-semibold" htmlFor="delete-confirm">
              Type delete my data
              <input
                id="delete-confirm"
                className="min-h-12 rounded-lg border-2 border-[#121212] bg-white px-3 text-lg font-normal"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
              />
            </label>
            <button type="submit" className="min-h-12 rounded-lg border-2 border-[#6b1d1d] bg-white px-4 text-lg font-bold">
              Delete all data
            </button>
          </form>
        </section>
      </main>
      <footer className="pb-4 text-base">{DISCLAIMER}</footer>
    </div>
  );
}
