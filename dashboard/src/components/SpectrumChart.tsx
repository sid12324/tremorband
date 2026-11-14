import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { SpectrumBin } from "../types";

type SpectrumChartProps = {
  spectrum: SpectrumBin[];
  peakHz: number;
};

export default function SpectrumChart({ spectrum, peakHz }: SpectrumChartProps) {
  const data = [...spectrum].sort((a, b) => a.hz - b.hz);
  const showPeak = peakHz >= 0 && peakHz <= 15;

  return (
    <div
      className="h-72 w-full"
      role="img"
      aria-label={`Spectrum for the latest window. Posted peak ${peakHz.toFixed(2)} hertz. The 3 to 12 hertz band is shaded.`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 28, right: 16, left: 0, bottom: 8 }}>
          <CartesianGrid stroke="#d9d3c7" />
          <XAxis
            dataKey="hz"
            type="number"
            domain={[0, 15]}
            ticks={[0, 3, 6, 9, 12, 15]}
            tick={{ fill: "#121212", fontSize: 14 }}
            stroke="#121212"
            unit=" Hz"
          />
          <YAxis
            domain={[0, "auto"]}
            tick={{ fill: "#121212", fontSize: 14 }}
            stroke="#121212"
            width={48}
          />
          <Tooltip
            formatter={(value) => [typeof value === "number" ? value.toFixed(3) : value, "Power"]}
            labelFormatter={(label) => `${Number(label).toFixed(2)} Hz`}
          />
          <ReferenceArea x1={3} x2={12} fill="#e2b657" fillOpacity={0.45} />
          {showPeak ? (
            <ReferenceLine
              x={peakHz}
              stroke="#6b1d1d"
              strokeWidth={2}
              label={{
                value: `${peakHz.toFixed(2)} Hz`,
                position: "insideTopRight",
                fill: "#121212",
                fontSize: 16,
              }}
            />
          ) : null}
          <Area
            type="monotone"
            dataKey="power"
            stroke="#0b3a82"
            strokeWidth={2}
            fill="#0b3a82"
            fillOpacity={0.2}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
