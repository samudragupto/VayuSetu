"use client";

import clsx from "clsx";

import { TIME_RANGES } from "@/lib/types";

export function TimeRangeSelector({ hours, onChange }: { hours: number; onChange: (hours: number) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-slate-300 bg-white p-0.5" role="group" aria-label="Time range">
      {TIME_RANGES.map((range) => (
        <button
          key={range.hours}
          type="button"
          onClick={() => onChange(range.hours)}
          className={clsx(
            "rounded-md px-3 py-1 text-sm font-medium transition",
            range.hours === hours ? "bg-brand-600 text-white" : "text-slate-600 hover:bg-slate-100"
          )}
          aria-pressed={range.hours === hours}
        >
          {range.label}
        </button>
      ))}
    </div>
  );
}
