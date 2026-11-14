import { useEffect, useState, type FormEvent } from "react";
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatNumber } from "../format";
import { DISCLAIMER, type DeviceStatus, type LiveWindow } from "../types";

type RigRun = {
  id: number;
  ts: string;
  set_hz: number;
  measured_hz: number | null;
  band_hz: number | null;
  amp_set: number | null;
  amp_band: number | null;
};

type RigPoint = RigRun & {
  compared_hz: number;
  error_hz: number;
  error_pct: number;
};

type FrequencyRow = {
  set_hz: number;
  n: number;
  mean_band_hz: number | null;
  mean_measured_hz: number | null;
  mae_hz: number;
  mean_pct_error: number;
};

type Accuracy = {
  mae_hz: number | null;
  n: number;
  rows: FrequencyRow[];
  points: RigPoint[];
};

function sentence(point: {
  set_hz: number;
  band_hz: number | null;
  measured_hz: number | null;
  error_pct?: number;
}): string {
  const compared = point.band_hz ?? point.measured_hz;
  const setText = formatNumber(point.set_hz, 2);
  if (compared == null) {
    return `Rig set ${setText} Hz | no measurement yet`;
  }
  const pct = point.error_pct ?? ((compared - point.set_hz) / point.set_hz) * 100;
  const source = point.band_hz != null ? "Band measured" : "Rig measured";
  return `Rig set ${setText} Hz | ${source} ${formatNumber(compared, 2)} Hz | error ${formatNumber(pct, 1)}%`;
}

function optionalHz(value: number | null): string {
  return value == null ? "—" : formatNumber(value, 2);
}

