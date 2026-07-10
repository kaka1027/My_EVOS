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
uvicorn backend.app.main:app --reload --port 8000
```

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
