import clsx from "clsx";
import type { ReactNode } from "react";

export function StatCard({ label, value, hint, accent, children }: { label: string; value: ReactNode; hint?: string; accent?: string; children?: ReactNode }) {
  return (
    <div className="card px-5 py-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      <p className={clsx("mt-1 text-2xl font-semibold", accent ?? "text-slate-900")}>{value}</p>
      {hint ? <p className="mt-1 text-xs text-slate-500">{hint}</p> : null}
      {children}
    </div>
  );
}
