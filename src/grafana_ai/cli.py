from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from .ai_client import AIError, build_ai_client
from .analyzer import analyze_dashboard
from .config import load_settings
from .grafana_client import GrafanaClient, GrafanaError


app = typer.Typer(add_completion=False, help="Analyze Grafana dashboards and generate AI recommendations")
console = Console()


@app.command()
def analyze(
    uid: str | None = typer.Option(None, "--uid", help="Grafana dashboard UID"),
    out: Path | None = typer.Option(None, "--out", help="Write Markdown report to this path"),
    digest_out: Path | None = typer.Option(None, "--digest-out", help="Write dashboard digest JSON to this path"),
    with_timeseries: bool = typer.Option(
        False,
        "--with-timeseries",
        help="Query datasource time series via Grafana and run anomaly detection",
    ),
    from_time: str | None = typer.Option(None, "--from", help="Time range start (e.g., now-24h, ISO, or epoch ms)"),
    to_time: str | None = typer.Option(None, "--to", help="Time range end (e.g., now, ISO, or epoch ms)"),
    timeseries_max_panels: int | None = typer.Option(
        None,
        "--timeseries-max-panels",
        help="Max panels to query for time series (0 = all)",
    ),
    anomaly_z_threshold: float | None = typer.Option(None, "--anomaly-z", help="Robust z-score threshold"),
) -> None:
    settings = load_settings()
    dashboard_uid = uid or settings.grafana_dashboard_uid
    if not dashboard_uid:
        raise typer.BadParameter("Provide --uid or set GRAFANA_DASHBOARD_UID")

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

    enable_timeseries = with_timeseries or settings.enable_timeseries_query

    try:
        report, digest, timeseries_summary = analyze_dashboard(
            grafana_client=grafana,
            ai_client=ai,
            dashboard_uid=dashboard_uid,
            max_panels=settings.max_panels,
            max_targets_per_panel=settings.max_targets_per_panel,
            enable_timeseries=enable_timeseries,
            from_expr=from_time,
            to_expr=to_time,
            timeseries_max_panels=timeseries_max_panels if timeseries_max_panels is not None else settings.timeseries_max_panels,
            anomaly_z_threshold=anomaly_z_threshold if anomaly_z_threshold is not None else settings.anomaly_z_threshold,
        )
    except (GrafanaError, AIError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    report_md = report.to_markdown()

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report_md, encoding="utf-8")
        console.print(f"Wrote report: {out}")
    else:
        console.print(report_md)

    if digest_out:
        digest_out.parent.mkdir(parents=True, exist_ok=True)
        digest_out.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"Wrote digest: {digest_out}")

    if timeseries_summary is not None:
        console.print(f"Queried time series panels: {timeseries_summary.get('panels_analyzed')}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8088, "--port"),
) -> None:
    try:
        import uvicorn  # type: ignore
    except Exception as exc:  # pragma: no cover
        console.print("[red]Missing server dependencies.[/red] Install with: pip install -e \".[server]\"")
        raise typer.Exit(1) from exc

    settings = load_settings()
    from .server import create_app

    api = create_app(settings)
    uvicorn.run(api, host=host, port=port, log_level="info")


if __name__ == "__main__":
    app()


