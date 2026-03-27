from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class AnalysisReport:
    grafana_url: str
    dashboard_uid: str
    dashboard_title: str | None
    generated_at_utc: str
    markdown: str

    def to_markdown(self) -> str:
        header = (
            "# Grafana dashboard AI recommendations\n\n"
            f"- Grafana: {self.grafana_url}\n"
            f"- Dashboard UID: {self.dashboard_uid}\n"
        )
        if self.dashboard_title:
            header += f"- Dashboard title: {self.dashboard_title}\n"
        header += f"- Generated at (UTC): {self.generated_at_utc}\n\n---\n\n"
        return header + self.markdown.strip() + "\n"


def build_report(*, grafana_url: str, dashboard_uid: str, dashboard_payload: dict[str, Any], markdown: str) -> AnalysisReport:
    dashboard = dashboard_payload.get("dashboard") if isinstance(dashboard_payload, dict) else {}
    title = dashboard.get("title") if isinstance(dashboard, dict) else None
    generated_at_utc = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    return AnalysisReport(
        grafana_url=grafana_url,
        dashboard_uid=dashboard_uid,
        dashboard_title=title if isinstance(title, str) else None,
        generated_at_utc=generated_at_utc,
        markdown=markdown,
    )
