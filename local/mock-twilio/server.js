"use strict";

/**
 * Mock Twilio server for local development.
 *
 * Emulates the subset of the Twilio REST API used by VayuSetu (Messages and
 * Calls resources, media downloads) and offers a /simulate/inbound helper that
 * posts a realistic WhatsApp webhook to the API gateway. No real messages are
 * ever sent, so Twilio sandbox quotas are not consumed during development.
 */

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const express = require("express");

const PORT = Number(process.env.PORT || 4010);
const PUBLIC_URL = (process.env.MOCK_TWILIO_PUBLIC_URL || `http://mock-twilio:${PORT}`).replace(/\/+$/, "");
const GATEWAY_WEBHOOK_URL = process.env.GATEWAY_WEBHOOK_URL || "http://api-gateway:8080/webhooks/twilio/whatsapp";
const ACCOUNT_SID = process.env.TWILIO_ACCOUNT_SID || "ACmock00000000000000000000000000";
const MEDIA_DIR = path.join(__dirname, "media");

const outbound = [];
const inbound = [];

const app = express();
app.use(express.urlencoded({ extended: false }));
app.use(express.json());

function log(message, extra = {}) {
  process.stdout.write(`${JSON.stringify({ time: new Date().toISOString(), service: "mock-twilio", message, ...extra })}\n`);
}

function newSid(prefix) {
  return `${prefix}${crypto.randomBytes(16).toString("hex")}`;
}

function requireBasicAuth(req, res, next) {
  const header = req.get("authorization") || "";
  if (!header.startsWith("Basic ")) {
    res.status(401).json({ code: 20003, message: "Authentication Error - No credentials provided", status: 401 });
    return;
  }
  next();
}

// --- Twilio REST API -------------------------------------------------------

app.post("/2010-04-01/Accounts/:sid/Messages.json", requireBasicAuth, (req, res) => {
  const record = {
    sid: newSid("SM"),
    account_sid: req.params.sid,
    to: req.body.To,
    from: req.body.From,
    body: req.body.Body,
    status: "queued",
    direction: "outbound-api",
    num_segments: "1",
    date_created: new Date().toUTCString(),
    date_sent: null,
    error_code: null,
    error_message: null,
    uri: `/2010-04-01/Accounts/${req.params.sid}/Messages/${newSid("SM")}.json`,
  };
  outbound.push({ kind: "message", ...record });
  log("Outbound message accepted", { to: record.to, preview: String(record.body || "").slice(0, 80) });
  res.status(201).json(record);
});

app.post("/2010-04-01/Accounts/:sid/Calls.json", requireBasicAuth, (req, res) => {
  const record = {
    sid: newSid("CA"),
    account_sid: req.params.sid,
    to: req.body.To,
    from: req.body.From,
    status: "queued",
    direction: "outbound-api",
    twiml: req.body.Twiml || null,
    url: req.body.Url || null,
    date_created: new Date().toUTCString(),
  };
  outbound.push({ kind: "call", ...record });
  log("Outbound call accepted", { to: record.to, twimlPreview: String(record.twiml || "").slice(0, 120) });
  res.status(201).json(record);
});

app.get("/2010-04-01/Accounts/:sid/Messages.json", requireBasicAuth, (_req, res) => {
  res.json({ messages: outbound.filter((item) => item.kind === "message") });
});

app.get("/2010-04-01/Accounts/:sid/Calls.json", requireBasicAuth, (_req, res) => {
  res.json({ calls: outbound.filter((item) => item.kind === "call") });
});

// --- Media -----------------------------------------------------------------

app.get("/media/:name", requireBasicAuth, (req, res) => {
  const safeName = path.basename(req.params.name);
  const file = path.join(MEDIA_DIR, safeName);
  if (!fs.existsSync(file)) {
    res.status(404).json({ code: 20404, message: "The requested resource was not found", status: 404 });
    return;
  }
  const extension = path.extname(safeName).toLowerCase();
  const contentType = extension === ".png" ? "image/png" : extension === ".webp" ? "image/webp" : "image/jpeg";
  res.type(contentType).sendFile(file);
});

app.get("/media", (_req, res) => {
  res.json({ media: fs.readdirSync(MEDIA_DIR).filter((name) => !name.startsWith(".")) });
});

