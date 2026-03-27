from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import requests


class AIError(RuntimeError):
    pass


class AIClient(Protocol):
    def analyze_dashboard(self, *, dashboard_digest: dict[str, Any], timeseries_summary: dict[str, Any] | None = None) -> str: ...


def _system_prompt() -> str:
    return (
        "You are an expert SRE + Oracle database performance engineer. "
        "You analyze Grafana dashboards and monitoring signals and produce practical, prioritized recommendations. "
        "Be specific and actionable; avoid generic advice. "
        "Only make factual claims when they are supported by the provided dashboard digest or time-series summary. "
        "If numeric evidence is present (last/first/min/max/mean/peak/pct_change), you MUST cite it. "
        "Do not downplay potential incidents without a baseline/threshold."
    )


def _iso_ms(ms: Any) -> str | None:
    try:
        if ms is None:
            return None
        v = int(ms)
        return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _to_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except Exception:
        return None


def _derive_signals(timeseries_summary: dict[str, Any] | None, *, max_signals: int = 15) -> list[dict[str, Any]]:
    if not isinstance(timeseries_summary, dict):
        return []

    panels = timeseries_summary.get("panels")
    if not isinstance(panels, list):
        return []

    signals: list[dict[str, Any]] = []

    def add(sig: dict[str, Any], score: float) -> None:
        sig["_score"] = score
        signals.append(sig)

    for p in panels:
        if not isinstance(p, dict):
            continue

        panel_title = p.get("panel_title")
        if not isinstance(panel_title, str):
            panel_title = None

        # Non-timeseries derived hints
        nt = p.get("non_timeseries")
        if isinstance(nt, dict):
            derived = nt.get("derived")
            if isinstance(derived, dict):
                rlc = _to_float(derived.get("row_lock_contention_rows"))
                if rlc and rlc > 0:
                    add(
                        {
                            "kind": "row_lock_contention_rows",
                            "panel": panel_title,
                            "details": f"Rows mentioning row-lock contention: {int(rlc)}",
                        },
                        3.0 + min(5.0, rlc / 2.0),
                    )

                br = _to_float(derived.get("blocking_rows"))
                if br and br > 0:
                    add(
                        {
                            "kind": "blocking_rows",
                            "panel": panel_title,
                            "details": f"Table rows that look like session/blocking details: {int(br)}",
                        },
                        2.0 + min(5.0, br / 2.0),
                    )

        series = p.get("series")
        if not isinstance(series, list):
            continue

        for s in series:
            if not isinstance(s, dict):
                continue

            name = s.get("series_name")
            if not isinstance(name, str):
                continue

            stats = s.get("stats") if isinstance(s.get("stats"), dict) else {}
            points = stats.get("points")
            try:
                n_points = int(points) if points is not None else 0
            except Exception:
                n_points = 0

            last_v = _to_float(s.get("last_value"))
            peak_v = _to_float(s.get("peak_value"))
            pct = _to_float(s.get("pct_change"))
            mean = _to_float(stats.get("mean"))
            min_v = _to_float(stats.get("min"))
            max_v = _to_float(stats.get("max"))

            if last_v is None:
                last_v = _to_float(stats.get("last"))
            if peak_v is None:
                peak_v = _to_float(max_v)

            if pct is None:
                first_v = _to_float(stats.get("first"))
                if first_v is not None and last_v is not None and abs(first_v) > 1e-9:
                    pct = (last_v - first_v) / first_v

            ratio = None
            if peak_v is not None and mean is not None and abs(mean) > 1e-9:
                ratio = peak_v / mean

            anomalies = s.get("anomalies")
            try:
                an = int(anomalies) if anomalies is not None else 0
            except Exception:
                an = 0

            name_l = name.lower()
            panel_l = (panel_title or "").lower()
            keyword_boost = 0.0
            if "row lock" in name_l or "enq: tx" in name_l or "tx - row lock" in name_l:
                keyword_boost += 2.5
            if "aas" in name_l or "aas" in panel_l or "average active" in panel_l:
                keyword_boost += 1.0
            if "elapsed" in name_l or "sql" in panel_l and "time" in panel_l:
                keyword_boost += 1.0

            # Emit meaningful signals only
            score = 0.0
            if pct is not None:
                score += min(4.0, abs(pct) * 2.0)
            if ratio is not None and ratio >= 1.5:
                score += min(4.0, ratio - 1.0)
            if an > 0:
                score += min(3.0, an / 2.0)
            score += keyword_boost

            if score < 2.5:
                continue

            sig: dict[str, Any] = {
                "kind": "series_signal",
                "panel": panel_title,
                "series": name,
                "points": n_points,
                "last": last_v,
                "min": min_v,
                "max": max_v,
                "mean": mean,
                "peak": peak_v,
                "pct_change": pct,
                "peak_time_utc": _iso_ms(s.get("peak_time_ms")),
                "last_time_utc": _iso_ms(s.get("last_time_ms")),
                "anomalies": an,
            }

            add(sig, score)

    # Keep top N
    signals.sort(key=lambda x: float(x.get("_score", 0.0)), reverse=True)
    for sig in signals:
        sig.pop("_score", None)

    return signals[:max_signals]


