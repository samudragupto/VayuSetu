# VayuSetu - Four-Minute Demo Script

Total running time: 4:00. Timings are cumulative. One presenter speaks; a second person (or the presenter with a second screen) drives the terminal and browser. Rehearse until the spoken track finishes within two seconds of each cue.

## Preparation checklist (complete 15 minutes before the slot)

1. `docker compose up -d` from the repository root and confirm `http://localhost:4000` (Emulator UI), `http://localhost:3000` (dashboard), `http://localhost:4010/_admin/log` (mock Twilio log) and `http://localhost:8090/healthz` (prediction service) respond.
2. Seed the escalating episode so the map and charts are populated before the audience sees them:

   ```bash
   source .venv/bin/activate
   export FIRESTORE_EMULATOR_HOST=localhost:8080
   python scripts/generate_mock_data.py --reports 500 --hours 48 --quiet-hours 3 --clear
   ```

   `--quiet-hours 3` stops the simulated batch runs three hours before the present and records their alerts as already sent, so the live batch run in section 4 produces fresh hotspots whose alerts are not suppressed by the three-hour cooldown.

3. Sign in to the dashboard with an account on the administrator domain (the Auth emulator lets you create `ops@example.gov.in` from the Google sign-in popup) and leave it on the **Overview** page with the last 48 hours selected; the map centres on Delhi NCR.
4. Clear the mock Twilio log so the alert section starts empty: `curl -X DELETE localhost:4010/_admin/log`.
5. Prepare a terminal with the three commands from section 3 pasted into a scratch file, and open the Emulator UI on the `citizen_reports` collection sorted by `createdAt` descending.
6. Open `docs/PITCH_DECK.md` slide 1 on the presentation display. Mute notifications.

If the live stack is unavailable, fall back to a screen recording made from this script during rehearsal, and to the JSON snapshot produced by `scripts/generate_mock_data.py --dry-run --json-out demo.json` for the data walkthrough.

---

## 0:00 - 0:35  The problem (slide 1 and slide 2)

**Show:** Slide 1 (title), then slide 2 (problem).

**Say:**

> Every winter, Delhi's air quality index crosses 400, and the story repeats in Kanpur, Lucknow, Patna and Mumbai. India has around 900 continuous monitoring stations for 1.4 billion people. Most districts have none. Authorities learn about a severe episode from the same news bulletin that citizens do, hours after the pollution has already settled over homes and schools.
>
> Yet there are more than 500 million WhatsApp users in India, and every one of them carries a camera. VayuSetu turns those cameras into a hyper-local sensor network, fuses the pictures with satellite data from Google Earth Engine, and forecasts the next twelve hours so that a municipal officer receives a phone call before the spike, not after.

**Transition cue:** switch to the browser at 0:35.

## 0:35 - 1:20  The WhatsApp flow

**Show:** Terminal on the left, mock Twilio log on the right (`http://localhost:4010/_admin/log`).

**Do:** run the location share, then the photo message.

```bash
curl -s -X POST localhost:4010/simulate/inbound -H 'content-type: application/json' \
  -d '{"from":"+919876543210","latitude":28.6304,"longitude":77.2177,"profileName":"Asha"}' | jq .reply

curl -s -X POST localhost:4010/simulate/inbound -H 'content-type: application/json' \
  -d '{"from":"+919876543210","media":"hazy_delhi.jpg","body":"Very smoky near ITO this morning"}' | jq .reply
```

**Say (while the commands run):**

> A citizen opens WhatsApp, shares her location once, and sends a photo of the sky with a short caption. No app to install, no account to create, and it works on a two-thousand-rupee phone over 2G.
>
> The message reaches our Node.js gateway on Cloud Run. It verifies Twilio's signature, pseudonymises the phone number with an HMAC so raw numbers never enter the analytics layer, writes the report to Firestore, uploads the image to Cloud Storage and replies within about two hundred milliseconds. Notice the acknowledgement is already in Hindi, because the citizen's language is inferred from the number and can be changed with a single word.

**Point to:** the TwiML reply printed by `jq`, then the `received` document appearing at the top of `citizen_reports` in the Emulator UI.

## 1:20 - 2:20  AI extraction: Gemini and Earth Engine

**Show:** Emulator UI, the new report document. Expand `geminiAnalysis` and `satelliteMetrics` as they appear (the vision function completes within a few seconds against the mock; against Google AI Studio it takes four to eight seconds).

**Say:**

> Two things now happen in parallel, both triggered by events, both costing nothing while idle.
>
> First, the Cloud Storage finalize event starts a Python function that sends the image to Gemini. We do not ask for prose. We send a strict JSON schema and receive a structured record: a haze index of 0.78, visibility around two kilometres, sky condition "smoky haze", open burning detected, vehicle density seven out of ten, and an estimated AQI category of "poor" with a confidence score. The prompt is engineered to refuse indoor scenes and screenshots, and the call is wrapped in exponential backoff so that free-tier rate limits slow us down rather than lose reports.
>
> Second, the Firestore create event starts another function that queries Google Earth Engine for Sentinel-5P aerosol index and tropospheric nitrogen dioxide within five kilometres of the citizen over the last three days, plus MODIS aerosol optical depth. That is the physical context the photo cannot provide on its own.
>
> Both streams land in BigQuery as partitioned tables, joined into a single fused view.