// --- Simulation helpers ----------------------------------------------------

/**
 * POST /simulate/inbound
 * {
 *   "from": "+919876543210",
 *   "body": "optional caption or command",
 *   "media": "hazy_delhi.jpg",          // optional, one of GET /media
 *   "latitude": 28.61, "longitude": 77.21,  // optional location share
 *   "profileName": "Asha"
 * }
 */
app.post("/simulate/inbound", async (req, res) => {
  const payload = req.body || {};
  const from = String(payload.from || "+919876543210").replace(/^whatsapp:/, "");
  const form = new URLSearchParams({
    MessageSid: newSid("SM"),
    SmsMessageSid: newSid("SM"),
    AccountSid: ACCOUNT_SID,
    From: `whatsapp:${from}`,
    To: `whatsapp:${process.env.TWILIO_WHATSAPP_FROM || "+14155238886"}`,
    Body: String(payload.body || ""),
    NumMedia: payload.media ? "1" : "0",
    ProfileName: String(payload.profileName || "Citizen"),
    WaId: from.replace(/^\+/, ""),
  });
  if (payload.media) {
    const extension = path.extname(String(payload.media)).toLowerCase();
    form.set("MediaUrl0", `${PUBLIC_URL}/media/${path.basename(String(payload.media))}`);
    form.set("MediaContentType0", extension === ".png" ? "image/png" : extension === ".webp" ? "image/webp" : "image/jpeg");
  }
  if (payload.latitude !== undefined && payload.longitude !== undefined) {
    form.set("Latitude", String(payload.latitude));
    form.set("Longitude", String(payload.longitude));
    if (payload.address) {
      form.set("Address", String(payload.address));
    }
  }

  const started = Date.now();
  try {
    const response = await fetch(GATEWAY_WEBHOOK_URL, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded", "x-twilio-signature": "mock" },
      body: form.toString(),
    });
    const text = await response.text();
    const record = { messageSid: form.get("MessageSid"), from, status: response.status, reply: text, elapsedMs: Date.now() - started };
    inbound.push(record);
    log("Simulated inbound webhook delivered", { status: response.status, elapsedMs: record.elapsedMs });
    res.status(response.ok ? 200 : 502).json(record);
  } catch (error) {
    log("Simulated inbound webhook failed", { error: error.message });
    res.status(502).json({ error: error.message, gateway: GATEWAY_WEBHOOK_URL });
  }
});

app.get("/_admin/log", (_req, res) => {
  res.json({ outbound: outbound.slice(-200), inbound: inbound.slice(-200) });
});

app.delete("/_admin/log", (_req, res) => {
  outbound.length = 0;
  inbound.length = 0;
  res.status(204).end();
});

app.get("/healthz", (_req, res) => {
  res.json({ status: "ok", outbound: outbound.length, inbound: inbound.length });
});

app.get("/", (_req, res) => {
  const rows = outbound
    .slice(-50)
    .reverse()
    .map(
      (item) =>
        `<tr><td>${item.kind}</td><td>${item.to || ""}</td><td>${item.status}</td><td><pre>${escapeHtml(item.body || item.twiml || "")}</pre></td><td>${item.date_created}</td></tr>`
    )
    .join("");
  res.type("html").send(`<!doctype html><html><head><meta charset="utf-8"><title>Mock Twilio</title>
<style>body{font-family:system-ui,sans-serif;margin:2rem;color:#1e293b}table{border-collapse:collapse;width:100%}td,th{border:1px solid #cbd5e1;padding:.4rem;text-align:left;vertical-align:top;font-size:.85rem}pre{white-space:pre-wrap;margin:0}</style></head>
<body><h1>Mock Twilio</h1><p>Outbound messages and calls captured from VayuSetu services. Use <code>POST /simulate/inbound</code> to inject a WhatsApp message.</p>
<table><thead><tr><th>Kind</th><th>To</th><th>Status</th><th>Content</th><th>Created</th></tr></thead><tbody>${rows || "<tr><td colspan=5>No outbound traffic yet</td></tr>"}</tbody></table></body></html>`);
});

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

app.listen(PORT, "0.0.0.0", () => {
  log("Mock Twilio listening", { port: PORT, gateway: GATEWAY_WEBHOOK_URL, publicUrl: PUBLIC_URL });
});
