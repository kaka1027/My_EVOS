from __future__ import annotations

from typing import Iterable

from db_design.matching.match_algorithm import SkillHave, SkillReq, compute_match

from .db import get_cursor
from .schemas import GraphEdge, GraphNode, GraphResponse


def _node_from_row(row: dict) -> GraphNode:
    props = {
        "slug": row.get("slug"),
        "canonical_name": row.get("canonical_name"),
        "status": row.get("status"),
        "category": row.get("category"),
        "target_group": row.get("target_group"),
        "is_emerging": row.get("is_emerging"),
        "confidence": row.get("job_confidence"),
    }
    return GraphNode(
        id=str(row["id"]),
        type=row["type"],
        label=row["name"],
        properties={k: v for k, v in props.items() if v is not None},
    )


def _edge_from_row(row: dict) -> GraphEdge:
    props = {
        "weight": row.get("weight"),
        "confidence": row.get("confidence"),
        "evidence_count": row.get("evidence_count"),
        "required_level": row.get("required_level"),
        "requirement_type": row.get("requirement_type"),
        "created_by": row.get("created_by"),
        "valid_from": row.get("valid_from").isoformat() if row.get("valid_from") else None,
        "valid_to": row.get("valid_to").isoformat() if row.get("valid_to") else None,
    }
    return GraphEdge(
        id=str(row["id"]),
        source=str(row["source_id"]),
        target=str(row["target_id"]),
        type=row["rel_type"],
        label=row["rel_type"],
        properties={k: v for k, v in props.items() if v is not None},
    )


def _dedupe_nodes(rows: Iterable[dict]) -> list[GraphNode]:
    nodes: dict[str, GraphNode] = {}
    for row in rows:
        node = _node_from_row(row)
        nodes[node.id] = node
    return list(nodes.values())


def list_jobs() -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT e.id::text, e.slug, e.name, e.canonical_name,
                   j.target_group::text, j.is_emerging, j.confidence
            FROM entities e
            JOIN jobs j ON j.entity_id = e.id
            WHERE e.type = 'JOB' AND e.status = 'active'
            ORDER BY e.name
            """
        )
        return list(cur.fetchall())


def list_candidates() -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT e.id::text, e.slug, e.name, c.anon_label, c.education,
                   c.years_experience, c.target_job_group::text
            FROM entities e
            JOIN candidates c ON c.entity_id = e.id
            WHERE e.type = 'CANDIDATE' AND e.status = 'active'
            ORDER BY e.name
            """
        )
        return list(cur.fetchall())


def get_graph(entity_type: str | None, rel_type: str | None, limit: int) -> GraphResponse:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT e.id::text, e.type::text, e.slug, e.name, e.canonical_name,
                   e.status::text, s.category::text, j.target_group::text,
                   j.is_emerging, j.confidence AS job_confidence
            FROM entities e
            LEFT JOIN skills s ON s.entity_id = e.id
            LEFT JOIN jobs j ON j.entity_id = e.id
            WHERE e.status = 'active'
              AND (%s IS NULL OR e.type::text = %s)
            ORDER BY e.type, e.name
            LIMIT %s
            """,
            (entity_type, entity_type, limit),
        )
        node_rows = list(cur.fetchall())
        node_ids = [row["id"] for row in node_rows]
        if not node_ids:
            return GraphResponse(nodes=[], edges=[])

        cur.execute(
            """
            SELECT r.id::text, r.rel_type::text, r.source_id::text, r.target_id::text,
                   r.weight, r.confidence, r.evidence_count, r.required_level::text,
                   r.requirement_type::text, r.created_by::text, r.valid_from, r.valid_to
            FROM relations r
            WHERE r.status = 'active'
              AND (%s IS NULL OR r.rel_type::text = %s)
              AND r.source_id = ANY(%s::uuid[])
              AND r.target_id = ANY(%s::uuid[])
            ORDER BY r.rel_type
            """,
            (rel_type, rel_type, node_ids, node_ids),
        )
        edge_rows = list(cur.fetchall())

    return GraphResponse(
        nodes=[_node_from_row(row) for row in node_rows],
        edges=[_edge_from_row(row) for row in edge_rows],
    )


def get_job_graph(job_ref: str, include_related: bool = True) -> GraphResponse:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM entities
            WHERE type = 'JOB' AND status = 'active' AND (id::text = %s OR slug = %s)
            """,
            (job_ref, job_ref),
        )
        job = cur.fetchone()
        if not job:
            return GraphResponse(nodes=[], edges=[])
        job_id = str(job["id"])

        cur.execute(
            """
            WITH direct_edges AS (
                SELECT *
                FROM relations
                WHERE status = 'active'
                  AND source_id = %s::uuid
                  AND rel_type = 'REQUIRES'
            ),
            direct_nodes AS (
                SELECT %s::uuid AS id
                UNION
                SELECT target_id FROM direct_edges
            ),
            related_edges AS (
                SELECT r.*
                FROM relations r
                WHERE %s
                  AND r.status = 'active'
                  AND r.rel_type IN ('BELONGS_TO', 'USED_IN', 'PREREQUISITE_OF')
                  AND (r.source_id IN (SELECT id FROM direct_nodes)
                       OR r.target_id IN (SELECT id FROM direct_nodes))
            ),
            all_edges AS (
                SELECT * FROM direct_edges
                UNION
                SELECT * FROM related_edges
            ),
            all_nodes AS (
                SELECT id FROM direct_nodes
                UNION SELECT source_id FROM all_edges
                UNION SELECT target_id FROM all_edges
            )
            SELECT e.id::text, e.type::text, e.slug, e.name, e.canonical_name,
                   e.status::text, s.category::text, j.target_group::text,
                   j.is_emerging, j.confidence AS job_confidence
            FROM entities e
            LEFT JOIN skills s ON s.entity_id = e.id
            LEFT JOIN jobs j ON j.entity_id = e.id
            WHERE e.id IN (SELECT id FROM all_nodes)
            ORDER BY e.type, e.name
            """,
            (job_id, job_id, include_related),
        )
        nodes = list(cur.fetchall())

        cur.execute(
            """
            WITH direct_edges AS (
                SELECT *
                FROM relations
                WHERE status = 'active'
                  AND source_id = %s::uuid
                  AND rel_type = 'REQUIRES'
            ),
            direct_nodes AS (
                SELECT %s::uuid AS id
                UNION
                SELECT target_id FROM direct_edges
            ),
            related_edges AS (
                SELECT r.*
                FROM relations r
                WHERE %s
                  AND r.status = 'active'
                  AND r.rel_type IN ('BELONGS_TO', 'USED_IN', 'PREREQUISITE_OF')
                  AND (r.source_id IN (SELECT id FROM direct_nodes)
                       OR r.target_id IN (SELECT id FROM direct_nodes))
            )
            SELECT r.id::text, r.rel_type::text, r.source_id::text, r.target_id::text,
                   r.weight, r.confidence, r.evidence_count, r.required_level::text,
                   r.requirement_type::text, r.created_by::text, r.valid_from, r.valid_to
            FROM (
                SELECT * FROM direct_edges
                UNION
                SELECT * FROM related_edges
            ) r
            ORDER BY r.rel_type
            """,
            (job_id, job_id, include_related),
        )
        edges = list(cur.fetchall())

    return GraphResponse(nodes=_dedupe_nodes(nodes), edges=[_edge_from_row(row) for row in edges])


