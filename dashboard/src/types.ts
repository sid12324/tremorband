export type WindowLabel = "still" | "voluntary" | "tremor";

export type SpectrumBin = {
  hz: number;
  power: number;
};

export type LiveWindow = {
  id: number;
  device_id: string;
  ts: string;
  session_id: number | null;
  test_type: string | null;
  peak_hz: number;
  band_power: number;
  rms: number;
  sharpness: number;
  amp_deg: number;
  disp_mm: number;
  log_amp: number;
  label: WindowLabel;
  p_tremor: number;
  vibrating: boolean;
  spectrum?: SpectrumBin[] | null;
  waveform?: number[] | null;
};

export type DeviceStatus = {
  id: string;
  name: string;
  last_seen: string | null;
  battery: number | null;
  rssi: number | null;
  fw_version: string | null;
  mode: string | null;
  connected: boolean;
};

export type CommandEvent = {
  id: number;
  device_id: string;
  cmd: string;
  status: "pending" | "sent" | "done";
  created_by: "user" | "agent";
  reason: string | null;
};

export const DISCLAIMER = "TremorBand is a monitoring aid, not a diagnostic device.";
