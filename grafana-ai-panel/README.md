# Grafana AI Recommendations Panel

This panel plugin runs inside the Grafana dashboard (in the user session), so it can query datasource time series via `POST /api/ds/query` even when a datasource plugin requires `grafana_session`.

It then calls your AI service (`POST /analyze_payload`) to get a Markdown report and renders it inside the panel.

## Prereqs

- Node.js **20 LTS** (recommended)
- Internet access to download npm dependencies

## Build (recommended tooling)

Grafana’s current recommended tooling is **Plugin Tools** via `@grafana/create-plugin`.

1) Create a fresh plugin scaffold:

```bash
npx @grafana/create-plugin@latest
```

Choose:
- Plugin type: **Panel**
- (any name)

2) Copy this repo’s implementation into the scaffold:

```powershell
# From this repo
pwsh -File .\copy-src-into-plugin.ps1 -TargetDir C:\path\to\your\new-plugin
```

3) Build using the scaffold’s scripts:

```bash
cd C:\path\to\your\new-plugin
npm install
npm run build
```

## Install in Grafana

- Copy the built plugin folder (the scaffold’s `dist/` output) into `/var/lib/grafana/plugins/`.
- Allow unsigned plugin id:
  - `GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS=dragonsage-grafana-ai-panel`

## Panel configuration

- AI service URL: `http://<ai-service>:8088`
- Auth (either):
  - `X-API-Key` (set `SERVICE_API_KEY` on the service), or
  - `?token=` (set `SERVICE_EMBED_TOKEN` on the service)

Notes:
- If your AI service is on a different host/port than Grafana, it must allow CORS for the Grafana origin (`CORS_ALLOW_ORIGINS`).
