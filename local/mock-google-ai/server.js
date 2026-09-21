"use strict";

/**
 * Mock Google AI Studio server for local development.
 *
 * Implements the generateContent and models endpoints of the Gemini REST API
 * closely enough for the google-generativeai Python SDK (REST transport) to
 * operate without a real API key. Responses are deterministic functions of
 * the submitted image bytes so repeated runs produce identical analyses.
 *
 * Behaviour switches (environment variables):
 *   MOCK_AVAILABLE_MODELS      comma separated model ids that respond (others return 404)
 *   MOCK_RATE_LIMIT_PROBABILITY probability [0,1] of returning HTTP 429 to exercise backoff
 *   MOCK_LATENCY_MS            artificial latency per request
 */

const crypto = require("node:crypto");
const express = require("express");

const PORT = Number(process.env.PORT || 4020);
const AVAILABLE_MODELS = (process.env.MOCK_AVAILABLE_MODELS || "gemini-1.5-flash,gemini-flash-latest,gemini-2.5-flash")
  .split(",")
  .map((m) => m.trim())
  .filter(Boolean);
const RATE_LIMIT_PROBABILITY = Math.min(1, Math.max(0, Number(process.env.MOCK_RATE_LIMIT_PROBABILITY || 0.1)));
const LATENCY_MS = Math.max(0, Number(process.env.MOCK_LATENCY_MS || 400));

const app = express();
app.use(express.json({ limit: "25mb" }));

function log(message, extra = {}) {
  process.stdout.write(`${JSON.stringify({ time: new Date().toISOString(), service: "mock-google-ai", message, ...extra })}\n`);
}

function requireApiKey(req, res, next) {
  const key = req.get("x-goog-api-key") || req.query.key;
  if (!key) {
    res.status(403).json({ error: { code: 403, message: "Method doesn't allow unregistered callers (callers without established identity). Please use API Key or other form of API consumer identity to call this API.", status: "PERMISSION_DENIED" } });
    return;
  }
  next();
}

const SCENARIOS = [
  {
    name: "clear",
    analysis: {
      is_outdoor_scene: true,
      haze_index: 0.12,
      visibility_km: 12.0,
      visibility_category: "excellent",
      sky_condition: "clear",
      smoke_detected: false,
      dust_detected: false,
      fog_or_mist_detected: false,
      open_burning_detected: false,
      vehicle_density_score: 0.25,
      construction_activity_score: 0.05,
      industrial_emission_score: 0.0,
      pollution_sources: ["vehicular"],
      estimated_aqi_category: "satisfactory",
      estimated_aqi: 78,
      confidence: 0.82,
      reasoning: "Deep blue sky with sharp building edges and distant horizon clearly visible; light traffic on the road.",
    },
  },
  {
    name: "moderate_haze",
    analysis: {
      is_outdoor_scene: true,
      haze_index: 0.55,
      visibility_km: 3.5,
      visibility_category: "moderate",
      sky_condition: "hazy",
      smoke_detected: false,
      dust_detected: true,
      fog_or_mist_detected: false,
      open_burning_detected: false,
      vehicle_density_score: 0.6,
      construction_activity_score: 0.45,
      industrial_emission_score: 0.1,
      pollution_sources: ["vehicular", "construction_dust"],
      estimated_aqi_category: "poor",
      estimated_aqi: 236,
      confidence: 0.71,
      reasoning: "Brownish haze flattens contrast; buildings beyond roughly three kilometres are indistinct and traffic is dense.",
    },
  },
  {
    name: "severe_smoke",
    analysis: {
      is_outdoor_scene: true,
      haze_index: 0.88,
      visibility_km: 0.9,
      visibility_category: "very_poor",
      sky_condition: "smoky",
      smoke_detected: true,
      dust_detected: false,
      fog_or_mist_detected: false,
      open_burning_detected: true,
      vehicle_density_score: 0.4,
      construction_activity_score: 0.1,
      industrial_emission_score: 0.3,
      pollution_sources: ["waste_burning", "crop_residue_burning", "vehicular"],
      estimated_aqi_category: "severe",
      estimated_aqi: 412,
      confidence: 0.77,
      reasoning: "Dense grey smoke plume with an identifiable burning source; sun heavily obscured and visibility under one kilometre.",
    },
  },
  {
    name: "indoor",
    analysis: {
      is_outdoor_scene: false,
      haze_index: 0.0,
      visibility_km: null,
      visibility_category: "unknown",
      sky_condition: "unknown",
      smoke_detected: false,
      dust_detected: false,
      fog_or_mist_detected: false,
      open_burning_detected: false,
      vehicle_density_score: 0.0,
      construction_activity_score: 0.0,
      industrial_emission_score: 0.0,
      pollution_sources: ["unknown"],
      estimated_aqi_category: "unknown",
      estimated_aqi: null,
      confidence: 0.2,
      reasoning: "The image shows an interior space with no view of the sky; air quality cannot be assessed.",
    },
  },
];

