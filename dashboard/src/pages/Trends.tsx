import { useCallback, useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { DISCLAIMER } from "../types";

type SessionMetric = {
  id: number;
  test_type: string;
  ts_start: string;
  log_amp: number | null;
  z: number | null;
  above_threshold: boolean;
  hours_since_dose: number | null;
  is_synthetic: boolean;
};

type Baseline = {
  test_type: string;
  mean_log_amp: number;
  sd_log_amp: number;
  threshold_z: number;
  n_sessions: number;
};

type Dose = { id: number; ts: string; name: string };
type Symptom = { id: number; ts: string; rating: number; tags: string[]; note: string | null };
type WearingOff = { confidence: string; finding: string; n_early: number; n_late: number };
type TagRow = {
  tag: string;
  n_tagged: number;
  n_untagged: number;
  median_difference: number | null;
  finding: string;
};
type Quality = {
  n_windows: number;
  excluded_vibration: number;
  excluded_missing: number;
  excluded_low_quality: number;
  n_used: number;
};
type TremorDay = { day: string; tremor_hours: number };
type FeedbackChange = { reason: string; new_threshold_z: number };

const TESTS = ["rest", "postural", "finger-to-nose", "tapping", "gait"];

function shortWhen(iso: string): string {
  return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function dayLabel(ms: number): string {
  return new Date(ms).toLocaleDateString([], { month: "short", day: "numeric" });
}

async function readJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path} failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export default function Trends() {
  const [testType, setTestType] = useState("rest");
  const [metrics, setMetrics] = useState<SessionMetric[]>([]);
  const [baselines, setBaselines] = useState<Baseline[]>([]);
  const [doses, setDoses] = useState<Dose[]>([]);
  const [symptoms, setSymptoms] = useState<Symptom[]>([]);
  const [wearing, setWearing] = useState<WearingOff | null>(null);
  const [tags, setTags] = useState<TagRow[]>([]);
  const [quality, setQuality] = useState<Quality | null>(null);
  const [tremorHours, setTremorHours] = useState<TremorDay[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const load = useCallback(async () => {
    const [nextMetrics, nextBaselines, nextDoses, nextSymptoms, nextWearing, nextTags, nextQuality, nextHours] =
      await Promise.all([
        readJson<SessionMetric[]>("/api/metrics?days=14"),
        readJson<Baseline[]>("/api/baseline"),
        readJson<Dose[]>("/api/medications?days=14"),
        readJson<Symptom[]>("/api/symptoms?days=14"),
        readJson<WearingOff>("/api/analytics/wearing-off?days=14"),
        readJson<TagRow[]>("/api/analytics/tags?days=14"),
        readJson<Quality>("/api/analytics/quality?days=14"),
        readJson<TremorDay[]>("/api/analytics/tremor-hours?days=14"),
      ]);
    setMetrics(nextMetrics);
    setBaselines(nextBaselines);
    setDoses(nextDoses);
    setSymptoms(nextSymptoms);
    setWearing(nextWearing);
    setTags(nextTags);
    setQuality(nextQuality);
    setTremorHours(nextHours);
  }, []);

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "Cannot reach the backend");
    });
  }, [load]);

  const chosen = testType === "all" ? metrics : metrics.filter((row) => row.test_type === testType);
  const baseline = baselines.find((row) => row.test_type === testType) ?? null;
  const series = chosen
    .filter((row) => row.log_amp !== null)
    .map((row) => ({
      t: new Date(row.ts_start).getTime(),
      log_amp: row.log_amp as number,
      above: row.above_threshold,
      band_low: baseline ? baseline.mean_log_amp - baseline.threshold_z * baseline.sd_log_amp : null,
      band_high: baseline ? baseline.mean_log_amp + baseline.threshold_z * baseline.sd_log_amp : null,
    }));
  const symptomY =
    baseline?.mean_log_amp ??
    (series.length > 0 ? series.reduce((sum, row) => sum + row.log_amp, 0) / series.length : 0);
  const symptomMarks = symptoms.map((row) => ({
    t: new Date(row.ts).getTime(),
    y: symptomY,
    label: row.tags.join(", ") || "symptom log",
  }));
  const span = [
    ...series.map((row) => row.t),
    ...doses.map((row) => new Date(row.ts).getTime()),
    ...symptomMarks.map((row) => row.t),
  ];
  const xMin = span.length > 0 ? Math.min(...span) : 0;
  const xMax = span.length > 0 ? Math.max(...span) : 1;
  const hourPoints = chosen
    .filter((row) => row.log_amp !== null && row.hours_since_dose !== null)
    .map((row) => ({
      hours: row.hours_since_dose as number,
      log_amp: row.log_amp as number,
    }));
  const latest = chosen.length > 0 ? chosen[chosen.length - 1] : null;
  const synthetic = metrics.some((row) => row.is_synthetic);
  const knownTests = TESTS.filter((name, index, all) => all.indexOf(name) === index);
  const extraTests = [...new Set(metrics.map((row) => row.test_type))].filter((name) => !knownTests.includes(name));

  async function sendFeedback(kind: "not_a_bad_day" | "missed_symptoms") {
    if (!latest) {
      return;
    }
    setSending(true);
    setNotice(null);
    try {
      const response = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, session_id: latest.id }),
      });
      if (!response.ok) {
        throw new Error(`Feedback failed (${response.status})`);
      }
      const body = (await response.json()) as { changes: FeedbackChange[] };
      const change = body.changes[0];
      setNotice(change ? change.reason : "Feedback saved.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Feedback failed");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h1 className="text-4xl font-bold tracking-tight">TremorBand</h1>
          <p className="text-lg">Trends</p>
        </div>
        <p className="rounded-lg bg-[#121212] px-4 py-3 text-lg font-semibold text-white" role="note">
          {DISCLAIMER}
        </p>
      </header>

      <main className="flex flex-col gap-6">
        {error ? (
          <p className="rounded-lg border-2 border-[#6b1d1d] bg-white px-4 py-3" role="alert">
            Cannot reach the backend. {error}
          </p>
        ) : null}
        {synthetic ? (
          <p className="rounded-lg border-2 border-[#121212] bg-white px-4 py-3 text-lg font-semibold" role="status">
            Synthetic data
          </p>
        ) : null}

        <section className="flex flex-col gap-3" aria-label="Test type">
          <h2 className="text-2xl font-bold">Log amplitude</h2>
          <div className="flex flex-wrap gap-2">
            {["all", ...knownTests, ...extraTests].map((name) => (
              <button
                key={name}
                type="button"
                className={`min-h-12 rounded-lg border-2 border-[#121212] px-4 text-lg font-semibold ${
                  testType === name ? "bg-[#121212] text-white" : "bg-white text-[#121212]"
                }`}
                aria-pressed={testType === name}
                onClick={() => setTestType(name)}
              >
                {name}
              </button>
            ))}
          </div>
          {baseline ? (
            <p className="tabular text-lg">
              Baseline mean {baseline.mean_log_amp.toFixed(2)}, SD {baseline.sd_log_amp.toFixed(2)}, comparison line{" "}
              {baseline.threshold_z.toFixed(2)} from {baseline.n_sessions} sessions.
            </p>
          ) : (
            <p className="text-lg">Choose one test to see its baseline band.</p>
          )}
          {series.length === 0 ? (
            <p className="text-lg">No sessions in this window.</p>
          ) : (
            <div className="h-72 w-full" role="img" aria-label="Log amplitude against the personal baseline band.">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={series} margin={{ top: 16, right: 16, left: 0, bottom: 8 }}>
                  <CartesianGrid stroke="#d9d3c7" />
                  <XAxis
                    dataKey="t"
                    type="number"
                    domain={[xMin, xMax]}
                    tickFormatter={dayLabel}
                    tick={{ fill: "#121212", fontSize: 14 }}
                    stroke="#121212"
                  />
                  <YAxis tick={{ fill: "#121212", fontSize: 14 }} stroke="#121212" width={48} />
                  <Tooltip
                    labelFormatter={(value) => shortWhen(new Date(Number(value)).toISOString())}
                    formatter={(value, name) => [Number(value).toFixed(2), String(name)]}
                  />
                  {doses.map((dose) => (
                    <ReferenceLine key={dose.id} x={new Date(dose.ts).getTime()} stroke="#6b1d1d" strokeDasharray="4 4" />
                  ))}
                  <Line
                    type="monotone"
                    dataKey="band_low"
                    stroke="#5c5346"
                    strokeDasharray="6 4"
                    dot={false}
                    isAnimationActive={false}
                    name="band low"
                  />
                  <Line
                    type="monotone"
                    dataKey="band_high"
                    stroke="#5c5346"
                    strokeDasharray="6 4"
                    dot={false}
                    isAnimationActive={false}
                    name="band high"
                  />
                  <Line
                    type="monotone"
                    dataKey="log_amp"
                    stroke="#0b3a82"
                    strokeWidth={3}
                    isAnimationActive={false}
                    name="log amplitude"
                    dot={(props) => {
                      const { cx, cy, payload } = props as { cx?: number; cy?: number; payload?: { above?: boolean } };
                      if (cx == null || cy == null) {
                        return <g />;
                      }
                      return <circle cx={cx} cy={cy} r={4} fill={payload?.above ? "#6b1d1d" : "#0b3a82"} />;
                    }}
                  />
                  <Scatter data={symptomMarks} dataKey="y" fill="#3f3a1e" name="symptom log" />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
          <p className="text-lg">Dashed lines mark logged doses. Dark dots mark symptom-log entries. The gray band is mean ± comparison line × SD.</p>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-2xl font-bold">Hours after a logged dose</h2>
          {hourPoints.length === 0 ? (
            <p className="text-lg">No sessions have a logged dose before them.</p>
          ) : (
            <div className="h-64 w-full" role="img" aria-label="Log amplitude by hours since the last logged dose.">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={hourPoints} margin={{ top: 16, right: 16, left: 0, bottom: 8 }}>
                  <CartesianGrid stroke="#d9d3c7" />
                  <XAxis
                    dataKey="hours"
                    type="number"
                    tick={{ fill: "#121212", fontSize: 14 }}
                    stroke="#121212"
                    name="Hours"
                  />
                  <YAxis dataKey="log_amp" tick={{ fill: "#121212", fontSize: 14 }} stroke="#121212" width={48} />
                  <Tooltip formatter={(value) => Number(value).toFixed(2)} />
                  <Scatter dataKey="log_amp" fill="#0b3a82" name="log amplitude" />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
          <p className="text-lg">Each point is a recorded session. This chart does not suggest a dose.</p>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-2xl font-bold">Tremor hours per day</h2>
          {tremorHours.length === 0 ? (
            <p className="text-lg">No passive summaries in this window.</p>
          ) : (
            <div className="h-64 w-full" role="img" aria-label="Tremor hours per day from passive summaries.">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={tremorHours} margin={{ top: 16, right: 16, left: 0, bottom: 8 }}>
                  <CartesianGrid stroke="#d9d3c7" />
                  <XAxis dataKey="day" tick={{ fill: "#121212", fontSize: 14 }} stroke="#121212" />
                  <YAxis tick={{ fill: "#121212", fontSize: 14 }} stroke="#121212" width={48} />
                  <Tooltip formatter={(value) => [`${Number(value).toFixed(2)} h`, "Tremor hours"]} />
                  <Bar dataKey="tremor_hours" fill="#0b3a82" isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          <p className="text-lg">Each summary counts for the time until the next one, up to one hour, times its tremor percent.</p>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-2xl font-bold">Timing of logged doses</h2>
          {wearing ? (
            <>
              <p className="text-lg">{wearing.finding}</p>
              <p className="tabular text-lg">
                Confidence: {wearing.confidence}. Sessions in the first 2 hours: {wearing.n_early}. Sessions from 3 to
                5 hours: {wearing.n_late}.
              </p>
            </>
          ) : (
            <p className="text-lg">Timing comparison is loading.</p>
          )}
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-2xl font-bold">Symptom tags</h2>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-lg">
              <thead>
                <tr>
                  <th className="border-b-2 border-[#121212] px-2 py-3">Tag</th>
                  <th className="border-b-2 border-[#121212] px-2 py-3">Near tag</th>
                  <th className="border-b-2 border-[#121212] px-2 py-3">Other</th>
                  <th className="border-b-2 border-[#121212] px-2 py-3">Median difference</th>
                </tr>
              </thead>
              <tbody>
                {tags.map((row) => (
                  <tr key={row.tag}>
                    <th className="px-2 py-3 font-semibold" scope="row">
                      {row.tag}
                    </th>
                    <td className="tabular px-2 py-3">{row.n_tagged}</td>
                    <td className="tabular px-2 py-3">{row.n_untagged}</td>
                    <td className="tabular px-2 py-3">
                      {row.median_difference === null ? "—" : row.median_difference.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {tags.map((row) => (
            <p key={`${row.tag}-finding`} className="text-lg">
              {row.finding}
            </p>
          ))}
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-2xl font-bold">Data quality</h2>
          {quality ? (
            <dl className="grid gap-2 text-lg sm:grid-cols-2">
              <div>
                <dt className="font-semibold">Windows used</dt>
                <dd className="tabular">
                  {quality.n_used} of {quality.n_windows}
                </dd>
              </div>
              <div>
                <dt className="font-semibold">Left out while the motor was on</dt>
                <dd className="tabular">{quality.excluded_vibration}</dd>
              </div>
              <div>
                <dt className="font-semibold">Left out for missing fields</dt>
                <dd className="tabular">{quality.excluded_missing}</dd>
              </div>
              <div>
                <dt className="font-semibold">Left out for an empty signal</dt>
                <dd className="tabular">{quality.excluded_low_quality}</dd>
              </div>
            </dl>
          ) : (
            <p className="text-lg">Quality counts are loading.</p>
          )}
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-2xl font-bold">Comparison line</h2>
          <p className="text-lg">Moves the comparison line for {testType === "all" ? "the latest session's test" : testType}. It does not interpret the session.</p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="min-h-12 rounded-lg bg-[#0b3a82] px-4 text-lg font-bold text-white disabled:opacity-50"
              disabled={!latest || sending}
              onClick={() => void sendFeedback("not_a_bad_day")}
            >
              Not a bad day
            </button>
            <button
              type="button"
              className="min-h-12 rounded-lg border-2 border-[#121212] bg-white px-4 text-lg font-bold disabled:opacity-50"
              disabled={!latest || sending}
              onClick={() => void sendFeedback("missed_symptoms")}
            >
              Missed symptoms
            </button>
          </div>
          {notice ? (
            <p className="text-lg" role="status">
              {notice}
            </p>
          ) : null}
        </section>
      </main>

      <footer className="pb-4 text-base">{DISCLAIMER}</footer>
    </div>
  );
}
