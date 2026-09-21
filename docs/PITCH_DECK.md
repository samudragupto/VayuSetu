# VayuSetu - Pitch Deck

Ten slides. Each slide lists the exact on-slide text (title, body and footer) followed by the speaker notes. Keep body text as written; the notes are guidance for the presenter and are not shown.

Suggested visual language: dark navy background, amber accent for air quality data, white typography, one figure per slide. Every figure referenced below can be produced from the repository (dashboard screenshots, `docs/DEMO_SCRIPT.md` outputs, `ml/artifacts/model_metrics.json`).

---

## Slide 1 - Title

**Title:** VayuSetu

**Subtitle:** A bridge between citizens and clean air. Multimodal, hyper-local air quality intelligence for India, built on Google Cloud.

**Body:**

- WhatsApp photo in, twelve-hour AQI forecast out
- Gemini vision, Earth Engine satellites, custom XGBoost, multilingual voice alerts
- Fully serverless, runs within Google Cloud free tiers

**Footer:** Google Cloud Build with AI: Code for Communities, India 2026

**Speaker notes:** Introduce the team in one sentence each. State the one-line thesis: India cannot build enough monitoring stations, but it already has 500 million cameras connected to WhatsApp.

---

## Slide 2 - Problem-Solution Fit

**Title:** The problem: pollution is hyper-local, monitoring is not

**Body:**

Left column, "Today":

- About 900 continuous monitoring stations for 1.4 billion people; most districts have none
- Station readings are averaged over kilometres; exposure differs street by street
- Authorities learn of severe episodes after they peak, from the same bulletins citizens read
- Air pollution is linked to roughly 1.6 million premature deaths in India each year

Right column, "VayuSetu":

- Any WhatsApp user becomes a sensor with a single photo and a shared location
- Gemini extracts haze, visibility and pollution sources as structured data
- Sentinel-5P and MODIS satellite columns calibrate every observation
- A forecast, not a reading: twelve hours of warning per five-kilometre cell
- Authorities receive the warning as a phone call in their own language

**Footer:** No app, no sensor purchase, no new infrastructure for the citizen or the municipality.

**Speaker notes:** Stress the reversal of the information flow. Today citizens wait for the government to publish AQI; with VayuSetu the citizens produce the data and the government receives the forecast. Mention that the Graded Response Action Plan already defines what authorities must do at each AQI level; the missing piece is timely, local triggering.

---

## Slide 3 - How it works

**Title:** From a photograph to a phone call in under a minute

**Body (pipeline diagram with six labelled stages):**

1. Citizen sends a sky photograph and location on WhatsApp (Twilio)
2. Node.js gateway on Cloud Run verifies, pseudonymises, stores to Firestore and Cloud Storage
3. Gemini analyses the image with a strict JSON schema; Earth Engine returns aerosol index and NO2 for the same 5 km
4. Observations merge in BigQuery; hourly batch aggregates them into geohash cells with live meteorology
5. XGBoost on Cloud Run forecasts AQI twelve hours ahead; cells above 300 become alerts
6. Cloud Translation and Text-to-Speech produce localised voice and WhatsApp alerts to the responsible authority; the dashboard updates in real time

**Footer:** Event-driven throughout. Every stage scales to zero when idle.

**Speaker notes:** Walk the diagram left to right in thirty seconds. The two AI stages run concurrently, triggered by storage and Firestore events, which is why latency is a few seconds rather than a queue-processing delay.

---

## Slide 4 - AI Execution

**Title:** Deep Google AI integration, engineered for reliability

**Body:**

| Capability | Implementation |
| --- | --- |
| Multimodal vision | Gemini through Google AI Studio with a response schema of 17 typed fields: outdoor-scene flag, haze index, visibility, sky condition, smoke, dust, fog and open burning detection, vehicle, construction and industrial scores, pollution sources, AQI category and estimate, confidence, reasoning |
| Prompt engineering | Outdoor-scene gating, screenshot rejection, Indian context (stubble season, Diwali, construction dust), grounded AQI category definitions from CPCB |
| Rate-limit resilience | Exponential backoff with full jitter on HTTP 429 and 5xx, configurable model fallback chain on model retirement, idempotent reprocessing |
| Satellite fusion | Earth Engine Python API: Sentinel-5P AER_AI, NO2, CO, SO2 and MODIS MAIAC AOD, server-side reductions within a 5 km buffer |
| Forecasting | XGBoost regressor, 35 features, MAE 25.7 AQI points and R2 0.92 on validation, 45 percent lower error than persistence |
| Language | Cloud Translation and Text-to-Speech for authority alerts in English, Hindi, Bengali, Tamil, Telugu, Marathi, Gujarati, Kannada, Malayalam and Punjabi; citizen replies templated in English and Hindi with language preference stored per citizen |