def compute_job_candidate_match(job_ref: str, candidate_ref: str) -> dict | None:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id::text, name
            FROM entities
            WHERE type = 'JOB' AND status = 'active' AND (id::text = %s OR slug = %s)
            """,
            (job_ref, job_ref),
        )
        job = cur.fetchone()
        cur.execute(
            """
            SELECT id::text, name
            FROM entities
            WHERE type = 'CANDIDATE' AND status = 'active' AND (id::text = %s OR slug = %s)
            """,
            (candidate_ref, candidate_ref),
        )
        candidate = cur.fetchone()
        if not job or not candidate:
            return None

        cur.execute(
            """
            SELECT s.id::text, s.canonical_name, r.required_level::text, r.requirement_type::text
            FROM relations r
            JOIN entities s ON s.id = r.target_id
            WHERE r.source_id = %s::uuid
              AND r.rel_type = 'REQUIRES'
              AND r.status = 'active'
            """,
            (job["id"],),
        )
        reqs = [SkillReq(row["id"], row["canonical_name"], row["required_level"], row["requirement_type"]) for row in cur.fetchall()]

        cur.execute(
            """
            SELECT s.id::text, r.required_level::text
            FROM relations r
            JOIN entities s ON s.id = r.target_id
            WHERE r.source_id = %s::uuid
              AND r.rel_type = 'HAS_SKILL'
              AND r.status = 'active'
            """,
            (candidate["id"],),
        )
        haves = [SkillHave(row["id"], row["required_level"]) for row in cur.fetchall()]

        cur.execute(
            """
            SELECT b.id::text AS target, a.id::text AS pre
            FROM relations r
            JOIN entities a ON a.id = r.source_id
            JOIN entities b ON b.id = r.target_id
            WHERE r.rel_type = 'PREREQUISITE_OF' AND r.status = 'active'
            """
        )
        prereq_edges: dict[str, list[str]] = {}
        for row in cur.fetchall():
            prereq_edges.setdefault(row["target"], []).append(row["pre"])

        cur.execute("SELECT id::text, canonical_name FROM entities WHERE type = 'SKILL'")
        skill_names = {row["id"]: row["canonical_name"] for row in cur.fetchall()}

    result = compute_match(job["name"], reqs, haves, prereq_edges, skill_names)
    return {
        "job_name": result.job_name,
        "candidate_name": candidate["name"],
        "coverage": result.coverage,
        "match_level": result.match_level,
        "mandatory_avg": result.mandatory_avg,
        "bonus_avg": result.bonus_avg,
        "missing_skills": result.missing_skills,
        "learning_paths": result.learning_paths,
        "skill_results": [item.__dict__ for item in result.skill_results],
    }
