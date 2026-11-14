import type { WindowLabel } from "./types";

export function formatNumber(value: number, digits: number): string {
  return value.toFixed(digits);
}

export function formatOptional(value: number | null, digits: number, suffix = ""): string {
  if (value === null || Number.isNaN(value)) {
    return "—";
  }
  return `${value.toFixed(digits)}${suffix}`;
}

export function secondsAgo(iso: string | null, now: number): string {
  if (!iso) {
    return "no contact yet";
  }
  const delta = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (delta < 2) {
    return "just now";
  }
  return `${delta}s ago`;
}

export function bandConnected(lastSeen: string | null, now: number): boolean {
  if (!lastSeen) {
    return false;
  }
  return now - new Date(lastSeen).getTime() <= 20_000;
}

export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function labelText(label: WindowLabel): string {
  if (label === "voluntary") {
    return "Voluntary";
  }
  if (label === "tremor") {
    return "Tremor";
  }
  return "Still";
}

export function isSimulated(deviceId: string, firmware: string | null): boolean {
  return deviceId.startsWith("sim") || (firmware ?? "").includes("sim");
}
