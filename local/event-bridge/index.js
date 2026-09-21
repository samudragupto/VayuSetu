"use strict";

/**
 * VayuSetu local event bridge.
 *
 * In production, Eventarc delivers Cloud Storage and Firestore events to the
 * Python Cloud Functions. The Firebase Local Emulator Suite cannot target
 * arbitrary containers, so this small Firebase Functions codebase runs inside
 * the Functions emulator, listens to Firestore triggers and re-emits the
 * equivalent CloudEvents over HTTP to the locally running function containers.
 *
 * Environment variables (set by docker-compose):
 *   PROCESS_IMAGE_URL   process_citizen_image container (storage finalize events)
 *   FETCH_GEE_URL       fetch_gee_metrics container (Firestore create events)
 *   ALERTS_URL          send_authority_alerts container (Firestore create events)
 *   STORAGE_API_URL     fake GCS endpoint used to wait for the uploaded object
 */

const crypto = require("node:crypto");
const { onDocumentCreated } = require("firebase-functions/v2/firestore");
const { setGlobalOptions } = require("firebase-functions/v2");
const logger = require("firebase-functions/logger");

setGlobalOptions({ region: "us-central1", maxInstances: 3 });

const PROCESS_IMAGE_URL = process.env.PROCESS_IMAGE_URL || "http://fn-process-image:8080";
const FETCH_GEE_URL = process.env.FETCH_GEE_URL || "http://fn-fetch-gee:8080";
const ALERTS_URL = process.env.ALERTS_URL || "http://fn-alerts:8080";
const STORAGE_API_URL = (process.env.STORAGE_API_URL || "http://gcs:4443").replace(/\/+$/, "");
const PROJECT_ID = process.env.GCLOUD_PROJECT || process.env.GCP_PROJECT_ID || "vayusetu-local";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Deliver a CloudEvent in binary content mode with exponential backoff. */
async function deliver(targetUrl, attributes, data, attempts = 5) {
  const headers = {
    "content-type": "application/json",
    "ce-specversion": "1.0",
    "ce-id": attributes.id || crypto.randomUUID(),
    "ce-time": attributes.time || new Date().toISOString(),
    "ce-type": attributes.type,
    "ce-source": attributes.source,
  };
  if (attributes.subject) {
    headers["ce-subject"] = attributes.subject;
  }
  for (const [key, value] of Object.entries(attributes.extensions || {})) {
    headers[`ce-${key}`] = String(value);
  }

  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(targetUrl, { method: "POST", headers, body: JSON.stringify(data) });
      if (response.ok) {
        logger.info("CloudEvent delivered", { target: targetUrl, type: attributes.type, subject: attributes.subject, attempt });
        return;
      }
      const text = await response.text();
      lastError = new Error(`HTTP ${response.status}: ${text.slice(0, 200)}`);
      if (response.status < 500 && response.status !== 429) {
        break;
      }
    } catch (error) {
      lastError = error;
    }
    const delayMs = Math.min(15000, 500 * 2 ** (attempt - 1));
    logger.warn("CloudEvent delivery failed; retrying", { target: targetUrl, attempt, delayMs, error: String(lastError && lastError.message) });
    await sleep(delayMs);
  }
  logger.error("CloudEvent delivery abandoned", { target: targetUrl, type: attributes.type, error: String(lastError && lastError.message) });
}

function parseGsUri(uri) {
  const match = /^gs:\/\/([^/]+)\/(.+)$/.exec(String(uri || ""));
  return match ? { bucket: match[1], name: match[2] } : null;
}

/** Wait until the object exists in the storage emulator (the gateway uploads after creating the report). */
async function waitForObject(bucket, name, timeoutMs = 45000) {
  const url = `${STORAGE_API_URL}/storage/v1/b/${encodeURIComponent(bucket)}/o/${encodeURIComponent(name)}`;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) {
        return await response.json();
      }
    } catch (error) {
      logger.debug("Storage probe failed", { error: String(error.message) });
    }
    await sleep(1000);
  }
  return null;
}

function firestoreEvent(collection, documentId, snapshotData, eventType) {
  const name = `projects/${PROJECT_ID}/databases/(default)/documents/${collection}/${documentId}`;
  return {
    attributes: {
      type: eventType,
      source: `//firestore.googleapis.com/projects/${PROJECT_ID}/databases/(default)`,
      subject: `documents/${collection}/${documentId}`,
      extensions: { document: `${collection}/${documentId}`, database: "(default)", namespace: "(default)" },
    },
    data: {
      value: { name, fields: snapshotData, createTime: new Date().toISOString(), updateTime: new Date().toISOString() },
      oldValue: {},
      updateMask: {},
    },
  };
}

exports.onReportCreated = onDocumentCreated({ document: "citizen_reports/{reportId}", timeoutSeconds: 120 }, async (event) => {
  const snapshot = event.data;
  if (!snapshot) {
    return;
  }
  const reportId = event.params.reportId;
  const report = snapshot.data() || {};
  const object = parseGsUri(report.imageUri);

  if (object) {
    const metadata = await waitForObject(object.bucket, object.name);
    if (!metadata) {
      logger.error("Image never appeared in storage; skipping vision dispatch", { reportId, imageUri: report.imageUri });
    } else {
      await deliver(
        PROCESS_IMAGE_URL,
        {
          type: "google.cloud.storage.object.v1.finalized",
          source: `//storage.googleapis.com/projects/_/buckets/${object.bucket}`,
          subject: `objects/${object.name}`,
        },
        {
          kind: "storage#object",
          id: `${object.bucket}/${object.name}/${metadata.generation || 1}`,
          bucket: object.bucket,
          name: object.name,
          contentType: metadata.contentType || report.contentType || "image/jpeg",
          size: String(metadata.size || 0),
          generation: String(metadata.generation || 1),
          metageneration: "1",
          timeCreated: metadata.timeCreated || new Date().toISOString(),
          updated: metadata.updated || new Date().toISOString(),
          metadata: { reportId, ...(metadata.metadata || {}) },
        }
      );
    }
  } else {
    logger.warn("Report has no gs:// imageUri; vision dispatch skipped", { reportId });
  }

  if (report.location) {
    const fsEvent = firestoreEvent("citizen_reports", reportId, {}, "google.cloud.firestore.document.v1.created");
    await deliver(FETCH_GEE_URL, fsEvent.attributes, fsEvent.data);
  } else {
    logger.info("Report has no location; satellite dispatch skipped", { reportId });
  }
});

exports.onHotspotCreated = onDocumentCreated({ document: "predicted_hotspots/{hotspotId}", timeoutSeconds: 120 }, async (event) => {
  const hotspotId = event.params.hotspotId;
  const fsEvent = firestoreEvent("predicted_hotspots", hotspotId, {}, "google.cloud.firestore.document.v1.created");
  await deliver(ALERTS_URL, fsEvent.attributes, fsEvent.data);
});