**Point to:** `estimatedAqi`, `pollutionSources`, `satelliteMetrics.aerAi`, `satelliteMetrics.no2TroposphericMolM2`.

**Then switch to the dashboard (2:05).** Show the **Overview** map, "Predicted hotspots and live reports": hotspots as coloured cells, reports as markers; click the newest marker to display the Gemini summary card.

> Every analysed report appears on the authority dashboard in real time through Firestore listeners, on Google Maps, with the Gemini findings on the card.

## 2:20 - 3:05  Prediction: from observations to a 12-hour forecast

**Show:** Dashboard **Overview**, chart "Observed versus predicted AQI (IST)" for the last 48 hours, while the batch job runs.

**Do:**

```bash
curl -s -X POST localhost:8085 -H 'content-type: application/json' \
  -d '{"trigger":"demo","lookback_hours":6}' | jq '{cells, hotspots_written, alerts_pending}'
```

**Say:**

> Every hour, Cloud Scheduler invokes the batch function. It aggregates the fused observations into five-kilometre geohash cells, pulls wind, humidity and boundary layer height from Open-Meteo, and calls our prediction service on Cloud Run: a custom XGBoost regressor with thirty-five features, served from a two-megabyte model file in a container that scales to zero.
>
> The chart shows what the seeded episode looks like: a stable "moderate" morning two days ago, and a steady climb as stubble smoke and calm winds trap emissions over the capital. The model projects the trend forward twelve hours. Cells whose forecast crosses 300, the CPCB "very poor" boundary, are written to Firestore with an alert status of pending.

**Point to:** the new hotspot cells turning red or maroon on the map and the table "Forecast hotspots ranked by predicted AQI".

## 3:05 - 3:45  Multilingual alerts to authorities

**Show:** Mock Twilio log (`http://localhost:4010/_admin/log`), refreshed; new `calls` and `messages` entries appear within a few seconds of the batch run.

**Say:**

> A pending hotspot triggers the last function. It claims the hotspot in a transaction so an alert is sent exactly once, looks up which authorities cover that cell, and composes the message: predicted AQI, confidence, dominant sources, number of citizen reports, and recommended actions from the Graded Response Action Plan.
>
> The Delhi control room is configured for Hindi, Punjab's crop-residue task force for Punjabi, Mumbai for Marathi, and the central board for English. Cloud Translation localises the text, Cloud Text-to-Speech produces the audio, and Twilio places a voice call and sends a WhatsApp message. Here is the Hindi call script and the audio file the officer will hear, and here is the same alert in English for CPCB. Every dispatch is written to the alert log with its Twilio SID, and a three-hour cooldown per cell prevents alert fatigue.

**Do (optional if time allows):** open the **Alerts** page of the dashboard to show the log entries with their language and channel.

## 3:45 - 4:00  Close (slide 9 and slide 10)

**Show:** Slide 9 (cost analysis) briefly, then slide 10 (call to action).

**Say:**

> Everything you saw runs inside Google Cloud's free tier: Cloud Run and Cloud Functions scale to zero, Firestore, BigQuery, Translation and Text-to-Speech stay within their permanent free allowances, Gemini is called through Google AI Studio, and Earth Engine is used under the non-commercial licence. A city pilot costs nothing; a national deployment costs less than one lakh rupees a month.
>
> One terraform apply, three GitHub Actions workflows, and any municipality in India, or in any BRICS country with WhatsApp, can have a predictive air quality network next week. VayuSetu: the bridge between citizens and clean air.

---

## Timing table

| Segment | Start | Duration | Screen |
| --- | --- | --- | --- |
| Problem | 0:00 | 0:35 | Slides 1-2 |
| WhatsApp flow | 0:35 | 0:45 | Terminal, mock Twilio log, Emulator UI |
| AI extraction | 1:20 | 1:00 | Emulator UI report document, dashboard map |
| Prediction | 2:20 | 0:45 | Dashboard overview chart and map, terminal |
| Multilingual alerts | 3:05 | 0:40 | Mock Twilio log, dashboard alerts page |
| Close | 3:45 | 0:15 | Slides 9-10 |

## Recovery notes

- If the Gemini mock returns a 429 during the demo (it simulates rate limits at a configurable rate), say: "That is a simulated free-tier rate limit; the function is backing off and will retry." The report will complete on the next attempt. Set `MOCK_RATE_LIMIT_PROBABILITY=0` in `.env` before the demo to disable this behaviour.
- If the batch job reports zero pending alerts, or the alert function logs `suppressed_cooldown`, re-seed with `python scripts/generate_mock_data.py --reports 500 --hours 48 --quiet-hours 3 --clear` (which resets the `alert_state` cooldown records) or lower `ALERT_AQI_THRESHOLD` in `.env` and restart the `fn-batch` and `fn-alerts` services.
- If the dashboard sign-in fails in the Auth emulator, create a user from the Emulator UI Authentication tab; any verified address on `example.gov.in` is accepted by the security rules.
- Keep the Twilio and Google AI Studio keys out of the frame at all times; the local stack does not need them.
