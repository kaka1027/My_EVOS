# EVOS Backend API

This is a thin FastAPI service over the EVOS PostgreSQL fact database.

## Run

```powershell
cd F:\EVOS\My_EVOS
pip install -r backend\requirements.txt
$env:PGHOST="127.0.0.1"
$env:PGPORT="54329"
$env:PGUSER="postgres"
$env:PGDATABASE="evos"
$env:NEO4J_URI="bolt://127.0.0.1:7687"
$env:NEO4J_USER="neo4j"
$env:NEO4J_PASSWORD="change-me"
uvicorn backend.app.main:app --reload --port 8000
```

## Neo4j projection

PostgreSQL remains the authoritative database. Neo4j is an independently rebuildable
projection used for graph traversal. Start Neo4j from the repository root:

```powershell
docker compose up -d neo4j
```

After PostgreSQL is available and the API is running, rebuild the active projection:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/admin/graph/sync
```

The sync endpoint reads active entities and relations from PostgreSQL and recreates
the Neo4j projection. It is intentionally idempotent and can be retried after a
temporary Neo4j outage. `/health` reports PostgreSQL and Neo4j independently.

Open API docs:

```text
http://127.0.0.1:8000/docs
```

## Frontend graph endpoints

- `GET /api/graph`
- `GET /api/graph?entity_type=SKILL`
- `GET /api/graph?rel_type=REQUIRES`
- `GET /api/graph/jobs/job:ai-agent-engineer`

Graph response format:

```json
{
  "nodes": [
    {
      "id": "uuid",
      "type": "JOB",
      "label": "AI Agent engineer",
      "properties": {}
    }
  ],
  "edges": [
    {
      "id": "uuid",
      "source": "job_uuid",
      "target": "skill_uuid",
      "type": "REQUIRES",
      "label": "REQUIRES",
      "properties": {
        "required_level": "PROFICIENT",
        "requirement_type": "MANDATORY"
      }
    }
  ]
}
```

## Match endpoint

- `GET /api/match/jobs/job:ai-agent-engineer/candidates/cand:a`

This endpoint reuses `db_design.matching.match_algorithm`.
