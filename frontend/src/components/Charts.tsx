"use client";

import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { CategoryCount, SourceCount, TrendPoint } from "@/lib/analytics";

import { EmptyState } from "./States";

export function AqiTrendChart({ data, threshold }: { data: TrendPoint[]; threshold: number }) {
  if (data.length === 0) {
    return <EmptyState title="No analysed reports in this window" description="The trend appears once Gemini has analysed citizen images." />;
  }
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 10, right: 20, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} minTickGap={24} />
          <YAxis domain={[0, 500]} tick={{ fontSize: 11 }} width={36} />
          <Tooltip
            formatter={(value, name) => [value === null || value === undefined ? "n/a" : String(value), String(name)]}
            labelFormatter={(label) => `IST ${label}`}
            contentStyle={{ fontSize: 12 }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <ReferenceLine y={threshold} stroke="#cc0033" strokeDasharray="4 4" label={{ value: `Alert ${threshold}`, fontSize: 11, fill: "#cc0033", position: "insideTopRight" }} />
          <Line type="monotone" dataKey="observedAqi" name="Observed AQI (citizen + Gemini)" stroke="#1d5bd6" strokeWidth={2} dot={false} connectNulls />
          <Line type="monotone" dataKey="predictedAqi" name="Predicted AQI (12 h XGBoost)" stroke="#ff9933" strokeWidth={2} strokeDasharray="6 3" dot={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SourceBreakdownChart({ data }: { data: SourceCount[] }) {
  if (data.length === 0) {
    return <EmptyState title="No pollution sources identified yet" />;
  }
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
          <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
          <YAxis type="category" dataKey="label" width={130} tick={{ fontSize: 11 }} />
          <Tooltip contentStyle={{ fontSize: 12 }} />
          <Bar dataKey="count" name="Reports" fill="#1d5bd6" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function CategoryDistributionChart({ data }: { data: CategoryCount[] }) {
  const total = data.reduce((sum, item) => sum + item.count, 0);
  if (total === 0) {
    return <EmptyState title="No analysed reports yet" />;
  }
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} interval={0} />
          <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={36} />
          <Tooltip contentStyle={{ fontSize: 12 }} />
          <Bar dataKey="count" name="Reports" radius={[4, 4, 0, 0]}>
            {data.map((entry) => (
              <Cell key={entry.category} fill={entry.color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
