from __future__ import annotations

import html

from typing import Any

from .ai_client import AIError, build_ai_client
from .analyzer import analyze_dashboard
from .api_models import AnalyzePayloadRequest
from .config import Settings
from .grafana_client import GrafanaClient, GrafanaError


def create_app(settings: Settings):
    try:
        from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
        from fastapi.responses import HTMLResponse, PlainTextResponse
    except Exception as exc:  # pragma: no cover
        raise RuntimeError('FastAPI not installed. Install with: pip install -e ".[server]"') from exc

    app = FastAPI(title="Grafana AI", version="0.1.0")

    # Optional CORS for browser-based Grafana plugins calling this service
    if settings.cors_allow_origins:
        from fastapi.middleware.cors import CORSMiddleware

        origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
        if origins:
            app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    grafana = GrafanaClient(
        base_url=settings.grafana_url,
        api_token=settings.grafana_api_token.get_secret_value(),
        timeout_s=settings.grafana_timeout_s,
    )
    ai = build_ai_client(
        provider=settings.ai_provider,
        openai_api_key=settings.openai_api_key.get_secret_value() if settings.openai_api_key else None,
        openai_model=settings.openai_model,
        ollama_url=settings.ollama_url,
        ollama_model=settings.ollama_model,
        ollama_timeout_s=settings.ollama_timeout_s,
        ollama_num_predict=settings.ollama_num_predict,
    )

    def require_service_auth(
        x_api_key: str | None = Header(None),
        token: str | None = Query(None),
    ) -> None:
        """Allow either header-based auth or query-token auth.

        - `SERVICE_API_KEY` -> header `X-API-Key`
        - `SERVICE_EMBED_TOKEN` -> query `?token=`

        This is useful because iframes can't send custom headers.
        """

        if settings.service_api_key is None and settings.service_embed_token is None:
            return

        if settings.service_api_key is not None and x_api_key == settings.service_api_key.get_secret_value():
            return

        if settings.service_embed_token is not None and token == settings.service_embed_token.get_secret_value():
            return

        raise HTTPException(status_code=401, detail="Missing/invalid X-API-Key")

    @app.get("/")
    def root() -> dict[str, str]:
        return {"service": "grafana-ai", "status": "ok"}

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/analyze_payload")
    def analyze_payload(req: AnalyzePayloadRequest = Body(...), _: None = Depends(require_service_auth)) -> dict[str, Any]:
        """LLM analysis of an already-built digest + time series summary.

        Intended for a Grafana frontend plugin: it can query /api/ds/query using the user's grafana_session,
        then post the summarized series here for the LLM to write recommendations.
        """

        try:
            from .prompt_compact import compact_digest_for_llm, compact_timeseries_summary_for_llm

            md = ai.analyze_dashboard(
                dashboard_digest=compact_digest_for_llm(req.dashboard_digest),
                timeseries_summary=compact_timeseries_summary_for_llm(req.timeseries_summary),
            )
        except AIError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {"report_markdown": md}

    @app.get("/debug/panel/{uid}/{panel_id}")
    def debug_panel(
        uid: str,
        panel_id: int,
        from_time: str | None = Query(None, alias="from"),
        to_time: str | None = Query(None, alias="to"),
        _: None = Depends(require_service_auth),
    ) -> dict[str, Any]:
        """Return the raw Grafana /api/ds/query response for a single panel (for troubleshooting parsing)."""
        payload = grafana.get_dashboard_by_uid(uid)
        dashboard = payload.get("dashboard") if isinstance(payload, dict) else None
        panels = (dashboard or {}).get("panels") if isinstance(dashboard, dict) else None
        if not isinstance(panels, list):
            raise HTTPException(status_code=400, detail="No panels")
        panel = next((p for p in panels if isinstance(p, dict) and p.get("id") == panel_id), None)
        if not isinstance(panel, dict):
            raise HTTPException(status_code=404, detail=f"Panel id {panel_id} not found")

        from .time_range import resolve_time_range
        from .datasource_query import build_panel_queries
        from .dataframe import parse_grafana_query_response

        tr = resolve_time_range(from_expr=from_time, to_expr=to_time)
        qs = build_panel_queries(panel)
        raw = grafana.query_datasource(queries=[q.model for q in qs], from_ms=tr.from_ms, to_ms=tr.to_ms)
        parsed = parse_grafana_query_response(raw)

        return {
            "panel": {"id": panel_id, "title": panel.get("title"), "type": panel.get("type")},
            "range": {"from_ms": tr.from_ms, "to_ms": tr.to_ms},
            "raw": raw,
            "parsed_series": [{"name": s.name, "points": len(s.points)} for s in parsed],
        }

    def _run(
        uid: str,
        *,
        with_timeseries: bool,
        from_time: str | None,
        to_time: str | None,
        timeseries_max_panels: int | None,
        anomaly_z: float | None,
    ):
        enable_timeseries = with_timeseries or settings.enable_timeseries_query
        return analyze_dashboard(
            grafana_client=grafana,
            ai_client=ai,
            dashboard_uid=uid,
            max_panels=settings.max_panels,
            max_targets_per_panel=settings.max_targets_per_panel,
            enable_timeseries=enable_timeseries,
            from_expr=from_time,
            to_expr=to_time,
            timeseries_max_panels=(
                timeseries_max_panels if timeseries_max_panels is not None else settings.timeseries_max_panels
            ),
            anomaly_z_threshold=anomaly_z if anomaly_z is not None else settings.anomaly_z_threshold,
        )

    @app.get("/analyze/{uid}")
    def analyze(
        uid: str,
        include_digest: bool = False,
        with_timeseries: bool = Query(False, description="Query datasource time series via Grafana"),
        from_time: str | None = Query(None, alias="from", description="Start time: now-24h, ISO, or epoch ms"),
        to_time: str | None = Query(None, alias="to", description="End time: now, ISO, or epoch ms"),
        timeseries_max_panels: int | None = Query(None, description="Max panels to query (0 = all)"),
        anomaly_z: float | None = Query(None, description="Robust z-score threshold"),
        _: None = Depends(require_service_auth),
    ) -> dict[str, Any]:
        try:
            report, digest, timeseries_summary = _run(
                uid,
                with_timeseries=with_timeseries,
                from_time=from_time,
                to_time=to_time,
                timeseries_max_panels=timeseries_max_panels,
                anomaly_z=anomaly_z,
            )
        except (GrafanaError, AIError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        out: dict[str, Any] = {
            "uid": uid,
            "grafana_url": grafana.base_url,
            "generated_at_utc": report.generated_at_utc,
            "dashboard_title": report.dashboard_title,
            "report_markdown": report.to_markdown(),
            "timeseries_enabled": with_timeseries or settings.enable_timeseries_query,
        }
        if include_digest:
            out["digest"] = digest
        if timeseries_summary is not None:
            out["timeseries_summary"] = timeseries_summary
        return out

    @app.get("/analyze/{uid}/panel")
    def analyze_panel(
        uid: str,
        with_timeseries: bool = Query(False),
        from_time: str | None = Query(None, alias="from"),
        to_time: str | None = Query(None, alias="to"),
        _: None = Depends(require_service_auth),
    ) -> dict[str, Any]:
        try:
            report, _, timeseries_summary = _run(
                uid,
                with_timeseries=with_timeseries,
                from_time=from_time,
                to_time=to_time,
                timeseries_max_panels=None,
                anomaly_z=None,
            )
        except (GrafanaError, AIError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "uid": uid,
            "generated_at_utc": report.generated_at_utc,
            "dashboard_title": report.dashboard_title,
            "text_markdown": report.to_markdown(),
            "timeseries_summary": timeseries_summary,
        }

    @app.get("/analyze/{uid}/panel_rows")
    def analyze_panel_rows(
        uid: str,
        with_timeseries: bool = Query(False),
        from_time: str | None = Query(None, alias="from"),
        to_time: str | None = Query(None, alias="to"),
        _: None = Depends(require_service_auth),
    ) -> list[dict[str, Any]]:
        try:
            report, _, _ = _run(
                uid,
                with_timeseries=with_timeseries,
                from_time=from_time,
                to_time=to_time,
                timeseries_max_panels=None,
                anomaly_z=None,
            )
        except (GrafanaError, AIError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return [
            {
                "uid": uid,
                "generated_at_utc": report.generated_at_utc,
                "dashboard_title": report.dashboard_title,
                "text_markdown": report.to_markdown(),
            }
        ]

    @app.get("/analyze/{uid}/markdown", response_class=PlainTextResponse)
    def analyze_markdown(
        uid: str,
        with_timeseries: bool = Query(False),
        from_time: str | None = Query(None, alias="from"),
        to_time: str | None = Query(None, alias="to"),
        _: None = Depends(require_service_auth),
    ) -> str:
        try:
            report, _, _ = _run(
                uid,
                with_timeseries=with_timeseries,
                from_time=from_time,
                to_time=to_time,
                timeseries_max_panels=None,
                anomaly_z=None,
            )
        except (GrafanaError, AIError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return report.to_markdown()

    @app.get("/analyze/{uid}/embed", response_class=HTMLResponse)
    def analyze_embed(
        uid: str,
        with_timeseries: bool = Query(False),
        from_time: str | None = Query(None, alias="from"),
        to_time: str | None = Query(None, alias="to"),
        _: None = Depends(require_service_auth),
    ) -> str:
        try:
            report, _, _ = _run(
                uid,
                with_timeseries=with_timeseries,
                from_time=from_time,
                to_time=to_time,
                timeseries_max_panels=None,
                anomaly_z=None,
            )
        except (GrafanaError, AIError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        md = html.escape(report.to_markdown())
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<style>body{font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;margin:0;padding:12px;}"
            "pre{white-space:pre-wrap;word-break:break-word;font-size:12px;line-height:1.35;margin:0;}</style>"
            "</head><body><pre>"
            + md
            + "</pre></body></html>"
        )

    return app



