"use client";

import clsx from "clsx";

import { TIME_RANGES } from "@/lib/types";

export function TimeRangeSelector({ hours, onChange }: { hours: number; onChange: (hours: number) => void }) {
  return (
    <div className="flex items-center gap-2" role="group" aria-label="Time range">
      <span className="hidden text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500 sm:inline">Window</span>
      <div className="inline-flex rounded-xl border border-slate-200 bg-white p-1 shadow-sm">
        {TIME_RANGES.map((range) => (
          <button
            key={range.hours}
            type="button"
            onClick={() => onChange(range.hours)}
            className={clsx(
              "rounded-lg px-3 py-1.5 text-xs font-semibold transition",
              range.hours === hours ? "bg-brand-600 text-white shadow-sm" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
            )}
            aria-pressed={range.hours === hours}
          >
            {range.label}
          </button>
        ))}
      </div>
    </div>
  );
}
