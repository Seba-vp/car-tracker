"use client";

import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";

export type YearPoint = { year: number; median: number; n: number };

export function DepreciationChart({ data }: { data: YearPoint[] }) {
  if (data.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-neutral-500">
        Not enough data
      </div>
    );
  }
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <CartesianGrid stroke="#1f1f24" />
          <XAxis
            dataKey="year"
            stroke="#737373"
            fontSize={11}
            tickFormatter={(v) => String(v)}
          />
          <YAxis
            tickFormatter={(v) => `${Math.round(v / 1_000_000)}M`}
            stroke="#737373"
            fontSize={11}
            width={48}
          />
          <Tooltip
            contentStyle={{
              background: "#0a0a0b",
              border: "1px solid #27272a",
              fontSize: 12,
            }}
            labelFormatter={(v) => `Year ${v}`}
            formatter={(value: number, name: string) => {
              if (name === "median") {
                return [
                  new Intl.NumberFormat("es-CL", {
                    style: "currency",
                    currency: "CLP",
                    maximumFractionDigits: 0,
                  }).format(value),
                  "Median price",
                ];
              }
              return [value, name];
            }}
          />
          <Line
            type="monotone"
            dataKey="median"
            stroke="#34d399"
            strokeWidth={2}
            dot={{ r: 3, fill: "#34d399" }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