function pickScenario(imageBase64) {
  if (!imageBase64) {
    return SCENARIOS[1];
  }
  const buffer = Buffer.from(imageBase64, "base64");
  // Sample images bundled with the mock Twilio server carry an explicit marker
  // in the JPEG comment segment so demos are fully deterministic.
  const header = buffer.subarray(0, 4096).toString("latin1");
  const marker = header.match(/vayusetu-scenario:([a-z_]+)/);
  if (marker) {
    const named = SCENARIOS.find((scenario) => scenario.name === marker[1]);
    if (named) {
      return named;
    }
  }
  // Arbitrary images map to a stable pseudo-random scenario weighted towards
  // the polluted end of the distribution, mirroring a winter smog episode.
  const digest = crypto.createHash("sha1").update(buffer).digest();
  const bucket = digest[0] % 100;
  if (bucket < 20) {
    return SCENARIOS[0];
  }
  if (bucket < 60) {
    return SCENARIOS[1];
  }
  if (bucket < 92) {
    return SCENARIOS[2];
  }
  return SCENARIOS[3];
}

function extractImage(body) {
  const contents = Array.isArray(body.contents) ? body.contents : [];
  for (const content of contents) {
    for (const part of content.parts || []) {
      const inline = part.inline_data || part.inlineData;
      if (inline && inline.data) {
        return { data: inline.data, mimeType: inline.mime_type || inline.mimeType };
      }
    }
  }
  return null;
}

function generateContentHandler(req, res) {
  const modelAction = String(req.params.modelAction || "");
  const [modelName, action] = modelAction.split(":");
  if (action !== "generateContent") {
    res.status(404).json({ error: { code: 404, message: `Unsupported method ${action}`, status: "NOT_FOUND" } });
    return;
  }
  if (!AVAILABLE_MODELS.includes(modelName)) {
    log("Model not found", { model: modelName });
    res.status(404).json({
      error: {
        code: 404,
        message: `models/${modelName} is not found for API version v1beta, or is not supported for generateContent. Call ListModels to see the list of available models and their supported methods.`,
        status: "NOT_FOUND",
      },
    });
    return;
  }
  if (Math.random() < RATE_LIMIT_PROBABILITY) {
    log("Injected rate limit", { model: modelName });
    res.status(429).json({
      error: {
        code: 429,
        message: "Resource has been exhausted (e.g. check quota).",
        status: "RESOURCE_EXHAUSTED",
        details: [{ "@type": "type.googleapis.com/google.rpc.RetryInfo", retryDelay: "2s" }],
      },
    });
    return;
  }

  const image = extractImage(req.body || {});
  const scenario = pickScenario(image ? image.data : null);
  const text = JSON.stringify(scenario.analysis);
  const promptTokens = Math.round(JSON.stringify(req.body || {}).length / 4);

  setTimeout(() => {
    res.json({
      candidates: [
        {
          content: { parts: [{ text }], role: "model" },
          finishReason: "STOP",
          index: 0,
          safetyRatings: [
            { category: "HARM_CATEGORY_HARASSMENT", probability: "NEGLIGIBLE" },
            { category: "HARM_CATEGORY_HATE_SPEECH", probability: "NEGLIGIBLE" },
            { category: "HARM_CATEGORY_SEXUALLY_EXPLICIT", probability: "NEGLIGIBLE" },
            { category: "HARM_CATEGORY_DANGEROUS_CONTENT", probability: "NEGLIGIBLE" },
          ],
        },
      ],
      usageMetadata: { promptTokenCount: promptTokens, candidatesTokenCount: Math.round(text.length / 4), totalTokenCount: promptTokens + Math.round(text.length / 4) },
      modelVersion: modelName,
    });
    log("generateContent served", { model: modelName, scenario: scenario.name, hasImage: Boolean(image) });
  }, LATENCY_MS);
}

app.post("/v1beta/models/:modelAction", requireApiKey, generateContentHandler);
app.post("/v1/models/:modelAction", requireApiKey, generateContentHandler);

function modelDescriptor(name) {
  return {
    name: `models/${name}`,
    version: "001",
    displayName: name,
    description: "Mock model served by the VayuSetu local development stack",
    inputTokenLimit: 1048576,
    outputTokenLimit: 8192,
    supportedGenerationMethods: ["generateContent", "countTokens"],
    temperature: 1,
    topP: 0.95,
    topK: 64,
  };
}

app.get(["/v1beta/models", "/v1/models"], requireApiKey, (_req, res) => {
  res.json({ models: AVAILABLE_MODELS.map(modelDescriptor) });
});

app.get(["/v1beta/models/:model", "/v1/models/:model"], requireApiKey, (req, res) => {
  const model = String(req.params.model);
  if (!AVAILABLE_MODELS.includes(model)) {
    res.status(404).json({ error: { code: 404, message: `models/${model} is not found`, status: "NOT_FOUND" } });
    return;
  }
  res.json(modelDescriptor(model));
});

app.get("/healthz", (_req, res) => {
  res.json({ status: "ok", models: AVAILABLE_MODELS, rateLimitProbability: RATE_LIMIT_PROBABILITY });
});

app.listen(PORT, "0.0.0.0", () => {
  log("Mock Google AI Studio listening", { port: PORT, models: AVAILABLE_MODELS, rateLimitProbability: RATE_LIMIT_PROBABILITY });
});
