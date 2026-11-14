import { useEffect, useState } from "react";
import { DISCLAIMER } from "../types";

type Device = { id: string; name: string };
type SessionRow = {
  id: number;
  test_type: string;
  ts_start: string;
  ts_end: string | null;
  summary: Record<string, number | boolean | null> | null;
  is_synthetic: boolean;
};
type PassiveRow = { id: number; ts: string; tremor_pct: number; median_hz: number; activity: number };
type TremorDay = { day: string; tremor_hours: number };

const TESTS = [
  { id: "rest", label: "Rest", seconds: 20 },
  { id: "postural", label: "Postural", seconds: 20 },
  { id: "finger_nose", label: "Finger to nose", seconds: 20 },
  { id: "tapping", label: "Tapping", seconds: 10 },
  { id: "gait", label: "Gait", seconds: 30 },
];

function num(summary: SessionRow["summary"], key: string): string {
  const value = summary?.[key];
  return typeof value === "number" ? value.toFixed(2) : "—";
}

export default function Tests() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [deviceId, setDeviceId] = useState("");
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [passive, setPassive] = useState<PassiveRow[]>([]);
  const [hours, setHours] = useState<TremorDay[]>([]);
  const [left, setLeft] = useState(0);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const [deviceResponse, sessionResponse, passiveResponse, hoursResponse] = await Promise.all([
      fetch("/api/devices"),
      fetch("/api/sessions?days=2"),
      fetch("/api/passive?days=1"),
      fetch("/api/analytics/tremor-hours?days=1"),
    ]);
    if (!deviceResponse.ok || !sessionResponse.ok || !passiveResponse.ok || !hoursResponse.ok) {
      throw new Error("The test list could not be loaded.");
    }
    const nextDevices = (await deviceResponse.json()) as Device[];
    setDevices(nextDevices);
    setDeviceId((current) => current || nextDevices[0]?.id || "");
    setSessions((await sessionResponse.json()) as SessionRow[]);
    setPassive((await passiveResponse.json()) as PassiveRow[]);
    setHours((await hoursResponse.json()) as TremorDay[]);
  }

  useEffect(() => {
    void load().catch((err: unknown) => setError(err instanceof Error ? err.message : "Cannot reach the backend"));
  }, []);

  useEffect(() => {
    if (left <= 0) {
      return;
    }
    const timer = window.setTimeout(() => setLeft((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [left]);

  async function start(test: (typeof TESTS)[number]) {
    if (!deviceId) {
      setError("No band has checked in.");
      return;
    }
    setError(null);
    const response = await fetch("/api/commands", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        device_id: deviceId,
        cmd: `run_test:${test.id}`,
        created_by: "user",
        reason: "Started from the Tests page.",
      }),
    });
    if (!response.ok) {
      setError(`Could not start ${test.label} (${response.status})`);
      return;
    }
    setRunning(test.label);
    setLeft(test.seconds);
    window.setTimeout(() => {
      void load().catch(() => undefined);
    }, (test.seconds + 3) * 1000);
  }

  const latest = new Map<string, SessionRow>();
  for (const row of sessions) {
    latest.set(row.test_type, row);
  }
  const todayHours = hours.reduce((sum, row) => sum + row.tremor_hours, 0);

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h1 className="text-4xl font-bold tracking-tight">TremorBand</h1>
          <p className="text-lg">Tests</p>
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
        <label className="flex flex-col gap-2 text-lg font-semibold" htmlFor="test-band">
          Band
          <select
            id="test-band"
            className="min-h-12 rounded-lg border-2 border-[#121212] bg-white px-3 text-lg"
            value={deviceId}
            onChange={(event) => setDeviceId(event.target.value)}
          >
            {devices.map((device) => (
              <option key={device.id} value={device.id}>
                {device.name}
              </option>
            ))}
          </select>
        </label>
        <div className="flex flex-wrap gap-2">
          {TESTS.map((test) => (
            <button
              key={test.id}
              type="button"
              className="min-h-12 rounded-lg border-2 border-[#121212] bg-white px-4 text-lg font-bold"
              onClick={() => void start(test)}
            >
              {test.label}
            </button>
          ))}
        </div>
        <p className="text-2xl font-bold tabular" role="status">
          {left > 0 ? `${running}: ${left}s` : "Idle"}
        </p>
        <section className="grid gap-3 sm:grid-cols-2">
          {TESTS.map((test) => {
            const row = latest.get(test.id);
            return (
              <article key={test.id} className="rounded-lg border-2 border-[#121212] bg-white px-4 py-3">
                <h2 className="text-xl font-bold">{test.label}</h2>
                <p className="text-lg">Peak Hz {num(row?.summary ?? null, "median_hz")}</p>
                <p className="text-lg">Log amplitude {num(row?.summary ?? null, "median_log_amp")}</p>
                <p className="text-lg">Tremor % {num(row?.summary ?? null, "tremor_pct")}</p>
                {test.id === "tapping" ? (
                  <>
                    <p className="text-lg">Taps/s {num(row?.summary ?? null, "taps_per_s")}</p>
                    <p className="text-lg">Decrement {num(row?.summary ?? null, "tap_decrement")}</p>
                  </>
                ) : null}
                {test.id === "gait" ? (
                  <p className="text-lg">Asymmetry % {num(row?.summary ?? null, "asymmetry_pct")}</p>
                ) : null}
                {row?.is_synthetic ? <p className="text-lg">Synthetic</p> : null}
              </article>
            );
          })}
        </section>
        <section>
          <h2 className="text-2xl font-bold">Passive monitoring</h2>
          <p className="text-lg">
            Summaries in the last day: {passive.length}. Tremor time from those gaps: {todayHours.toFixed(2)} h.
          </p>
        </section>
      </main>
      <footer className="pb-4 text-base">{DISCLAIMER}</footer>
    </div>
  );
}
