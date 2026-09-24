import clsx from "clsx";
import type { ReactNode } from "react";

export function StatCard({ label, value, hint, accent, children }: { label: string; value: ReactNode; hint?: string; accent?: string; children?: ReactNode }) {
  return (
    <div className="card relative overflow-hidden px-5 py-4">
      <div className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-brand-500 via-cyan-400 to-transparent" aria-hidden="true" />
      <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">{label}</p>
      <p className={clsx("mt-2 text-2xl font-semibold tracking-[-0.03em]", accent ?? "text-slate-950")}>{value}</p>
      {hint ? <p className="mt-1.5 text-xs leading-5 text-slate-500">{hint}</p> : null}
      {children}
    </div>
  );
}