**Footer:** Every AI call is typed, retried, logged and tested: 113 automated tests across the repository.

**Speaker notes:** Judges care about whether the AI is load-bearing or decorative. Here Gemini produces the primary features of the forecasting model and the citizen-facing reply; Earth Engine supplies the physical anchor; Translation and TTS are what make the output actionable for a district officer who may not read English.

---

## Slide 5 - India Scale

**Title:** Designed for 1.4 billion people and 28 states

**Body:**

- Ingestion channel: WhatsApp, used by more than 500 million Indians, works on entry-level phones and 2G networks
- Compute: Cloud Run and Cloud Functions scale horizontally from zero to thousands of concurrent requests with no capacity planning
- Data: BigQuery tables partitioned by day and clustered by geohash and city; ten years of national reports fit in terabytes, not clusters
- Prediction cost grows with active grid cells, not reports: one million reports per day still collapse into roughly 40,000 five-kilometre cells nationwide
- Alerts route by geohash coverage to any number of authorities, from ward officers to the Central Pollution Control Board
- Authority alerts in ten languages (English and nine Indian languages), citizen replies in English and Hindi today, both extensible by configuration

**Footer:** Throughput target: one million reports per day on the current architecture without redesign.

**Speaker notes:** Give the intuition for cell-based aggregation: whether a cell receives ten reports or ten thousand, it costs one prediction per hour. Mention that WhatsApp's read receipts and reply templates already handle delivery at national scale; VayuSetu never operates its own messaging infrastructure.

---

## Slide 6 - Impact

**Title:** What changes for citizens and authorities

**Body:**

For citizens:

- Immediate, understandable feedback in their language: estimated AQI category, visibility and likely sources
- A voice in the data: their neighbourhood appears on the official map within seconds
- Health guidance aligned with CPCB categories

For authorities:

- Twelve hours of warning before a severe episode, per five-kilometre cell
- Evidence-backed alerts with report counts, satellite context and dominant sources
- Action-ready messaging referencing Graded Response Action Plan measures
- A live dashboard with trends, source breakdowns and an auditable alert log

For researchers:

- Every observation and forecast lands in BigQuery with open schemas, enabling epidemiological and policy research

**Footer:** Pilot success metric: time from onset of a severe episode to first authority notification, from hours to under sixty minutes.

**Speaker notes:** Offer a concrete scenario: a Sunday evening in November, stubble smoke drifts over north Delhi, wind falls below one metre per second. Citizens in Rohini send twenty photographs between five and seven in the evening. By eight, the Delhi control room has received a Hindi voice call predicting an AQI of 430 by early morning and can order water sprinkling and school advisories before the morning commute.

---

## Slide 7 - Deployability

**Title:** One command to provision, three workflows to deploy

**Body:**

- `terraform apply` creates about 70 resources: APIs, buckets with lifecycle rules, Firestore with indexes and TTL, BigQuery dataset and schemas, Secret Manager, least-privilege service accounts, Cloud Run services, Cloud Scheduler and GitHub Workload Identity Federation
- GitHub Actions: `terraform.yml` (plan on pull request, apply on main), `backend-deploy.yml` (lint, tests, containers, functions, smoke tests), `frontend-deploy.yml` (Next.js static export to Firebase Hosting)
- No service account keys anywhere; deployments authenticate with OIDC
- Local parity: `docker compose up` starts the Firebase Emulator Suite, a Cloud Storage emulator, mock Twilio, mock Google AI Studio, both services and all four functions
- `generate_mock_data.py` seeds a realistic 48-hour episode for training, testing and demonstrations
- Comprehensive `.env.example`, README and runbooks

**Footer:** A municipality with a Google Cloud project and a Twilio account can be live in one afternoon.

**Speaker notes:** Emphasise the mock servers: developers and municipal IT teams can run the entire pipeline with no API keys and no cloud spend, which lowers the barrier to adoption and audit.

