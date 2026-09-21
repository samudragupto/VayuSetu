"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useAuth } from "@/hooks/useAuth";

const NAV_ITEMS = [
  { href: "/", label: "Overview" },
  { href: "/reports/", label: "Citizen reports" },
  { href: "/alerts/", label: "Alerts" },
];

function normalise(path: string): string {
  return path === "/" ? "/" : path.replace(/\/+$/, "") + "/";
}

export function AppShell({ children, title, actions }: { children: ReactNode; title: string; actions?: ReactNode }) {
  const pathname = usePathname();
  const { user, signOut } = useAuth();
  const current = normalise(pathname ?? "/");

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6">
          <div className="flex items-center gap-8">
            <Link href="/" className="flex items-center gap-2">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 text-sm font-bold text-white">VS</span>
              <span>
                <span className="block text-base font-semibold leading-tight text-slate-900">VayuSetu</span>
                <span className="block text-xs text-slate-500">Authority dashboard</span>
              </span>
            </Link>
            <nav className="hidden items-center gap-1 sm:flex" aria-label="Primary">
              {NAV_ITEMS.map((item) => {
                const active = normalise(item.href) === current;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={clsx(
                      "rounded-md px-3 py-1.5 text-sm font-medium transition",
                      active ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                    )}
                    aria-current={active ? "page" : undefined}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            {user ? (
              <>
                <span className="hidden text-sm text-slate-600 md:inline">{user.email}</span>
                <button type="button" className="btn-secondary" onClick={() => void signOut()}>
                  Sign out
                </button>
              </>
            ) : null}
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto border-t border-slate-100 px-4 py-2 sm:hidden" aria-label="Primary mobile">
          {NAV_ITEMS.map((item) => (
            <Link key={item.href} href={item.href} className={clsx("rounded-md px-3 py-1 text-sm", normalise(item.href) === current ? "bg-brand-50 text-brand-700" : "text-slate-600")}>
              {item.label}
            </Link>
          ))}
        </nav>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
          {actions}
        </div>
        {children}
      </main>
      <footer className="border-t border-slate-200 bg-white py-3 text-center text-xs text-slate-500">
        VayuSetu combines citizen WhatsApp reports, Gemini vision analysis, Sentinel-5P satellite data and XGBoost forecasts. Data refreshes in real time.
      </footer>
    </div>
  );
}
