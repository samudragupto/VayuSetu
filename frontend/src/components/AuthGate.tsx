"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { useAuth } from "@/hooks/useAuth";

import { LoadingState } from "./States";

/** Redirects unauthenticated or unauthorised visitors to the login page. */
export function AuthGate({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "signed_out" || status === "unauthorised" || status === "unconfigured") {
      router.replace("/login/");
    }
  }, [status, router]);

  if (status !== "authorised") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <LoadingState message={status === "initialising" ? "Checking your session" : "Redirecting to sign in"} />
      </div>
    );
  }
  return <>{children}</>;
}
