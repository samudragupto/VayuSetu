"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useAuth } from "@/hooks/useAuth";

const NAV_ITEMS = [
  { href: "/", label: "Overview", shortLabel: "Home" },
  { href: "/reports/", label: "Citizen reports", shortLabel: "Reports" },
  { href: "/alerts/", label: "Alert dispatch", shortLabel: "Alerts" },
];

function normalise(path: string): string {
  return path === "/" ? "/" : path.replace(/\/+$/, "") + "/";
}

function initials(email: string | null | undefined): string {
  const first = email?.trim().charAt(0).toUpperCase();
  return first || "A";
}

export function AppShell({ children, title, actions }: { children: ReactNode; title: string; actions?: ReactNode }) {
  const pathname = usePathname();
  const { user, signOut } = useAuth();
  const current = normalise(pathname ?? "/");

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-slate-200/90 bg-white/95 shadow-[0_2px_16px_rgba(15,23,42,0.04)] backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3.5 sm:px-6">
          <div className="flex items-center gap-8">
            <Link href="/" className="group flex items-center gap-2.5" aria-label="VayuSetu overview">
              <span className="brand-mark bg-brand-600 text-white shadow-[0_5px_12px_rgba(22,74,178,0.22)]" aria-hidden="true">
                <span />
                <span />
                <span />
              </span>
              <span>
                <span className="block text-[15px] font-bold leading-tight tracking-[-0.02em] text-slate-900">VayuSetu</span>
                <span className="block text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">Control room</span>
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
                      "rounded-lg px-3 py-2 text-sm font-medium transition",
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
          <div className="flex items-center gap-2.5">
            <span className="hidden items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-800 md:flex">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_0_3px_rgba(16,185,129,0.12)]" aria-hidden="true" />
              Live feed
            </span>
            {user ? (
              <>
                <div className="flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 py-1 pl-1 pr-2.5" title={user.email ?? undefined}>
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-100 text-xs font-bold text-brand-700">{initials(user.email)}</span>
                  <span className="hidden max-w-[180px] truncate text-xs font-medium text-slate-700 lg:inline">{user.email}</span>
                </div>
                <button type="button" className="btn-secondary px-2.5 py-1.5 text-xs" onClick={() => void signOut()}>
                  Sign out
                </button>
              </>
            ) : null}
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto border-t border-slate-100 px-4 py-2 sm:hidden" aria-label="Primary mobile">
          {NAV_ITEMS.map((item) => {
            const active = normalise(item.href) === current;
            return (
              <Link key={item.href} href={item.href} className={clsx("whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium", active ? "bg-brand-50 text-brand-700" : "text-slate-600")} aria-current={active ? "page" : undefined}>
                {item.shortLabel}
              </Link>
            );
          })}
        </nav>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-7 sm:px-6 lg:py-9">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow text-brand-600">Authority workspace</p>
            <h1 className="mt-1.5 text-2xl font-semibold tracking-[-0.03em] text-slate-950">{title}</h1>
          </div>
          {actions}
        </div>
        {children}
      </main>
      <footer className="border-t border-slate-200 bg-white/80 px-4 py-4 sm:px-6">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
          <span>VayuSetu · evidence for the next decision</span>
          <span>Citizen reports are pseudonymous · Phone numbers stay out of the dashboard</span>
        </div>
      </footer>
    </div>
  );
}