def _user_prompt(dashboard_digest: dict[str, Any], timeseries_summary: dict[str, Any] | None) -> str:
    digest_json = json.dumps(dashboard_digest, ensure_ascii=False, indent=2)

    ts_block = ""
    derived_block = ""
    if timeseries_summary is not None:
        derived = _derive_signals(timeseries_summary)
        derived_block = (
            "\n\nAuto-derived notable signals (use these first; they are computed from the summaries):\n"
            + json.dumps(derived, ensure_ascii=False, indent=2)
            + "\n"
        )

        ts_json = json.dumps(timeseries_summary, ensure_ascii=False, indent=2)
        ts_block = "\n\nTime series summary (computed from Grafana datasource queries):\n" + ts_json + "\n"

    return (
        "Analyze this Grafana dashboard digest and monitoring data, then provide evidence-backed recommendations.\n\n"
        "Return Markdown with these sections:\n"
        "0) Notable signals (5-12 bullets). Each bullet must reference a specific panel/series and at least one number from the inputs.\n"
        "1) Executive summary (3-6 bullets)\n"
        "2) Evidence (numbers) (only if time-series summary exists; 8-20 bullets). Each bullet must include: Panel title, Series name (or table field), and numbers (last/min/max/peak/pct_change if available).\n"
        "3) Findings & impact (prioritized; include severity: High/Med/Low). Tie each finding to evidence or to a specific panel configuration gap.\n"
        "4) Recommended actions (specific next steps; 6-14 bullets).\n"
        "5) Dashboard improvements (naming, units, thresholds, annotations, variable hygiene).\n"
        "6) Alerting recommendations (what to alert on, suggested thresholds, noise reduction).\n"
        "7) Questions / extra data needed.\n\n"
        "Rules:\n"
        "- If current metric values are not present, do not claim spikes/outages/low/high.\n"
        "- If a panel has query errors, treat it as data-unavailable and do not infer health from it.\n"
        "- For lock/contend signals: if any series/table indicates blocking or row-lock contention and values > 0, treat it as actionable and recommend immediate triage steps (do not say it is low/normal unless a threshold/baseline is provided).\n"
        "- Avoid generic best practices (backups, patching, upgrades) unless the dashboard/metrics indicate a gap.\n"
        "- Prefer recommendations tied to existing panel titles/targets.\n\n"
        f"Dashboard digest JSON:\n{digest_json}\n"
        f"{derived_block}"
        f"{ts_block}"
    )


@dataclass(frozen=True)
class NoneAIClient:
    def analyze_dashboard(self, *, dashboard_digest: dict[str, Any], timeseries_summary: dict[str, Any] | None = None) -> str:
        title = (dashboard_digest.get("dashboard") or {}).get("title")
        return (
            "# AI provider disabled\n\n"
            f"Dashboard: {title!r}\n\n"
            "Set `AI_PROVIDER` and provider-specific env vars to enable analysis."
        )


@dataclass(frozen=True)
class OpenAIChatClient:
    api_key: str
    model: str

    def analyze_dashboard(self, *, dashboard_digest: dict[str, Any], timeseries_summary: dict[str, Any] | None = None) -> str:
        try:
            from openai import OpenAI  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise AIError('OpenAI SDK not installed. Install with: pip install -e ".[openai]"') from exc

        if not self.api_key:
            raise AIError("OPENAI_API_KEY is missing.")
        if not self.model:
            raise AIError("OPENAI_MODEL is missing.")

        client = OpenAI(api_key=self.api_key)
        messages = [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": _user_prompt(dashboard_digest, timeseries_summary)},
        ]

        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.2,
            )
        except Exception as exc:  # pragma: no cover
            raise AIError(f"OpenAI request failed: {exc}") from exc

        choice = resp.choices[0]
        content = getattr(choice.message, "content", None)
        if not content or not isinstance(content, str):
            raise AIError("OpenAI returned an empty response.")
        return content.strip()


@dataclass(frozen=True)
class OllamaChatClient:
    base_url: str
    model: str
    timeout_s: float = 300.0
    num_predict: int | None = 1600

    def analyze_dashboard(self, *, dashboard_digest: dict[str, Any], timeseries_summary: dict[str, Any] | None = None) -> str:
        if not self.base_url:
            raise AIError("OLLAMA_URL is missing.")
        if not self.model:
            raise AIError("OLLAMA_MODEL is missing.")

        url = f"{self.base_url.rstrip('/')}" + "/api/chat"
        body: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": _user_prompt(dashboard_digest, timeseries_summary)},
            ],
        }
        if self.num_predict is not None:
            body["options"] = {"num_predict": int(self.num_predict)}

        try:
            resp = requests.post(url, json=body, timeout=self.timeout_s)
        except requests.RequestException as exc:
            raise AIError(f"Failed to reach Ollama at {self.base_url!r}: {exc}") from exc

        if resp.status_code >= 400:
            raise AIError(f"Ollama API error HTTP {resp.status_code}: {resp.text[:2000]}")

        try:
            data = resp.json()
        except Exception as exc:
            raise AIError(f"Ollama returned non-JSON: {exc}") from exc

        message = data.get("message") if isinstance(data, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not content or not isinstance(content, str):
            raise AIError("Ollama returned an empty response.")
        return content.strip()


def build_ai_client(
    *,
    provider: str,
    openai_api_key: str | None,
    openai_model: str | None,
    ollama_url: str | None = None,
    ollama_model: str | None = None,
    ollama_timeout_s: float | None = None,
    ollama_num_predict: int | None = None,
) -> AIClient:
    if provider == "none":
        return NoneAIClient()
    if provider == "openai":
        return OpenAIChatClient(api_key=openai_api_key or "", model=openai_model or "")
    if provider == "ollama":
        return OllamaChatClient(
            base_url=ollama_url or "",
            model=ollama_model or "",
            timeout_s=float(ollama_timeout_s) if ollama_timeout_s is not None else 300.0,
            num_predict=ollama_num_predict if ollama_num_predict is not None else 1600,
        )
    raise AIError(f"Unknown AI_PROVIDER: {provider!r}")
