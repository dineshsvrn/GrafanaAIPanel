from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests


class GrafanaError(RuntimeError):
    pass


@dataclass(frozen=True)
class GrafanaClient:
    base_url: str
    api_token: str
    timeout_s: float = 30.0

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}" + path

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def get_dashboard_by_uid(self, uid: str) -> dict[str, Any]:
        try:
            resp = requests.get(
                self._url(f"/api/dashboards/uid/{uid}"),
                headers=self._headers(),
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            raise GrafanaError(f"Failed to reach Grafana at {self.base_url!r}: {exc}") from exc

        if resp.status_code >= 400:
            body_preview = resp.text[:1000]
            raise GrafanaError(
                f"Grafana API error GET /api/dashboards/uid/{uid}: HTTP {resp.status_code}: {body_preview}"
            )

        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise GrafanaError(f"Grafana returned non-JSON for dashboard uid={uid}: {exc}") from exc

        if not isinstance(data, dict) or "dashboard" not in data:
            raise GrafanaError("Unexpected Grafana response shape; expected object with 'dashboard'.")

        return data

    def query_datasource(self, *, queries: list[dict[str, Any]], from_ms: int, to_ms: int) -> dict[str, Any]:
        span_ms = max(1, int(to_ms) - int(from_ms))

        normalized: list[dict[str, Any]] = []
        for q in queries:
            if not isinstance(q, dict):
                continue
            q2 = dict(q)

            mdp = q2.get("maxDataPoints")
            if not isinstance(mdp, int) or mdp <= 0:
                mdp = 800
                q2["maxDataPoints"] = mdp

            if not isinstance(q2.get("intervalMs"), int):
                q2["intervalMs"] = max(1000, int(span_ms / mdp))

            normalized.append(q2)

        body = {
            "queries": normalized,
            "from": str(int(from_ms)),
            "to": str(int(to_ms)),
        }

        try:
            resp = requests.post(
                self._url("/api/ds/query"),
                headers=self._headers(),
                data=json.dumps(body),
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            raise GrafanaError(f"Failed to query Grafana datasource via /api/ds/query: {exc}") from exc

        if resp.status_code >= 400:
            body_preview = resp.text[:2000]
            raise GrafanaError(f"Grafana API error POST /api/ds/query: HTTP {resp.status_code}: {body_preview}")

        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise GrafanaError(f"Grafana returned non-JSON for /api/ds/query: {exc}") from exc

        if not isinstance(data, dict):
            raise GrafanaError("Unexpected /api/ds/query response shape; expected JSON object.")

        return data
