-- ============================================================
-- EVOS PostgreSQL 事实主库 Schema (MVP)
-- 权威数据源:所有实体/关系/证据以 PG 为准,Neo4j 为投影层
-- 依赖扩展:pgvector
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS vector;        -- pgvector

-- ------------------------------------------------------------
-- 枚举类型
-- ------------------------------------------------------------
CREATE TYPE entity_type       AS ENUM ('JOB','SKILL','TECHSTACK','SCENARIO','CERT','EVIDENCE','CANDIDATE');
CREATE TYPE skill_category     AS ENUM ('Programming','Framework','Database','AI_Skill','DevOps','Tool','Concept');
CREATE TYPE skill_level        AS ENUM ('BASIC','PROFICIENT','EXPERT');
CREATE TYPE requirement_kind   AS ENUM ('MANDATORY','BONUS');
CREATE TYPE relation_type      AS ENUM ('REQUIRES','BELONGS_TO','PREREQUISITE_OF','USED_IN','SIMILAR_TO','EVIDENCED_BY','HAS_SKILL');
CREATE TYPE created_source      AS ENUM ('rule','ner','embedding','llm','human');
CREATE TYPE record_status      AS ENUM ('active','deprecated','deleted');
CREATE TYPE target_group       AS ENUM ('AI_AGENT','JAVA');
CREATE TYPE dataset_kind        AS ENUM ('JD','RESUME','TREND_EVIDENCE');
CREATE TYPE split_kind          AS ENUM ('train','valid','test');
CREATE TYPE evidence_source     AS ENUM ('jd','resume','github','paper','doc','blog','human');
CREATE TYPE match_level         AS ENUM ('HIGH','MEDIUM','LOW');