---

## Slide 8 - BRICS and Global South scalability

**Title:** Built for India, ready for Brazil, South Africa, Indonesia and beyond

**Body:**

- The three inputs are globally available: WhatsApp (most used messenger in Brazil, South Africa, Indonesia, Nigeria and Mexico), Sentinel-5P and MODIS (global daily coverage), Open-Meteo (global forecasts)
- Language is configuration: Cloud Translation and Text-to-Speech cover Portuguese, Spanish, Zulu, Afrikaans, Bahasa Indonesia, Arabic and dozens more
- AQI scale, alert thresholds, geohash precision and authority routing are parameters, not code
- Regional deployment: choose the closest Google Cloud region for Firestore and Cloud Run; BigQuery multi-region for analytics
- Same free-tier envelope applies in every Google Cloud region

**Footer:** Sao Paulo, Johannesburg, Jakarta and Lagos share Delhi's problem: dense populations, sparse monitors, ubiquitous WhatsApp.

**Speaker notes:** Point out that the model retrains on local data through the BigQuery-backed training CLI; the feature set (vision, satellite, meteorology, time) is region-agnostic, while the label source can be any local monitoring network.

---

## Slide 9 - Cost Analysis

**Title:** Zero-cost pilots, sub-lakh national scale

**Body:**

Monthly cost estimates (USD), architecture unchanged across tiers:

| Component | City pilot: 5,000 reports/day | State: 100,000 reports/day | National: 1,000,000 reports/day |
| --- | --- | --- | --- |
| Gemini (Google AI Studio free tier, then Flash pricing) | 0 | 45 | 450 |
| Cloud Run (gateway and prediction) | 0 | 6 | 60 |
| Cloud Functions (four functions) | 0 | 12 | 120 |
| Firestore | 0 | 15 | 150 |
| BigQuery (load jobs, partitioned queries) | 0 | 3 | 25 |
| Cloud Storage (Nearline at 30 days, delete at 90) | 0 | 8 | 80 |
| Earth Engine (non-commercial tier; commercial tier at scale) | 0 | 0 | 500 |
| Translation and Text-to-Speech (Standard voices) | 0 | 0 | 5 |
| Twilio WhatsApp and voice (authority alerts only, 20 to 500 per day) | 0 | 40 | 400 |
| **Total** | **0** | **about 130** | **about 1,800** |

- Zero-cost pilot: every service stays inside permanent free allowances (Cloud Run 2 million requests, Functions 2 million invocations, Firestore 50k reads per day, BigQuery 1 TiB queries, Translation 500k characters, TTS 4 million characters)
- Design choices that keep it there: image downscaling, single Gemini call per report, batch loads instead of streaming inserts, cell-level prediction, Standard voices, scale-to-zero everywhere
- Replacing Vertex AI AutoML with a custom XGBoost container removed the largest fixed cost of the original design (endpoint hours) entirely
- National scale at about 1,800 USD per month is roughly 1.5 lakh rupees, less than the cost of a single reference-grade monitoring station

**Footer:** A billing account must be linked for Cloud Run and Functions, but a pilot deployment incurs no charges.

**Speaker notes:** Be precise about assumptions: 1 image per report, 1024 px downscaled, hourly batch with 40,000 cells nationally, alerts capped by the three-hour cooldown. Note that the Earth Engine line at national scale assumes a commercial licence; a government or academic partner keeps it at zero.

---

## Slide 10 - The ask and the road ahead

**Title:** Help us bridge citizens and clean air

**Body:**

Next ninety days:

- Pilot with one municipal corporation in Delhi NCR during the winter smog season
- Join CPCB station data in BigQuery and retrain the model on real labels weekly
- WhatsApp Business verification to remove sandbox opt-in
- Ward-level authority routing and escalation ladders

What we need:

- Introductions to two municipal control rooms and one state pollution control board
- Google Cloud credits for the pilot's Gemini quota beyond the free tier
- Earth Engine institutional access for sustained non-commercial use

**Closing line:** Five hundred million cameras are already pointed at the sky. VayuSetu turns them into a warning system.

**Footer:** github.com/samudragupto/VayuSetu | Apache 2.0

**Speaker notes:** End on the closing line, pause, then invite questions. Have the dashboard open on the second screen for the question period.
