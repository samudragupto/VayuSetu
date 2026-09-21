"use client";

import { collection, limit, onSnapshot, orderBy, query, Timestamp, where, type DocumentData, type QueryDocumentSnapshot } from "firebase/firestore";
import { useEffect, useMemo, useState } from "react";

import { alertFromDoc, hotspotFromDoc, reportFromDoc } from "@/lib/converters";
import { getFirebase } from "@/lib/firebase";
import type { AlertLogEntry, CitizenReport, PredictedHotspot } from "@/lib/types";

import { useAuth } from "./useAuth";

export interface CollectionState<T> {
  items: T[];
  loading: boolean;
  error: string | null;
}

interface WindowedQueryOptions<T> {
  collectionName: string;
  timestampField: string;
  hours: number;
  maxDocs: number;
  convert: (doc: QueryDocumentSnapshot<DocumentData>) => T;
  extraWhere?: { field: string; op: "==" | "in"; value: unknown };
}

/**
 * Subscribe to a time-windowed Firestore collection with realtime updates.
 * Subscriptions are only opened for authorised administrators.
 */
export function useWindowedCollection<T>(options: WindowedQueryOptions<T>): CollectionState<T> {
  const { status } = useAuth();
  const [state, setState] = useState<CollectionState<T>>({ items: [], loading: true, error: null });
  const windowStartMs = useMemo(() => {
    // Align to the minute so React does not resubscribe on every render.
    const now = Date.now();
    return now - (now % 60_000) - options.hours * 3_600_000;
  }, [options.hours]);

  const { collectionName, timestampField, maxDocs, convert } = options;
  const extraField = options.extraWhere?.field;
  const extraOp = options.extraWhere?.op;
  const extraValue = options.extraWhere?.value;

  useEffect(() => {
    if (status !== "authorised") {
      setState({ items: [], loading: status === "initialising", error: null });
      return;
    }
    const firebase = getFirebase();
    if (!firebase) {
      setState({ items: [], loading: false, error: "Firebase is not configured" });
      return;
    }
    const constraints = [where(timestampField, ">=", Timestamp.fromMillis(windowStartMs))];
    if (extraField && extraOp) {
      constraints.push(where(extraField, extraOp, extraValue));
    }
    const q = query(collection(firebase.db, collectionName), ...constraints, orderBy(timestampField, "desc"), limit(maxDocs));
    setState((previous) => ({ ...previous, loading: true, error: null }));
    const unsubscribe = onSnapshot(
      q,
      (snapshot) => {
        setState({ items: snapshot.docs.map(convert), loading: false, error: null });
      },
      (error) => {
        console.error(`Firestore subscription failed for ${collectionName}`, error);
        setState({ items: [], loading: false, error: error.message });
      }
    );
    return unsubscribe;
  }, [status, collectionName, timestampField, windowStartMs, maxDocs, convert, extraField, extraOp, extraValue]);

  return state;
}

export function useReports(hours: number, maxDocs = 1500): CollectionState<CitizenReport> {
  return useWindowedCollection({ collectionName: "citizen_reports", timestampField: "createdAt", hours, maxDocs, convert: reportFromDoc });
}

export function useHotspots(hours: number, maxDocs = 1000): CollectionState<PredictedHotspot> {
  return useWindowedCollection({ collectionName: "predicted_hotspots", timestampField: "generatedAt", hours, maxDocs, convert: hotspotFromDoc });
}

export function useAlerts(hours: number, maxDocs = 500): CollectionState<AlertLogEntry> {
  return useWindowedCollection({ collectionName: "alert_log", timestampField: "sentAt", hours, maxDocs, convert: alertFromDoc });
}
