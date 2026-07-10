from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    id: str
    type: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class JobSummary(BaseModel):
    id: str
    slug: str
    name: str
    canonical_name: str
    target_group: str | None = None
    is_emerging: bool | None = None
    confidence: float | None = None


class CandidateSummary(BaseModel):
    id: str
    slug: str
    name: str
    anon_label: str | None = None
    education: str | None = None
    years_experience: float | None = None
    target_job_group: str | None = None


class MatchSkillResult(BaseModel):
    canonical: str
    requirement_type: str
    required_level: str
    have_level: str | None
    score: float
    status: str


class MatchResponse(BaseModel):
    job_name: str
    candidate_name: str
    coverage: float
    match_level: str
    mandatory_avg: float
    bonus_avg: float
    missing_skills: list[str]
    learning_paths: dict[str, list[str]]
    skill_results: list[MatchSkillResult]
