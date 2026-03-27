<<<<<<< HEAD
# GrafanaAIPanel
An AI-powered Grafana panel that transforms dashboards from passive visualizations into intelligent systems by automatically analysing metrics and delivering actionable insights and recommendations.
=======
﻿# Grafana AI Recommendations (Prototype)

Fetch a Grafana dashboard definition via the Grafana HTTP API, summarize it, and send it to an LLM to get actionable recommendations (dashboard hygiene, alerting gaps, capacity planning, and Oracle-focused suggestions).

## What this is (and isnâ€™t)

- âœ… An end-to-end prototype you can run as a CLI or a small HTTP service.
- âœ… Works even if your metrics come from Oracle Enterprise Manager (OEM) as long as Grafana is already displaying them.
- âŒ It does **not** execute panel queries to pull raw time series (Grafanaâ€™s `/api/ds/query` differs per datasource and panel type). Instead, it analyzes the dashboard definition (panels, thresholds, units, variables, etc.). You can extend it later to fetch panel renders or datasource queries.

## Setup

1) Create a virtualenv and install:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[openai,server]"
```

2) Create `.env` (see `.env.example`):

```text
GRAFANA_URL=https://grafana.example.com
GRAFANA_API_TOKEN=YOUR_TOKEN
GRAFANA_DASHBOARD_UID=abcdEfGhI
AI_PROVIDER=openai
OPENAI_API_KEY=YOUR_OPENAI_KEY
OPENAI_MODEL=YOUR_MODEL_NAME
```

## Run (CLI)

```powershell
python -m grafana_ai analyze --uid abcdEfGhI --out report.md
```

If you omit `--uid`, it reads `GRAFANA_DASHBOARD_UID`.

## Run (HTTP service)

```powershell
python -m grafana_ai serve --host 127.0.0.1 --port 8088
```

Then call:

```powershell
Invoke-RestMethod http://127.0.0.1:8088/analyze/abcdEfGhI
```

## Next steps you can ask me to implement

- Pull dashboard/panel screenshots via Grafana render API and use a vision-capable model.
- Add datasource-specific query execution (Prometheus, Loki, InfluxDB, etc.).
- Persist reports, trend changes over time, and push summaries to Slack/Teams.


## Time series anomaly detection

This prototype can optionally query panel time series through Grafana (server-side) using POST /api/ds/query and run robust z-score anomaly detection.

Example:

`powershell
python -m grafana_ai analyze --uid abcdEfGhI --with-timeseries --from now-24h --to now --out report.md
`

Notes:
- This depends on the datasource plugin supporting backend queries via Grafana.
- Anomaly detection here is generic (robust z-score); tune thresholds per metric and validate against known incidents.


## Display the AI output in Grafana

Yesâ€”Grafana can show the AI report as a panel by querying this service as an HTTP/JSON datasource.

Typical approach (Grafana OSS):
- Install a JSON-capable datasource plugin (commonly *Infinity* or *JSON API*).
- Point it at this service (e.g., http://ai-service:8088).
- Create a panel that queries GET /analyze/<uid>/panel (JSON) or GET /analyze/<uid>/markdown (plain text).
- Use a panel that can render Markdown (plugin-dependent); otherwise use a Table panel to show the text field.

Service endpoint for panels:
- GET /analyze/<uid>/panel returns JSON including 	ext_markdown.

Security:
- If you set SERVICE_API_KEY in .env, Grafana must send header X-API-Key: <value> when calling the service.


## Local LLM (Llama3 via Ollama)

1) Install Ollama and pull the model:

`powershell
ollama pull llama3
`

2) Set env:

`	ext
AI_PROVIDER=ollama
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3
`

## Grafana JSON API plugin panel

- Create a JSON API datasource pointing to this service base URL (for example http://ai-service:8088).
- Create a Table panel (or any panel that can show string fields) and query:
  - Path: /analyze/<uid>/panel_rows
- Select the 	ext_markdown field to display.

If you set SERVICE_API_KEY, configure the datasource to send header X-API-Key.


## Grafana built-in Text panel

Grafana’s built-in Text panel is static (it does not execute datasource queries). To show the AI output there, embed the service endpoint in an iframe.

1) Create a Text panel → Mode: HTML
2) Set content to:

```html
<iframe src="http://<ai-service>:8088/analyze/<uid>/embed" style="width:100%;height:100%;border:0;"></iframe>
```

Optional security:
- Set `SERVICE_EMBED_TOKEN` in `.env` and use:

```html
<iframe src="http://<ai-service>:8088/analyze/<uid>/embed?token=<token>" style="width:100%;height:100%;border:0;"></iframe>
```

If the iframe is blocked, your Grafana Content-Security-Policy may need to allow the service host in `frame-src`.

## JSON API datasource plugin notes

There are two commonly-used "JSON API" plugins:

- `simpod-json-datasource` (often shows the data source name as "JSON API"). It expects these endpoints:
  - `GET /` (Test connection)
  - `POST /metrics`
  - `POST /query`
  This service now implements all three.

- `marcusolsson-json-datasource` (Grafana JSON API). It lets you call arbitrary endpoints like `/analyze/<uid>/panel_rows`.

### Ollama timeouts

If you see `Read timed out` from Ollama, either the first generation is slow (CPU) or the prompt is large.

- Increase timeout: set `OLLAMA_TIMEOUT_S=600`
- Limit output tokens: set `OLLAMA_NUM_PREDICT=400`
- Keep `ENABLE_TIMESERIES_QUERY=false` until basic output works

## OEM plugin: getting real time series data

Some datasource plugins (including some OEM/EMCC plugins) only allow querying when a user is logged in (requires `grafana_session`). In that case, backend services calling Grafana with only an API token will fail to run `/api/ds/query`.

Recommended approach:
- Build a Grafana frontend panel/app plugin.
- The plugin runs in the user session, queries `/api/ds/query` successfully, summarizes the series (min/max/mean/delta/anomalies), then calls this service endpoint to produce the written recommendation:
  - `POST /analyze_payload` (send `dashboard_digest` + `timeseries_summary`)

Auth:
- `SERVICE_API_KEY` (header `X-API-Key`) or `SERVICE_EMBED_TOKEN` (query `?token=`)
>>>>>>> 3b9ad3e (Initial commit - Grafana AI Panel with insights and recommendations)
