import { useEffect, useRef, useState } from "react";
import HistoryChart from "../components/HistoryChart";
import SpectrumChart from "../components/SpectrumChart";
import { bandConnected, formatNumber, formatOptional, isSimulated, labelText, secondsAgo } from "../format";
import { DISCLAIMER, type CommandEvent, type DeviceStatus, type LiveWindow } from "../types";

const LABEL_CLASS: Record<LiveWindow["label"], string> = {
  tremor: "bg-[#6b1d1d] text-white",
  still: "bg-[#0c3a5e] text-white",
  voluntary: "bg-[#3f3a1e] text-white",
};

function mergeWindow(previous: LiveWindow[], next: LiveWindow): LiveWindow[] {
  if (previous.some((window) => window.id === next.id)) {
    return previous.map((window) => (window.id === next.id ? { ...window, ...next } : window));
  }
  return [...previous, next].slice(-40);
}

function upsertDevice(list: DeviceStatus[], next: DeviceStatus): DeviceStatus[] {
  const index = list.findIndex((item) => item.id === next.id);
  if (index < 0) {
    return [next, ...list];
  }
  const copy = list.slice();
  copy[index] = { ...copy[index], ...next };
  return copy;
}

export default function Live() {
  const [devices, setDevices] = useState<DeviceStatus[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selectedRef = useRef<string | null>(null);
  const requestRef = useRef(0);
  const [device, setDevice] = useState<DeviceStatus | null>(null);
  const [windows, setWindows] = useState<LiveWindow[]>([]);
  const [latest, setLatest] = useState<LiveWindow | null>(null);
  const [command, setCommand] = useState<CommandEvent | null>(null);
  const [stream, setStream] = useState<"connecting" | "live" | "reconnecting">("connecting");
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [sending, setSending] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  async function loadHistory(deviceId: string) {
    const token = ++requestRef.current;
    const response = await fetch(`/api/windows?device_id=${encodeURIComponent(deviceId)}&limit=40`);
    if (!response.ok) {
      throw new Error(`Window list failed (${response.status})`);
    }
    const history = (await response.json()) as LiveWindow[];
    if (token !== requestRef.current) {
      return;
    }
    setWindows(history);
    setLatest(history.length > 0 ? history[history.length - 1] : null);
    const latestResponse = await fetch(`/api/device/${encodeURIComponent(deviceId)}/latest`);
    if (latestResponse.ok) {
      const cached = (await latestResponse.json()) as LiveWindow | null;
      if (token === requestRef.current && cached && cached.device_id === deviceId) {
        setLatest(cached);
        setWindows((current) => mergeWindow(current, cached));
      }
    }
  }

  function chooseDevice(next: DeviceStatus) {
    selectedRef.current = next.id;
    setSelectedId(next.id);
    setDevice(next);
    setCommand(null);
    setWindows([]);
    setLatest(null);
    void loadHistory(next.id).catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "Cannot reach the backend");
    });
  }

  useEffect(() => {
    let cancelled = false;
    let source: EventSource | null = null;

    function deviceFromWindow(next: LiveWindow, current: DeviceStatus | null): DeviceStatus {
      return {
        id: next.device_id,
        name: current && current.id === next.device_id ? current.name : next.device_id,
        last_seen: next.ts,
        battery: current && current.id === next.device_id ? current.battery : null,
        rssi: current && current.id === next.device_id ? current.rssi : null,
        fw_version: current && current.id === next.device_id ? current.fw_version : null,
        mode: current && current.id === next.device_id ? current.mode : null,
        connected: true,
      };
    }

    async function start() {
      try {
        const response = await fetch("/api/devices");
        if (!response.ok) {
          throw new Error(`Device list failed (${response.status})`);
        }
        const found = (await response.json()) as DeviceStatus[];
        if (cancelled) {
          return;
        }
        setDevices(found);
        const current = found[0] ?? null;
        selectedRef.current = current?.id ?? null;
        setSelectedId(current?.id ?? null);
        setDevice(current);
        if (current) {
          await loadHistory(current.id);
        }
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Cannot reach the backend");
        }
      }

      if (cancelled) {
        return;
      }

      source = new EventSource("/api/live");
      source.onopen = () => {
        if (!cancelled) {
          setStream("live");
        }
      };
      source.onerror = () => {
        if (!cancelled) {
          setStream("reconnecting");
        }
      };
      source.addEventListener("device", (event) => {
        const next = JSON.parse((event as MessageEvent<string>).data) as DeviceStatus;
        if (cancelled) {
          return;
        }
        setDevices((current) => upsertDevice(current, next));
        if (selectedRef.current === null || selectedRef.current === next.id) {
          if (selectedRef.current === null) {
            selectedRef.current = next.id;
            setSelectedId(next.id);
          }
          setDevice(next);
        }
      });
      source.addEventListener("window", (event) => {
        const next = JSON.parse((event as MessageEvent<string>).data) as LiveWindow;
        if (cancelled) {
          return;
        }
        setDevices((current) => {
          const existing = current.find((item) => item.id === next.device_id) ?? null;
          return upsertDevice(current, deviceFromWindow(next, existing));
        });
        if (selectedRef.current && next.device_id !== selectedRef.current) {
          return;
        }
        if (!selectedRef.current) {
          selectedRef.current = next.device_id;
          setSelectedId(next.device_id);
        }
        setLatest(next);
        setWindows((current) => mergeWindow(current, next));
        setDevice((current) => deviceFromWindow(next, current));
      });
      source.addEventListener("command", (event) => {
        const next = JSON.parse((event as MessageEvent<string>).data) as CommandEvent;
        if (cancelled || (selectedRef.current && next.device_id !== selectedRef.current)) {
          return;
        }
        setCommand(next);
      });
    }

    void start();
    return () => {
      cancelled = true;
      source?.close();
    };
  }, []);

  async function sendCommand(cmd: string, reason: string) {
    if (!device) {
      return;
    }
    setSending(cmd);
    setActionError(null);
    try {
      const response = await fetch("/api/commands", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          device_id: device.id,
          cmd,
          created_by: "user",
          reason,
        }),
      });
      if (!response.ok) {
        throw new Error(`Command failed (${response.status})`);
      }
      const created = (await response.json()) as CommandEvent;
      setCommand(created);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Command failed");
    } finally {
      setSending(null);
    }
  }

  const connected = device ? bandConnected(device.last_seen, now) : false;
  const connectionText = !device ? "Waiting for band" : connected ? "Connected" : "Not connected";
  const simulated = device ? isSimulated(device.id, device.fw_version) : false;

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h1 className="text-4xl font-bold tracking-tight">TremorBand</h1>
          <p className="text-lg">Live</p>
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

        <section className="rounded-lg border-2 border-[#121212] bg-white p-4" aria-labelledby="status-heading">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 id="status-heading" className="text-2xl font-bold">
              Band
            </h2>
            <div className="flex flex-wrap gap-2">
              {simulated ? (
                <span className="rounded-full border-2 border-[#121212] px-3 py-1 text-base font-semibold">
                  Simulated data
                </span>
              ) : null}
              <span className="text-base">Event stream: {stream}</span>
            </div>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatusCell label="Connection" value={connectionText} detail={device ? secondsAgo(device.last_seen, now) : "Waiting for a band"} />
            <StatusCell label="Battery" value={formatOptional(device?.battery ?? null, 0, "%")} detail={device?.name ?? "—"} />
            <StatusCell label="RSSI" value={formatOptional(device?.rssi ?? null, 0, " dBm")} detail={device?.fw_version ?? "—"} />
            <StatusCell label="Mode" value={device?.mode ?? "—"} detail={device?.id ?? "No device id"} />
          </div>
          {devices.length > 0 ? (
            <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label="Bands">
              {devices.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={item.id === selectedId}
                  className={`min-h-12 rounded-lg border-2 border-[#121212] px-4 text-lg font-semibold ${
                    item.id === selectedId ? "bg-[#121212] text-white" : "bg-white"
                  }`}
                  onClick={() => chooseDevice(item)}
                >
                  {item.name}
                </button>
              ))}
            </div>
          ) : null}
        </section>

        <section className="grid grid-cols-1 gap-3 lg:grid-cols-4" aria-label="Latest window">
          <Readout label="Peak" value={latest ? `${formatNumber(latest.peak_hz, 2)} Hz` : "—"} />
          <Readout
            label="Amplitude"
            value={latest ? `${formatNumber(latest.amp_deg, 2)}°` : "—"}
            detail={latest ? `${formatNumber(latest.disp_mm, 2)} mm` : "Waiting for a window"}
          />
          <div className="rounded-lg border-2 border-[#121212] bg-white p-4">
            <p className="text-base font-semibold">Label</p>
            {latest ? (
              <p className={`mt-3 inline-flex min-h-12 items-center rounded-lg px-4 text-3xl font-bold ${LABEL_CLASS[latest.label]}`}>
                {labelText(latest.label)}
              </p>
            ) : (
              <p className="mt-3 text-3xl font-bold">—</p>
            )}
            <p className="mt-3 text-base">{latest?.vibrating ? "Vibrating flag is set" : "Not vibrating"}</p>
          </div>
          <div className="rounded-lg border-2 border-[#121212] bg-white p-4">
            <p className="text-base font-semibold">p_tremor</p>
            <p className="tabular mt-2 text-5xl font-bold">{latest ? formatNumber(latest.p_tremor, 2) : "—"}</p>
            <div
              className="mt-3 h-12 w-full overflow-hidden rounded-lg border-2 border-[#121212] bg-[#f7f4ee]"
              role="meter"
              aria-label="Classifier score for this window"
              aria-valuemin={0}
              aria-valuemax={1}
              aria-valuenow={latest?.p_tremor ?? 0}
            >
              <div
                className="h-full bg-[#0b3a82]"
                style={{ width: `${Math.round((latest?.p_tremor ?? 0) * 100)}%` }}
              />
            </div>
            <p className="mt-2 text-base">Classifier score for this window.</p>
          </div>
        </section>

        <section className="rounded-lg border-2 border-[#121212] bg-white p-4">
          <h2 className="text-2xl font-bold">Spectrum</h2>
          <p className="mt-1 text-base">Shaded region is 3–12 Hz. The line marks the posted peak.</p>
          {latest?.spectrum && latest.spectrum.length > 0 ? (
            <SpectrumChart spectrum={latest.spectrum} peakHz={latest.peak_hz} />
          ) : (
            <p className="py-16 text-center text-xl">This window has no spectrum.</p>
          )}
        </section>

        <section className="rounded-lg border-2 border-[#121212] bg-white p-4">
          <h2 className="text-2xl font-bold">Recent peak frequency</h2>
          <p className="mt-1 text-base">{windows.length} window{windows.length === 1 ? "" : "s"} on this page.</p>
          {windows.length > 0 ? (
            <HistoryChart windows={windows} />
          ) : (
            <p className="py-16 text-center text-xl">Waiting for windows.</p>
          )}
        </section>

        <section className="rounded-lg border-2 border-[#121212] bg-white p-4">
          <h2 className="text-2xl font-bold">Waveform</h2>
          <p className="mt-2 text-lg">Raw stream is off. The band posts window features, not the 104 Hz waveform.</p>
        </section>

        <section className="rounded-lg border-2 border-[#121212] bg-white p-4" aria-labelledby="actions-heading">
          <h2 id="actions-heading" className="text-2xl font-bold">
            Band actions
          </h2>
          <p className="mt-1 text-base">Commands are queued for the band. The simulator picks them up about every 2 seconds.</p>
          <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <button
              type="button"
              className="min-h-14 rounded-lg bg-[#121212] px-6 text-xl font-semibold text-white disabled:opacity-40"
              disabled={!device || sending !== null}
              onClick={() => void sendCommand("identify", "Identify from the Live page")}
            >
              {sending === "identify" ? "Sending…" : "Identify band"}
            </button>
            <button
              type="button"
              className="min-h-14 rounded-lg bg-[#121212] px-6 text-xl font-semibold text-white disabled:opacity-40"
              disabled={!device || sending !== null}
              onClick={() => void sendCommand("vibrate:ALERT", "Buzz from the Live page")}
            >
              {sending === "vibrate:ALERT" ? "Sending…" : "Buzz"}
            </button>
          </div>
          <p className="mt-4 text-lg">
            Last command:{" "}
            {command ? (
              <span className="font-semibold">
                {command.cmd} · {command.status}
              </span>
            ) : (
              "none yet"
            )}
          </p>
          {actionError ? (
            <p className="mt-2 text-lg" role="alert">
              {actionError}
            </p>
          ) : null}
        </section>

        <section className="rounded-lg border-2 border-[#121212] bg-white p-4" aria-labelledby="latest-heading">
          <h2 id="latest-heading" className="text-2xl font-bold">
            Latest windows
          </h2>
          {windows.length === 0 ? (
            <p className="mt-3 text-lg">Waiting for windows.</p>
          ) : (
            <ol className="mt-3 flex flex-col gap-2">
              {windows.slice(-5).reverse().map((window) => (
                <li key={window.id} className="tabular text-lg">
                  {new Date(window.ts).toLocaleTimeString()} · {formatNumber(window.peak_hz, 2)} Hz ·{" "}
                  {formatNumber(window.amp_deg, 2)}° · {formatNumber(window.disp_mm, 2)} mm · {labelText(window.label)}
                </li>
              ))}
            </ol>
          )}
        </section>
      </main>

      <footer className="pb-4 text-base">{DISCLAIMER}</footer>
    </div>
  );
}

function StatusCell({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="min-h-24 rounded-lg bg-[#f7f4ee] px-4 py-3">
      <p className="text-base font-semibold">{label}</p>
      <p className="tabular mt-1 text-3xl font-bold">{value}</p>
      <p className="mt-1 text-base">{detail}</p>
    </div>
  );
}

function Readout({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="rounded-lg border-2 border-[#121212] bg-white p-4">
      <p className="text-base font-semibold">{label}</p>
      <p className="tabular mt-2 text-5xl font-bold">{value}</p>
      {detail ? <p className="mt-2 text-lg">{detail}</p> : null}
    </div>
  );
}
