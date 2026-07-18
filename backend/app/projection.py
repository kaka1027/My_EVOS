from __future__ import annotations

from .db import get_cursor
from .neo4j_db import get_session


def sync_projection() -> dict[str, int]:
    """Rebuild the active graph projection from PostgreSQL in one transaction."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT e.id::text AS entity_id, e.type::text AS type, e.name,
                   e.canonical_name, e.slug, e.status::text AS status,
                   s.category::text AS category, j.target_group::text AS target_group,
                   j.is_emerging, j.confidence AS job_confidence
            FROM entities e
            LEFT JOIN skills s ON s.entity_id=e.id
            LEFT JOIN jobs j ON j.entity_id=e.id
            WHERE e.status='active'
        """)
        entities = list(cur.fetchall())
        cur.execute("""
            SELECT r.id::text AS relation_id, r.rel_type::text AS rel_type,
                   r.source_id::text AS source_id, r.target_id::text AS target_id,
                   r.weight, r.confidence, r.evidence_count,
                   r.required_level::text AS required_level,
                   r.requirement_type::text AS requirement_type,
                   r.valid_from, r.valid_to
            FROM relations r WHERE r.status='active'
        """)
        relations = list(cur.fetchall())

    labels = {"JOB": "Job", "SKILL": "Skill", "TECHSTACK": "TechStack",
              "SCENARIO": "Scenario", "CERT": "Cert", "CANDIDATE": "Candidate"}
    with get_session() as session:
        session.run("MATCH (n) DETACH DELETE n")
        for row in entities:
            label = labels.get(row["type"])
            if not label:
                continue
            props = {k: v for k, v in dict(row).items() if v is not None and k != "type"}
            session.run(f"MERGE (n:{label} {{pg_id: $entity_id}}) SET n += $props",
                        entity_id=row["entity_id"], props=props)
        for row in relations:
            rel_type = row["rel_type"]
            props = {k: v for k, v in dict(row).items()
                     if k not in {"relation_id", "rel_type", "source_id", "target_id"} and v is not None}
            session.run(f"""
                MATCH (a {{pg_id: $source_id}}), (b {{pg_id: $target_id}})
                MERGE (a)-[r:{rel_type} {{pg_id: $relation_id}}]->(b)
                SET r += $props
            """, **row, props=props)
    return {"entities": len(entities), "relations": len(relations)}