export default function Calibration() {
  const [devices, setDevices] = useState<DeviceStatus[]>([]);
  const [selectedId, setSelectedId] = useState<string | null | undefined>(undefined);
  const [latest, setLatest] = useState<LiveWindow | null>(null);
  const [accuracy, setAccuracy] = useState<Accuracy | null>(null);
  const [setHz, setSetHz] = useState("5");
  const [amp, setAmp] = useState("10");
  const [measured, setMeasured] = useState("");
  const [pairBand, setPairBand] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [posted, setPosted] = useState<RigRun | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadAccuracy() {
      const response = await fetch("/api/rig/accuracy");
      if (!response.ok) {
        throw new Error(`Accuracy failed (${response.status})`);
      }
      const body = (await response.json()) as Accuracy;
      if (!cancelled) {
        setAccuracy(body);
      }
    }

    async function loadDevices() {
      const response = await fetch("/api/devices");
      if (!response.ok) {
        throw new Error(`Device list failed (${response.status})`);
      }
      const found = (await response.json()) as DeviceStatus[];
      if (cancelled) {
        return;
      }
      setDevices(found);
      setSelectedId((current) => (current === undefined ? (found[0]?.id ?? null) : current));
    }

    async function tick() {
      try {
        await Promise.all([loadAccuracy(), loadDevices()]);
        if (!cancelled) {
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Cannot reach the backend");
        }
      }
    }

    void tick();
    const timer = window.setInterval(() => void tick(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setLatest(null);
      return;
    }
    let cancelled = false;
    async function loadLatest() {
      const response = await fetch(`/api/windows?device_id=${encodeURIComponent(selectedId ?? "")}&limit=1`);
      if (!response.ok) {
        return;
      }
      const rows = (await response.json()) as LiveWindow[];
      if (!cancelled) {
        setLatest(rows.length > 0 ? rows[rows.length - 1] : null);
      }
    }
    void loadLatest();
    const timer = window.setInterval(() => void loadLatest(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [selectedId]);

  async function record(event: FormEvent) {
    event.preventDefault();
    const setpoint = Number(setHz);
    const amplitude = Number(amp);
    const rigMeasured = measured.trim() === "" ? null : Number(measured);
    if (!Number.isFinite(setpoint) || setpoint <= 0 || setpoint > 30) {
      setError("Setpoint must be greater than 0 Hz and at most 30 Hz.");
      return;
    }
    if (!Number.isFinite(amplitude) || amplitude < 0 || amplitude > 180) {
      setError("Amplitude must be between 0 and 180 degrees.");
      return;
    }
    if (rigMeasured != null && (!Number.isFinite(rigMeasured) || rigMeasured < 0)) {
      setError("Rig measured Hz must be a positive number, or left blank.");
      return;
    }
    setRecording(true);
    try {
      const response = await fetch("/api/rig/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          set_hz: setpoint,
          amp_set: amplitude,
          measured_hz: rigMeasured,
          band_hz: pairBand && latest ? latest.peak_hz : null,
          amp_band: pairBand && latest ? latest.amp_deg : null,
        }),
      });
      if (!response.ok) {
        throw new Error(`Record failed (${response.status})`);
      }
      const saved = (await response.json()) as RigRun;
      setPosted(saved);
      const accuracyResponse = await fetch("/api/rig/accuracy");
      if (accuracyResponse.ok) {
        setAccuracy((await accuracyResponse.json()) as Accuracy);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Record failed");
    } finally {
      setRecording(false);
    }
  }

  const newest = accuracy && accuracy.points.length > 0 ? accuracy.points[accuracy.points.length - 1] : posted;
  const maxAxis = Math.max(
    8,
    ...(accuracy?.points ?? []).map((point) => Math.max(point.set_hz, point.compared_hz)),
  );
  const identity = [
    { set_hz: 0, compared_hz: 0 },
    { set_hz: maxAxis, compared_hz: maxAxis },
  ];

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h1 className="text-4xl font-bold tracking-tight">TremorBand</h1>
          <p className="text-lg">Calibration</p>
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

        <section className="rounded-lg border-2 border-[#121212] bg-white p-4" aria-labelledby="setpoint-heading">
          <h2 id="setpoint-heading" className="text-2xl font-bold">
            Setpoint
          </h2>
          <p className="mt-1 text-base">
            Type the rig frequency, or the frequency you asked the servo to hold. Pair it with the band window when one is posting.
          </p>
          <form className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3" onSubmit={(event) => void record(event)}>
            <label className="flex flex-col gap-2 text-lg font-semibold" htmlFor="set-hz">
              Setpoint Hz
              <input
                id="set-hz"
                className="min-h-12 rounded-lg border-2 border-[#121212] bg-white px-3 text-2xl"
                inputMode="decimal"
                value={setHz}
                onChange={(event) => setSetHz(event.target.value)}
              />
            </label>
            <label className="flex flex-col gap-2 text-lg font-semibold" htmlFor="amp-deg">
              Amplitude deg
              <input
                id="amp-deg"
                className="min-h-12 rounded-lg border-2 border-[#121212] bg-white px-3 text-2xl"
                inputMode="decimal"
                value={amp}
                onChange={(event) => setAmp(event.target.value)}
              />
            </label>
            <label className="flex flex-col gap-2 text-lg font-semibold" htmlFor="measured-hz">
              Rig measured Hz
              <input
                id="measured-hz"
                className="min-h-12 rounded-lg border-2 border-[#121212] bg-white px-3 text-2xl"
                inputMode="decimal"
                value={measured}
                onChange={(event) => setMeasured(event.target.value)}
                placeholder="Optional"
              />
            </label>
            <div className="lg:col-span-3 flex flex-col gap-3">
              <p className="text-lg font-semibold">Band</p>
              <div className="flex flex-wrap gap-2" role="group" aria-label="Bands">
                <button
                  type="button"
                  aria-pressed={selectedId === null}
                  className={`min-h-12 rounded-lg border-2 border-[#121212] px-4 text-lg font-semibold ${
                    selectedId === null ? "bg-[#121212] text-white" : "bg-white"
                  }`}
                  onClick={() => setSelectedId(null)}
                >
                  No band
                </button>
                {devices.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    aria-pressed={item.id === selectedId}
                    className={`min-h-12 rounded-lg border-2 border-[#121212] px-4 text-lg font-semibold ${
                      item.id === selectedId ? "bg-[#121212] text-white" : "bg-white"
                    }`}
                    onClick={() => setSelectedId(item.id)}
                  >
                    {item.name}
                  </button>
                ))}
              </div>
              <p className="tabular text-lg">
                {selectedId === null
                  ? "No band selected."
                  : selectedId && latest
                    ? `Latest window ${formatNumber(latest.peak_hz, 2)} Hz, ${formatNumber(latest.amp_deg, 2)}°`
                    : "No window from this band yet."}
              </p>
              <label className="flex min-h-12 items-center gap-3 text-lg font-semibold" htmlFor="pair-band">
                <input
                  id="pair-band"
                  type="checkbox"
                  className="h-6 w-6"
                  checked={pairBand}
                  onChange={(event) => setPairBand(event.target.checked)}
                />
                Pair with the selected band window
              </label>
              <button
                type="submit"
                className="min-h-12 w-full rounded-lg bg-[#0b3a82] px-4 text-xl font-bold text-white sm:w-64"
                disabled={recording}
              >
                {recording ? "Recording" : "Record run"}
              </button>
            </div>
          </form>
        </section>

        <section className="rounded-lg border-2 border-[#121212] bg-white p-4" aria-labelledby="live-error-heading">
          <h2 id="live-error-heading" className="text-2xl font-bold">
            Latest comparison
          </h2>
          <p className="tabular mt-3 text-2xl font-bold" id="live-error">
            {newest ? sentence(newest) : "No rig runs yet. Enter a setpoint and record a run."}
          </p>
        </section>

        <section className="rounded-lg border-2 border-[#121212] bg-white p-4" aria-labelledby="mae-heading">
          <h2 id="mae-heading" className="text-2xl font-bold">
            Mean absolute error
          </h2>
          <p className="tabular mt-2 text-5xl font-bold" id="mae">
            {accuracy?.mae_hz == null ? "—" : `${formatNumber(accuracy.mae_hz, 3)} Hz`}
          </p>
          <p className="mt-2 text-lg">{accuracy ? `${accuracy.n} compared run${accuracy.n === 1 ? "" : "s"}` : "Loading"}</p>
        </section>

        <section className="rounded-lg border-2 border-[#121212] bg-white p-4" aria-labelledby="table-heading">
          <h2 id="table-heading" className="text-2xl font-bold">
            Accuracy by frequency
          </h2>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full border-collapse text-left text-lg" id="accuracy-table">
              <caption className="sr-only">Mean error at each rig setpoint</caption>
              <thead>
                <tr className="border-b-2 border-[#121212]">
                  <th scope="col" className="px-2 py-3">
                    Set Hz
                  </th>
                  <th scope="col" className="px-2 py-3">
                    Runs
                  </th>
                  <th scope="col" className="px-2 py-3">
                    Mean band Hz
                  </th>
                  <th scope="col" className="px-2 py-3">
                    MAE Hz
                  </th>
                  <th scope="col" className="px-2 py-3">
                    Mean error %
                  </th>
                </tr>
              </thead>
              <tbody>
                {accuracy && accuracy.rows.length > 0 ? (
                  accuracy.rows.map((row) => (
                    <tr key={row.set_hz} className="border-b border-[#d9d3c7]">
                      <td className="tabular px-2 py-3">{formatNumber(row.set_hz, 2)}</td>
                      <td className="tabular px-2 py-3">{row.n}</td>
                      <td className="tabular px-2 py-3">{optionalHz(row.mean_band_hz)}</td>
                      <td className="tabular px-2 py-3">{formatNumber(row.mae_hz, 3)}</td>
                      <td className="tabular px-2 py-3">{formatNumber(row.mean_pct_error, 1)}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td className="px-2 py-6" colSpan={5}>
                      No rig runs yet. Enter a setpoint and record a run.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="rounded-lg border-2 border-[#121212] bg-white p-4" aria-labelledby="scatter-heading">
          <h2 id="scatter-heading" className="text-2xl font-bold">
            Measured versus setpoint
          </h2>
          <p className="mt-1 text-base">
            Horizontal axis is the setpoint. Vertical axis is the band peak when a window was paired, otherwise the rig
            measurement. The dashed line is perfect agreement.
          </p>
          {accuracy && accuracy.points.length > 0 ? (
            <div
              className="mt-2 h-80 w-full"
              role="img"
              aria-label="Scatter of measured frequency against the rig setpoint, with a dashed identity line."
            >
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={identity} margin={{ top: 16, right: 16, left: 0, bottom: 8 }}>
                  <CartesianGrid stroke="#d9d3c7" />
                  <XAxis
                    type="number"
                    dataKey="set_hz"
                    domain={[0, maxAxis]}
                    tick={{ fill: "#121212", fontSize: 14 }}
                    stroke="#121212"
                    name="Set"
                  />
                  <YAxis
                    type="number"
                    domain={[0, maxAxis]}
                    tick={{ fill: "#121212", fontSize: 14 }}
                    stroke="#121212"
                    width={48}
                    name="Measured"
                  />
                  <Tooltip formatter={(value) => [`${Number(value).toFixed(2)} Hz`, "Measured"]} />
                  <Scatter data={accuracy.points} dataKey="compared_hz" fill="#0b3a82" isAnimationActive={false} />
                  <Line
                    dataKey="compared_hz"
                    stroke="#121212"
                    strokeDasharray="6 4"
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                    legendType="none"
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="py-16 text-center text-xl">No rig runs yet. Enter a setpoint and record a run.</p>
          )}
        </section>
      </main>

      <footer className="pb-4 text-base">{DISCLAIMER}</footer>
    </div>
  );
}
