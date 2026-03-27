from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyzePayloadRequest(BaseModel):
    dashboard_digest: dict = Field(default_factory=dict)
    timeseries_summary: dict | None = None


class AnalyzePayloadResponse(BaseModel):
    report_markdown: str
