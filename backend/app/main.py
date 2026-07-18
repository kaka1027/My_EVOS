from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import get_cursor
from .repositories import (
    compute_job_candidate_match,
    get_graph,
    get_job_graph,
    get_job_graph_neo4j,
    list_candidates,
    list_jobs,
)
from .schemas import CandidateSummary, GraphResponse, JobSummary, MatchResponse
from .neo4j_db import verify_connection
from .projection import sync_projection

app = FastAPI(title="EVOS Backend API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    with get_cursor() as cur:
        cur.execute("SELECT 1 AS ok")
        row = cur.fetchone()
    return {"status": "ok", "postgresql": bool(row and row["ok"] == 1), "neo4j": verify_connection()}


@app.post("/api/admin/graph/sync")
def api_graph_sync() -> dict[str, object]:
    try:
        counts = sync_projection()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"graph sync failed: {exc}") from exc
    return {"status": "ok", **counts}


@app.get("/api/jobs", response_model=list[JobSummary])
def api_list_jobs() -> list[dict]:
    return list_jobs()


@app.get("/api/candidates", response_model=list[CandidateSummary])
def api_list_candidates() -> list[dict]:
    return list_candidates()


@app.get("/api/graph", response_model=GraphResponse)
def api_graph(
    entity_type: str | None = Query(default=None, examples=["SKILL"]),
    rel_type: str | None = Query(default=None, examples=["REQUIRES"]),
    limit: int = Query(default=300, ge=1, le=2000),
) -> GraphResponse:
    return get_graph(entity_type=entity_type, rel_type=rel_type, limit=limit)


@app.get("/api/graph/jobs/{job_ref}", response_model=GraphResponse)
def api_job_graph(
    job_ref: str,
    include_related: bool = Query(default=True),
) -> GraphResponse:
    try:
        graph = get_job_graph_neo4j(job_ref, include_related=include_related)
    except Exception:
        graph = get_job_graph(job_ref, include_related=include_related)
    if not graph.nodes:
        raise HTTPException(status_code=404, detail="job not found")
    return graph


@app.get("/api/match/jobs/{job_ref}/candidates/{candidate_ref}", response_model=MatchResponse)
def api_match(job_ref: str, candidate_ref: str) -> dict:
    result = compute_job_candidate_match(job_ref, candidate_ref)
    if result is None:
        raise HTTPException(status_code=404, detail="job or candidate not found")
    return result