-- ============================================================
-- 1. 数据集与原始文档
-- ============================================================
CREATE TABLE datasets (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind          dataset_kind NOT NULL,
    name          TEXT NOT NULL,
    version       TEXT NOT NULL DEFAULT 'v1',
    description   TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE documents (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id    UUID REFERENCES datasets(id),
    file_type     TEXT,                       -- pdf/docx/txt/image
    source_path   TEXT,
    source_url    TEXT,
    capture_date  DATE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 2. 原始 JD (300 条,作为证据源,不进 entities 表)
-- ============================================================
CREATE TABLE job_postings (
    jd_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id          UUID REFERENCES datasets(id),
    source_platform     TEXT,
    source_url          TEXT,
    capture_date        DATE,
    job_title           TEXT,
    company_name        TEXT,
    city                TEXT,
    salary_range        TEXT,
    experience_required TEXT,
    education_required  TEXT,
    job_description     TEXT,
    job_requirement     TEXT,
    raw_text            TEXT,
    target_group        target_group,
    -- 可空外键:该 JD 支撑的抽象岗位;新岗位发现前可为空
    job_entity_id       UUID,                  -- FK -> entities(id) (type=JOB),延后加约束
    annotator           TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- 3. 统一实体表 + 子类型表 (公共表 + 子类型表方案)
-- ============================================================
CREATE TABLE entities (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type          entity_type NOT NULL,
    slug          TEXT UNIQUE NOT NULL,        -- 人可读业务码,如 skill:langchain
    name          TEXT NOT NULL,               -- 展示名
    canonical_name TEXT NOT NULL,              -- 归一后的规范名
    status        record_status NOT NULL DEFAULT 'active',
    created_by    created_source NOT NULL DEFAULT 'human',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_entities_type   ON entities(type) WHERE status = 'active';
CREATE INDEX idx_entities_canon  ON entities(canonical_name);

-- job_postings.job_entity_id 现在可以加约束
ALTER TABLE job_postings
    ADD CONSTRAINT fk_jd_job_entity FOREIGN KEY (job_entity_id) REFERENCES entities(id);

-- 3.1 技能子表 (原子技能 + category + level)
CREATE TABLE skills (
    entity_id     UUID PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    category      skill_category NOT NULL,
    default_level skill_level,                 -- 该技能的典型/基线等级,可空
    description   TEXT
);

-- 3.2 抽象岗位子表 (由预置 + 新岗位发现生成,非原始 JD)
CREATE TABLE jobs (
    entity_id       UUID PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    target_group    target_group,
    is_emerging     BOOLEAN NOT NULL DEFAULT FALSE,  -- 新发现岗位标记
    core_duties     TEXT,
    typical_scenarios TEXT,
    definition_source created_source,           -- 岗位定义生成方式
    confidence      REAL                         -- 岗位定义整体置信度 0-1
);

-- 3.3 技术栈子表 (BELONGS_TO 的目标,分组用)
CREATE TABLE tech_stacks (
    entity_id     UUID PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    description   TEXT
);

-- 3.4 应用场景子表 (USED_IN 的目标)
CREATE TABLE scenarios (
    entity_id     UUID PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    description   TEXT
);

-- 3.5 证书子表
CREATE TABLE certs (
    entity_id     UUID PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    issuer        TEXT
);

-- 3.6 匿名候选人子表 (简历解析后的 Candidate 实体)
CREATE TABLE candidates (
    entity_id       UUID PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    resume_id       UUID,                        -- FK -> resumes(id),延后
    anon_label      TEXT,                        -- 匿名标识
    education        TEXT,
    years_experience REAL,
    target_job_group target_group
);

-- ============================================================
-- 4. 技能别名 / 归一
-- ============================================================
CREATE TABLE skill_aliases (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alias_text        TEXT NOT NULL,
    canonical_skill_id UUID NOT NULL REFERENCES skills(entity_id) ON DELETE CASCADE,
    source            created_source NOT NULL DEFAULT 'human',
    note              TEXT,                       -- 裁决记录
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (alias_text)
);
CREATE INDEX idx_alias_canon ON skill_aliases(canonical_skill_id);

-- ============================================================
-- 5. 统一关系表 (可空强类型列存关系专属属性)
-- ============================================================
CREATE TABLE relations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rel_type        relation_type NOT NULL,
    source_id       UUID NOT NULL REFERENCES entities(id),
    target_id       UUID NOT NULL REFERENCES entities(id),
    -- 公共属性
    weight          REAL,
    confidence      REAL,                        -- 0-1 最终聚合置信度
    evidence_count  INT NOT NULL DEFAULT 0,
    valid_from      DATE,
    valid_to        DATE,                         -- 软删除/失效:置 valid_to + status
    status          record_status NOT NULL DEFAULT 'active',
    created_by      created_source NOT NULL DEFAULT 'rule',
    -- 关系专属属性 (仅 REQUIRES / HAS_SKILL 有意义,其余 NULL)
    required_level    skill_level,
    requirement_type  requirement_kind,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_rel_source ON relations(source_id) WHERE status = 'active';
CREATE INDEX idx_rel_target ON relations(target_id) WHERE status = 'active';
CREATE INDEX idx_rel_type   ON relations(rel_type)  WHERE status = 'active';
-- 同一对实体同一关系类型在有效期内唯一
CREATE UNIQUE INDEX uq_rel_active
    ON relations(rel_type, source_id, target_id)
    WHERE status = 'active';

-- ============================================================
-- 6. 证据 + 关系-证据多对多
-- ============================================================
CREATE TABLE evidence (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type      evidence_source NOT NULL,
    title            TEXT,
    url              TEXT,
    snippet          TEXT,                        -- 原文片段
    jd_id            UUID REFERENCES job_postings(jd_id),  -- 来自 JD 时回指
    publish_date     DATE,
    capture_date     DATE,
    reliability_score REAL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE relation_evidence (
    relation_id   UUID NOT NULL REFERENCES relations(id) ON DELETE CASCADE,
    evidence_id   UUID NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    source_score  REAL,                          -- 该证据对该关系的分项贡献
    source_kind   evidence_source,               -- 该分项来源 (jd/github/paper/doc/blog/human)
    PRIMARY KEY (relation_id, evidence_id)
);

-- ============================================================
-- 7. 简历
-- ============================================================
CREATE TABLE resumes (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id     UUID REFERENCES datasets(id),
    document_id    UUID REFERENCES documents(id),
    anon_name      TEXT,
    raw_text       TEXT,
    parse_status   TEXT,
    target_group   target_group,
    manual_match_level match_level,              -- 人工匹配等级 (测试样例)
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE candidates
    ADD CONSTRAINT fk_candidate_resume FOREIGN KEY (resume_id) REFERENCES resumes(id);

CREATE TABLE resume_projects (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resume_id      UUID NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    project_name   TEXT,
    role_desc      TEXT,
    tech_used      TEXT
);

-- ============================================================
-- 8. 时间演化:趋势快照表 (岗位 × 技能 × 时间窗)
-- ============================================================
CREATE TABLE skill_trends (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_entity_id UUID REFERENCES entities(id),  -- 可空:全局技能趋势时为 NULL
    skill_entity_id UUID NOT NULL REFERENCES entities(id),
    time_bucket   DATE NOT NULL,                 -- 窗口起点,如 2024-01-01 (季度/月)
    frequency     INT NOT NULL DEFAULT 0,        -- 该窗口内出现次数
    doc_count     INT NOT NULL DEFAULT 0,        -- 覆盖 JD/文档数
    ratio         REAL,                          -- 占比
    weight        REAL,                          -- 该窗口权重
    UNIQUE (job_entity_id, skill_entity_id, time_bucket)
);
CREATE INDEX idx_trend_skill ON skill_trends(skill_entity_id, time_bucket);

-- ============================================================
-- 9. embedding (按用途分表)
-- ============================================================
CREATE TABLE skill_embeddings (
    skill_entity_id UUID PRIMARY KEY REFERENCES skills(entity_id) ON DELETE CASCADE,
    model_name    TEXT NOT NULL,
    embedding     vector(1024) NOT NULL          -- 维度按所选模型调整
);
CREATE INDEX idx_skill_emb ON skill_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE TABLE jd_embeddings (
    jd_id         UUID PRIMARY KEY REFERENCES job_postings(jd_id) ON DELETE CASCADE,
    model_name    TEXT NOT NULL,
    embedding     vector(1024) NOT NULL
);
CREATE INDEX idx_jd_emb ON jd_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE TABLE resume_embeddings (
    resume_id     UUID PRIMARY KEY REFERENCES resumes(id) ON DELETE CASCADE,
    model_name    TEXT NOT NULL,
    embedding     vector(1024) NOT NULL
);
CREATE INDEX idx_resume_emb ON resume_embeddings USING hnsw (embedding vector_cosine_ops);

-- ============================================================
-- 10. 数据集划分 (物理隔离防泄漏)
-- ============================================================
CREATE TABLE dataset_splits (
    jd_id         UUID PRIMARY KEY REFERENCES job_postings(jd_id) ON DELETE CASCADE,
    split         split_kind NOT NULL,
    target_group  target_group
);
CREATE INDEX idx_split ON dataset_splits(split);

-- ============================================================
-- 11. 评测金标 (独立 gold 表,与系统产出物理隔离)
-- ============================================================
-- JD 实体金标:标准答案里某 JD 应抽出的技能/字段实体
CREATE TABLE gold_jd_entities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    jd_id           UUID NOT NULL REFERENCES job_postings(jd_id),
    canonical_name  TEXT NOT NULL,               -- 归一后技能/实体名
    entity_type     entity_type NOT NULL,
    skill_category  skill_category,
    required_level    skill_level,
    requirement_type  requirement_kind,
    annotator       TEXT,
    version         TEXT NOT NULL DEFAULT 'v1'
);
CREATE INDEX idx_gold_jde_jd ON gold_jd_entities(jd_id);

-- JD 关系金标
CREATE TABLE gold_jd_relations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    jd_id           UUID NOT NULL REFERENCES job_postings(jd_id),
    rel_type        relation_type NOT NULL,
    source_canonical TEXT NOT NULL,
    target_canonical TEXT NOT NULL,
    required_level    skill_level,
    annotator       TEXT,
    version         TEXT NOT NULL DEFAULT 'v1'
);

-- 简历标注金标
CREATE TABLE gold_resume_annotations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resume_id       UUID NOT NULL REFERENCES resumes(id),
    field_kind      TEXT NOT NULL,               -- basic_field / skill / project
    field_name      TEXT,
    canonical_value TEXT,
    skill_level     skill_level,
    evidence_snippet TEXT,
    annotator       TEXT,
    version         TEXT NOT NULL DEFAULT 'v1'
);

-- 人岗匹配金标
CREATE TABLE gold_matching (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resume_id       UUID NOT NULL REFERENCES resumes(id),
    target_job_group target_group NOT NULL,
    match_level     match_level NOT NULL,
    missing_skills  TEXT[],                       -- 关键缺失技能 (canonical)
    covered_mandatory TEXT[],
    path_reasonable BOOLEAN,                      -- 推荐学习路径是否合理
    annotator       TEXT,
    version         TEXT NOT NULL DEFAULT 'v1'
);

-- ============================================================
-- 12. 异步任务 + 评测结果
-- ============================================================
CREATE TABLE tasks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_type     TEXT NOT NULL,                 -- ocr/extract/graph_sync/eval/...
    status        TEXT NOT NULL DEFAULT 'pending',-- pending/running/success/failed
    progress      REAL DEFAULT 0,
    error_message TEXT,
    result_ref    TEXT,                          -- 结果引用 (表名/文件/id)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE evaluations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    eval_type       TEXT NOT NULL,               -- jd_parse / resume_extract / matching
    dataset_version TEXT NOT NULL,
    model_version   TEXT NOT NULL,
    split           split_kind NOT NULL DEFAULT 'test',
    precision       REAL,
    recall          REAL,
    f1              REAL,
    score           REAL,                        -- 加权综合分 (ScoreJD/ScoreResume/ScoreMatch)
    detail          JSONB,                       -- 各分项 (F1skill / Accjob_field / ...)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 错误样例 (错误分析页面)
CREATE TABLE error_cases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    evaluation_id   UUID REFERENCES evaluations(id) ON DELETE CASCADE,
    error_type      TEXT NOT NULL,               -- 漏抽/误抽/归一化错误/关系错误/...
    source_snippet  TEXT,
    system_output   TEXT,
    gold_output     TEXT,
    fix_suggestion  TEXT
);
