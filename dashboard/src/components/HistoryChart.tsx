import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { clockTime } from "../format";
import type { LiveWindow } from "../types";

type HistoryChartProps = {
  windows: LiveWindow[];
};

export default function HistoryChart({ windows }: HistoryChartProps) {
  const data = windows.map((window) => ({
    t: clockTime(window.ts),
    peak_hz: window.peak_hz,
  }));
  const tickInterval = data.length > 6 ? Math.ceil(data.length / 6) : 0;

  return (
    <div className="h-64 w-full" role="img" aria-label="Recent posted peak frequency.">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 16, right: 16, left: 0, bottom: 8 }}>
          <CartesianGrid stroke="#d9d3c7" />
          <XAxis
            dataKey="t"
            tick={{ fill: "#121212", fontSize: 14 }}
            stroke="#121212"
            interval={tickInterval}
            minTickGap={16}
          />
          <YAxis
            domain={[0, 15]}
            tick={{ fill: "#121212", fontSize: 14 }}
            stroke="#121212"
            width={40}
            unit=""
          />
          <Tooltip formatter={(value) => [`${Number(value).toFixed(2)} Hz`, "Peak"]} />
          <Line
            type="monotone"
            dataKey="peak_hz"
            stroke="#0b3a82"
            strokeWidth={3}
            dot={{ r: 3, fill: "#0b3a82" }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
