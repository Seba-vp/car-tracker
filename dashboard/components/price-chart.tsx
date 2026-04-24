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
import { format } from "date-fns";

export type PricePoint = { observed_at: string; price_clp: number };

export function PriceChart({ data }: { data: PricePoint[] }) {
  const pts = data.map((p) => ({
    t: new Date(p.observed_at).getTime(),
    price: p.price_clp,
  }));

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={pts}>
          <CartesianGrid stroke="#1f1f24" />
          <XAxis
            dataKey="t"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(t) => format(new Date(t), "MMM d")}
            stroke="#737373"
            fontSize={11}
          />
          <YAxis
            dataKey="price"
            tickFormatter={(v) => `${Math.round(v / 1_000_000)}M`}
            stroke="#737373"
            fontSize={11}
            width={50}
          />
          <Tooltip
            contentStyle={{
              background: "#0a0a0b",
              border: "1px solid #27272a",
              fontSize: 12,
            }}
            labelFormatter={(t) => format(new Date(t), "PPP")}
            formatter={(v: number) =>
              new Intl.NumberFormat("es-CL", {
                style: "currency",
                currency: "CLP",
                maximumFractionDigits: 0,
              }).format(v)
            }
          />
          <Line
            type="stepAfter"
            dataKey="price"
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
