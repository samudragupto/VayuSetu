"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/hooks/useAuth";
import { config } from "@/lib/config";

import { ErrorState, LoadingState } from "./States";

function GoogleMark() {
  return (
    <svg aria-hidden="true" width="18" height="18" viewBox="0 0 48 48">
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.3l7.9 6.1C12.4 13.4 17.7 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4.1 7.1-10.1 7.1-17.5z" />
      <path fill="#FBBC05" d="M10.5 28.6A14.5 14.5 0 0 1 9.7 24c0-1.6.3-3.1.8-4.6l-7.9-6.1A24 24 0 0 0 0 24c0 3.9.9 7.5 2.6 10.7l7.9-6.1z" />
      <path fill="#34A853" d="M24 48c6.3 0 11.7-2.1 15.6-5.7l-7.5-5.8c-2.1 1.4-4.8 2.3-8.1 2.3-6.3 0-11.6-3.9-13.5-9.4l-7.9 6.1C6.5 42.6 14.6 48 24 48z" />
    </svg>
  );
}

export function LoginPanel() {
  const { status, error, signIn } = useAuth();
  const router = useRouter();
  const isLocalDemo = config.useEmulators;
  const domainText = config.adminDomains.length > 0 ? config.adminDomains.join(", ") : "the configured administrator domain";

  useEffect(() => {
    if (status === "authorised") {
      router.replace("/");
    }
  }, [status, router]);

  return (
    <div className="min-h-screen overflow-hidden bg-[#08152f] text-white">
      <div className="pointer-events-none fixed inset-0 opacity-80" aria-hidden="true">
        <div className="absolute -left-32 -top-40 h-96 w-96 rounded-full bg-brand-600/30 blur-3xl" />
        <div className="absolute bottom-0 right-0 h-[32rem] w-[32rem] rounded-full bg-cyan-400/10 blur-3xl" />
        <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.035)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.035)_1px,transparent_1px)] bg-[size:48px_48px]" />
      </div>

      <main className="relative mx-auto grid min-h-screen max-w-6xl gap-8 px-5 py-6 sm:px-8 lg:grid-cols-[1.08fr_.92fr] lg:items-center lg:gap-16 lg:py-10">
        <section className="flex flex-col justify-between py-4 lg:min-h-[720px] lg:py-10">
          <div>
            <div className="flex items-center gap-3">
              <span className="brand-mark brand-mark-dark" aria-hidden="true">
                <span />
                <span />
                <span />
              </span>
              <div>
                <p className="text-lg font-semibold tracking-tight">VayuSetu</p>
                <p className="text-xs text-slate-400">Air quality intelligence for the people who act</p>
              </div>
            </div>

            <p className="eyebrow mt-16 text-cyan-300">Authority workspace</p>
            <h1 className="mt-4 max-w-xl text-4xl font-semibold leading-[1.08] tracking-[-0.04em] text-white sm:text-5xl">
              See where the air is changing. Decide before it settles.
            </h1>
            <p className="mt-6 max-w-lg text-base leading-7 text-slate-300">
              VayuSetu turns ordinary WhatsApp photos into a local signal for the control room. Citizen observations, satellite context and a twelve-hour forecast arrive in one calm, practical view.
            </p>
          </div>

          <div className="mt-12 max-w-xl rounded-2xl border border-white/10 bg-white/[0.06] p-5 backdrop-blur-sm">
            <div className="flex items-center justify-between gap-4">
              <p className="text-sm font-semibold text-white">One report, carried all the way through</p>
              <span className="rounded-full border border-emerald-300/20 bg-emerald-300/10 px-2.5 py-1 text-[11px] font-medium text-emerald-200">Evidence first</span>
            </div>
            <div className="mt-5 grid gap-4 sm:grid-cols-3">
              {[
                ["01", "Citizen signal", "A photo and location, without another app."],
                ["02", "Shared context", "Gemini and Sentinel-5P add meaning."],
                ["03", "Clear next step", "Forecast, confidence and alert trail."],
              ].map(([number, title, description]) => (
                <div key={number} className="border-l border-white/15 pl-3">
                  <span className="font-mono text-xs text-cyan-300">{number}</span>
                  <p className="mt-2 text-sm font-medium text-white">{title}</p>
                  <p className="mt-1 text-xs leading-5 text-slate-400">{description}</p>
                </div>
              ))}
            </div>
          </div>

          <p className="mt-8 text-xs leading-5 text-slate-500">
            Built for the person on duty, not for a data scientist. The dashboard keeps the source, model confidence and dispatch history visible beside the decision.
          </p>
        </section>

        <section className="rounded-[1.75rem] bg-[#fbfcfe] p-6 text-slate-900 shadow-2xl shadow-black/25 sm:p-8">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="eyebrow text-brand-600">Secure access</p>
              <h2 className="mt-2 text-2xl font-semibold tracking-tight">Welcome to the control room</h2>
            </div>
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-700" aria-hidden="true">
              <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M12 3 5 6v5c0 4.6 2.9 8.7 7 10 4.1-1.3 7-5.4 7-10V6l-7-3Z" />
                <path d="m9.5 12 1.7 1.7 3.5-3.8" />
              </svg>
            </span>
          </div>

          <p className="mt-5 text-sm leading-6 text-slate-600">
            {isLocalDemo ? (
              <>This local preview accepts a demo Google account on <strong className="font-semibold text-slate-900">{domainText}</strong>. Production access remains restricted to verified Workspace accounts.</>
            ) : (
              <>Access is limited to verified Google Workspace accounts on <strong className="font-semibold text-slate-900">{domainText}</strong>.</>
            )}
          </p>

          <div className="mt-5 flex items-center gap-2 rounded-xl border border-brand-100 bg-brand-50 px-3 py-2.5 text-xs text-brand-800">
            <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-500" aria-hidden="true" />
            <span>{isLocalDemo ? "Local emulator · data stays on this machine" : "Workspace policy · read-only authority view"}</span>
          </div>

          <div className="mt-6 space-y-3">
            {status === "initialising" ? <LoadingState message="Checking your session" /> : null}
            {status === "unconfigured" ? (
              <ErrorState message="Firebase is not configured for this build. Set the NEXT_PUBLIC_FIREBASE_* variables, or enable NEXT_PUBLIC_USE_EMULATORS for the local preview, then rebuild." />
            ) : null}
            {error ? <ErrorState message={error} /> : null}
            {status === "unauthorised" ? <p className="-mt-1 text-xs text-slate-500">Choose a different Google account ending in @{domainText}, then try again.</p> : null}
            {status === "signed_out" || status === "unauthorised" ? (
              <button type="button" className="btn-primary w-full py-3" onClick={() => void signIn()}>
                <GoogleMark />
                {status === "unauthorised" ? "Try another Google account" : "Sign in with Google"}
              </button>
            ) : null}
          </div>

          <div className="mt-7 border-t border-slate-200 pt-5">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Inside the workspace</p>
            <ul className="mt-3 space-y-3 text-sm text-slate-600">
              <li className="flex gap-3"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan-500" />Live citizen reports with pseudonymous IDs, not phone numbers.</li>
              <li className="flex gap-3"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan-500" />A forecast with the evidence and confidence needed to act responsibly.</li>
              <li className="flex gap-3"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan-500" />An audit trail for every multilingual authority dispatch.</li>
            </ul>
          </div>

          <p className="mt-7 flex items-start gap-2 text-xs leading-5 text-slate-400">
            <svg className="mt-0.5 shrink-0" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M12 3 5 6v5c0 4.6 2.9 8.7 7 10 4.1-1.3 7-5.4 7-10V6l-7-3Z" /><path d="M9 12h6M12 9v6" /></svg>
            Reports are pseudonymous. Phone numbers are never displayed on this dashboard.
          </p>
        </section>
      </main>
    </div>
  );
}
