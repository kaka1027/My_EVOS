-- ============================================================
-- EVOS 种子数据 (MVP 冒烟测试用)
-- 全部用 slug 子查询关联,规避 UUID 主键/外键回填问题。
-- 依赖:01_postgresql_schema.sql 已执行。
-- 覆盖:AI Agent + Java 两条主线的最小可运行图谱 + 一份简历 + 一条评测金标。
-- ============================================================

-- ------------------------------------------------------------
-- 1. 数据集
-- ------------------------------------------------------------
INSERT INTO datasets (kind, name, version, description) VALUES
  ('JD',             'EVOS JD 数据集',   'v1', 'AI Agent + Java 两方向 JD'),
  ('RESUME',         'EVOS 简历样例集',  'v1', '测试简历'),
  ('TREND_EVIDENCE', 'EVOS 趋势证据集',  'v1', 'GitHub/arXiv/doc 证据');

-- ------------------------------------------------------------
-- 2. 实体:抽象岗位 (2 条主线)
-- ------------------------------------------------------------
INSERT INTO entities (type, slug, name, canonical_name, created_by) VALUES
  ('JOB', 'job:ai-agent-engineer', 'AI Agent 应用工程师', 'AI Agent 应用工程师', 'human'),
  ('JOB', 'job:java-backend',      'Java 开发工程师',      'Java 开发工程师',      'human');

INSERT INTO jobs (entity_id, target_group, is_emerging, core_duties, definition_source, confidence)
SELECT id, 'AI_AGENT', TRUE,  '设计与实现基于大模型的智能体应用', 'llm',   0.86
  FROM entities WHERE slug = 'job:ai-agent-engineer';
INSERT INTO jobs (entity_id, target_group, is_emerging, core_duties, definition_source, confidence)
SELECT id, 'JAVA',     FALSE, 'Java 后端微服务开发与维护',        'human', 0.95
  FROM entities WHERE slug = 'job:java-backend';

-- ------------------------------------------------------------
-- 3. 实体:技能 (含 category)
-- ------------------------------------------------------------
INSERT INTO entities (type, slug, name, canonical_name, created_by) VALUES
  ('SKILL', 'skill:python',       'Python',        'Python',            'rule'),
  ('SKILL', 'skill:java',         'Java',          'Java',              'rule'),
  ('SKILL', 'skill:langchain',    'LangChain',     'LangChain',         'rule'),
  ('SKILL', 'skill:rag',          'RAG',           'RAG',               'ner'),
  ('SKILL', 'skill:prompt-eng',   'Prompt 工程',   'Prompt Engineering','llm'),
  ('SKILL', 'skill:spring-boot',  'Spring Boot',   'Spring Boot',       'rule'),
  ('SKILL', 'skill:mysql',        'MySQL',         'MySQL',             'rule'),
  ('SKILL', 'skill:redis',        'Redis',         'Redis',             'rule'),
  ('SKILL', 'skill:docker',       'Docker',        'Docker',            'rule'),
  ('SKILL', 'skill:k8s',          'Kubernetes',    'Kubernetes',        'rule');

INSERT INTO skills (entity_id, category, default_level)
SELECT id, cat::skill_category, lvl::skill_level FROM (VALUES
  ('skill:python',      'Programming', 'PROFICIENT'),
  ('skill:java',        'Programming', 'EXPERT'),
  ('skill:langchain',   'Framework',   'PROFICIENT'),
  ('skill:rag',         'AI_Skill',    'PROFICIENT'),
  ('skill:prompt-eng',  'AI_Skill',    'BASIC'),
  ('skill:spring-boot', 'Framework',   'EXPERT'),
  ('skill:mysql',       'Database',    'PROFICIENT'),
  ('skill:redis',       'Database',    'PROFICIENT'),
  ('skill:docker',      'DevOps',      'BASIC'),
  ('skill:k8s',         'DevOps',      'BASIC')
) AS v(slug, cat, lvl)
JOIN entities e ON e.slug = v.slug;

-- ------------------------------------------------------------
-- 4. 实体:技术栈 + 场景
-- ------------------------------------------------------------
INSERT INTO entities (type, slug, name, canonical_name, created_by) VALUES
  ('TECHSTACK', 'stack:llm-app',      'LLM 应用技术栈', 'LLM 应用技术栈', 'human'),
  ('TECHSTACK', 'stack:spring',       'Spring 全家桶',   'Spring 全家桶',   'human'),
  ('SCENARIO',  'scenario:kb-qa',     '知识库问答',      '知识库问答',      'ner'),
  ('SCENARIO',  'scenario:microsvc',  '微服务',          '微服务',          'ner');
INSERT INTO tech_stacks (entity_id) SELECT id FROM entities WHERE type='TECHSTACK';
INSERT INTO scenarios   (entity_id) SELECT id FROM entities WHERE type='SCENARIO';

-- ------------------------------------------------------------
-- 5. 技能别名 (归一验证)
-- ------------------------------------------------------------
INSERT INTO skill_aliases (alias_text, canonical_skill_id, source, note)
SELECT v.alias, e.id, 'human', v.note FROM (VALUES
  ('大模型应用开发', 'skill:langchain', 'LLM 应用开发归一到 LangChain 生态'),
  ('检索增强生成',   'skill:rag',       'RAG 中文别名'),
  ('K8s',            'skill:k8s',       'Kubernetes 缩写')
) AS v(alias, slug, note)
JOIN entities e ON e.slug = v.slug;

-- ------------------------------------------------------------
-- 6. 原始 JD (2 条,作证据) + 关联抽象岗位
-- ------------------------------------------------------------
INSERT INTO job_postings (dataset_id, source_platform, source_url, capture_date,
                          job_title, company_name, city, target_group,
                          job_description, raw_text, job_entity_id, annotator)
SELECT (SELECT id FROM datasets WHERE kind='JD'),
       'BOSS直聘', 'https://example.com/jd/ai001', DATE '2026-06-01',
       'AI Agent 开发工程师', '示例科技', '上海', 'AI_AGENT',
       '负责智能体应用开发', '负责智能体应用开发,熟悉 LangChain/RAG',
       (SELECT id FROM entities WHERE slug='job:ai-agent-engineer'), 'KAKA';
INSERT INTO job_postings (dataset_id, source_platform, source_url, capture_date,
                          job_title, company_name, city, target_group,
                          job_description, raw_text, job_entity_id, annotator)
SELECT (SELECT id FROM datasets WHERE kind='JD'),
       '智联招聘', 'https://example.com/jd/java001', DATE '2026-06-02',
       'Java 后端工程师', '示例科技', '北京', 'JAVA',
       '负责后端微服务开发', '负责后端微服务开发,熟悉 Spring Boot/MySQL',
       (SELECT id FROM entities WHERE slug='job:java-backend'), 'KAKA';

-- ------------------------------------------------------------
-- 7. 关系:REQUIRES (岗位需要技能,带 level + 必备/加分)
-- ------------------------------------------------------------
INSERT INTO relations (rel_type, source_id, target_id, weight, confidence,
                       required_level, requirement_type, created_by, valid_from)
SELECT 'REQUIRES', j.id, s.id, v.w, v.conf,
       v.lvl::skill_level, v.req::requirement_kind, 'rule', DATE '2026-06-01'
FROM (VALUES
  ('job:ai-agent-engineer', 'skill:python',     0.9, 0.92, 'PROFICIENT', 'MANDATORY'),
  ('job:ai-agent-engineer', 'skill:langchain',  0.9, 0.90, 'PROFICIENT', 'MANDATORY'),
  ('job:ai-agent-engineer', 'skill:rag',        0.8, 0.85, 'PROFICIENT', 'MANDATORY'),
  ('job:ai-agent-engineer', 'skill:prompt-eng', 0.6, 0.70, 'BASIC',      'BONUS'),
  ('job:ai-agent-engineer', 'skill:docker',     0.5, 0.65, 'BASIC',      'BONUS'),
  ('job:java-backend',      'skill:java',       1.0, 0.98, 'EXPERT',     'MANDATORY'),
  ('job:java-backend',      'skill:spring-boot',0.9, 0.95, 'EXPERT',     'MANDATORY'),
  ('job:java-backend',      'skill:mysql',      0.8, 0.90, 'PROFICIENT', 'MANDATORY'),
  ('job:java-backend',      'skill:redis',      0.7, 0.82, 'PROFICIENT', 'BONUS'),
  ('job:java-backend',      'skill:k8s',        0.5, 0.60, 'BASIC',      'BONUS')
) AS v(job_slug, skill_slug, w, conf, lvl, req)
JOIN entities j ON j.slug = v.job_slug
JOIN entities s ON s.slug = v.skill_slug;

-- 关系:BELONGS_TO (技能属于技术栈)
INSERT INTO relations (rel_type, source_id, target_id, confidence, created_by)
SELECT 'BELONGS_TO', s.id, t.id, 0.9, 'rule'
FROM (VALUES
  ('skill:langchain',   'stack:llm-app'),
  ('skill:rag',         'stack:llm-app'),
  ('skill:spring-boot', 'stack:spring'),
  ('skill:mysql',       'stack:spring')
) AS v(skill_slug, stack_slug)
JOIN entities s ON s.slug = v.skill_slug
JOIN entities t ON t.slug = v.stack_slug;

-- 关系:PREREQUISITE_OF (前置依赖,学习路径用)
INSERT INTO relations (rel_type, source_id, target_id, weight, confidence, created_by)
SELECT 'PREREQUISITE_OF', a.id, b.id, 0.8, 0.85, 'human'
FROM (VALUES
  ('skill:python',   'skill:langchain'),
  ('skill:langchain','skill:rag'),
  ('skill:java',     'skill:spring-boot'),
  ('skill:docker',   'skill:k8s')
) AS v(pre_slug, post_slug)
JOIN entities a ON a.slug = v.pre_slug
JOIN entities b ON b.slug = v.post_slug;

-- 关系:USED_IN (技能用于场景)
INSERT INTO relations (rel_type, source_id, target_id, confidence, created_by)
SELECT 'USED_IN', s.id, sc.id, 0.8, 'ner'
FROM (VALUES
  ('skill:rag',         'scenario:kb-qa'),
  ('skill:spring-boot', 'scenario:microsvc')
) AS v(skill_slug, scen_slug)
JOIN entities s  ON s.slug  = v.skill_slug
JOIN entities sc ON sc.slug = v.scen_slug;

-- ------------------------------------------------------------
-- 8. 证据 + 关系-证据绑定
-- ------------------------------------------------------------
INSERT INTO evidence (source_type, title, url, snippet, jd_id, reliability_score)
SELECT 'jd', 'AI JD 片段', 'https://example.com/jd/ai001',
       '熟悉 LangChain/RAG', jp.jd_id, 0.9
FROM job_postings jp WHERE jp.target_group='AI_AGENT' LIMIT 1;
INSERT INTO evidence (source_type, title, url, snippet, reliability_score)
VALUES ('github', 'LangChain 仓库', 'https://github.com/langchain-ai/langchain',
        'LangChain 高热度开源项目', 0.95);

-- 绑定:REQUIRES(ai-agent, langchain) <- 两条证据
INSERT INTO relation_evidence (relation_id, evidence_id, source_score, source_kind)
SELECT r.id, ev.id, 0.9, 'jd'
FROM relations r
JOIN entities j ON j.id = r.source_id AND j.slug='job:ai-agent-engineer'
JOIN entities s ON s.id = r.target_id AND s.slug='skill:langchain'
CROSS JOIN evidence ev
WHERE r.rel_type='REQUIRES' AND ev.source_type='jd';
INSERT INTO relation_evidence (relation_id, evidence_id, source_score, source_kind)
SELECT r.id, ev.id, 0.95, 'github'
FROM relations r
JOIN entities j ON j.id = r.source_id AND j.slug='job:ai-agent-engineer'
JOIN entities s ON s.id = r.target_id AND s.slug='skill:langchain'
CROSS JOIN evidence ev
WHERE r.rel_type='REQUIRES' AND ev.source_type='github';

-- 回填 evidence_count
UPDATE relations r SET evidence_count = sub.cnt
FROM (SELECT relation_id, COUNT(*) cnt FROM relation_evidence GROUP BY relation_id) sub
WHERE r.id = sub.relation_id;

-- ------------------------------------------------------------
-- 9. 简历 + 候选人 + HAS_SKILL
-- ------------------------------------------------------------
INSERT INTO resumes (dataset_id, anon_name, raw_text, parse_status, target_group, manual_match_level)
SELECT (SELECT id FROM datasets WHERE kind='RESUME'),
       '候选人A', 'Python/LangChain 3年,做过知识库问答', 'parsed', 'AI_AGENT', 'MEDIUM';

INSERT INTO entities (type, slug, name, canonical_name, created_by) VALUES
  ('CANDIDATE', 'cand:a', '候选人A', '候选人A', 'human');
INSERT INTO candidates (entity_id, resume_id, anon_label, education, years_experience, target_job_group)
SELECT e.id, r.id, '候选人A', '本科', 3, 'AI_AGENT'
FROM entities e, resumes r WHERE e.slug='cand:a' AND r.anon_name='候选人A';

INSERT INTO resume_projects (resume_id, project_name, role_desc, tech_used)
SELECT r.id, '企业知识库问答系统', '核心开发', 'Python, LangChain, RAG'
FROM resumes r WHERE r.anon_name='候选人A';

-- 候选人实际拥有的技能 (缺 RAG -> 后面匹配算法能识别出缺口)
INSERT INTO relations (rel_type, source_id, target_id, required_level, confidence, created_by)
SELECT 'HAS_SKILL', c.id, s.id, v.lvl::skill_level, 0.9, 'ner'
FROM (VALUES
  ('cand:a', 'skill:python',    'PROFICIENT'),
  ('cand:a', 'skill:langchain', 'BASIC'),
  ('cand:a', 'skill:docker',    'BASIC')
) AS v(cand_slug, skill_slug, lvl)
JOIN entities c ON c.slug = v.cand_slug
JOIN entities s ON s.slug = v.skill_slug;

-- ------------------------------------------------------------
-- 10. 趋势快照 (Kubernetes 在 Java 岗的上升趋势)
-- ------------------------------------------------------------
INSERT INTO skill_trends (job_entity_id, skill_entity_id, time_bucket, frequency, doc_count, ratio, weight)
SELECT j.id, s.id, v.tb::date, v.freq, v.dc, v.ratio, v.w
FROM (VALUES
  ('job:java-backend', 'skill:k8s', '2024-01-01', 5,  50, 0.10, 0.3),
  ('job:java-backend', 'skill:k8s', '2024-07-01', 12, 60, 0.20, 0.5),
  ('job:java-backend', 'skill:k8s', '2025-01-01', 25, 70, 0.36, 0.8)
) AS v(job_slug, skill_slug, tb, freq, dc, ratio, w)
JOIN entities j ON j.slug = v.job_slug
JOIN entities s ON s.slug = v.skill_slug;

-- ------------------------------------------------------------
-- 11. 数据集划分
-- ------------------------------------------------------------
INSERT INTO dataset_splits (jd_id, split, target_group)
SELECT jd_id, 'test', target_group FROM job_postings WHERE target_group='AI_AGENT';
INSERT INTO dataset_splits (jd_id, split, target_group)
SELECT jd_id, 'train', target_group FROM job_postings WHERE target_group='JAVA';

-- ------------------------------------------------------------
-- 12. 评测金标 + 评测结果
-- ------------------------------------------------------------
-- JD 技能实体金标
INSERT INTO gold_jd_entities (jd_id, canonical_name, entity_type, skill_category, required_level, requirement_type, annotator)
SELECT jp.jd_id, v.cn, 'SKILL', v.cat::skill_category, v.lvl::skill_level, v.req::requirement_kind, 'KAKA'
FROM job_postings jp
CROSS JOIN (VALUES
  ('Python',    'Programming', 'PROFICIENT', 'MANDATORY'),
  ('LangChain', 'Framework',   'PROFICIENT', 'MANDATORY'),
  ('RAG',       'AI_Skill',    'PROFICIENT', 'MANDATORY')
) AS v(cn, cat, lvl, req)
WHERE jp.target_group='AI_AGENT';

-- JD 字段金标(job_title / city / target_group)
INSERT INTO gold_jd_entities (jd_id, canonical_name, entity_type, annotator)
SELECT jp.jd_id, v.cn, v.et::entity_type, 'KAKA'
FROM job_postings jp
CROSS JOIN (VALUES
  ('AI Agent 开发工程师', 'JOB'),
  ('上海', 'LOCATION'),
  ('AI_AGENT', 'CATEGORY')
) AS v(cn, et)
WHERE jp.target_group='AI_AGENT' LIMIT 1;

-- JD 关系金标(REQUIRES)
INSERT INTO gold_jd_relations (jd_id, rel_type, source_canonical, target_canonical, annotator)
SELECT jp.jd_id, 'REQUIRES', 'AI Agent 应用工程师', v.skill, 'KAKA'
FROM job_postings jp
CROSS JOIN (VALUES
  ('Python'),
  ('LangChain'),
  ('RAG')
) AS v(skill)
WHERE jp.target_group='AI_AGENT';

-- 简历金标(候选人A):技能
INSERT INTO gold_resume_annotations (resume_id, field_kind, canonical_value, skill_level, annotator)
SELECT r.id, 'skill', v.skill, v.lvl::skill_level, 'KAKA'
FROM resumes r
CROSS JOIN (VALUES
  ('Python',    'PROFICIENT'),
  ('LangChain', 'BASIC')
) AS v(skill, lvl)
WHERE r.anon_name='候选人A';

-- 简历金标(候选人A):基本字段
INSERT INTO gold_resume_annotations (resume_id, field_kind, field_name, canonical_value, annotator)
SELECT r.id, 'basic_field', v.fname, v.fval, 'KAKA'
FROM resumes r
CROSS JOIN (VALUES
  ('education', '本科'),
  ('years_experience', '3'),
  ('target_job_group', 'AI_AGENT'),
  ('anon_label', '候选人A')
) AS v(fname, fval)
WHERE r.anon_name='候选人A';

-- 简历金标(候选人A):项目
INSERT INTO gold_resume_annotations (resume_id, field_kind, canonical_value, annotator)
SELECT r.id, 'project', '企业知识库问答系统', 'KAKA'
FROM resumes r WHERE r.anon_name='候选人A';

-- 匹配金标
INSERT INTO gold_matching (resume_id, target_job_group, match_level, missing_skills, covered_mandatory, path_reasonable, annotator)
SELECT r.id, 'AI_AGENT', 'MEDIUM', ARRAY['RAG'], ARRAY['Python','LangChain'], TRUE, 'KAKA'
FROM resumes r WHERE r.anon_name='候选人A';

INSERT INTO evaluations (eval_type, dataset_version, model_version, split, precision, recall, f1, score, detail)
VALUES ('jd_parse', 'v1', 'seed-model-0', 'test', 0.93, 0.90, 0.915, 0.915,
        '{"F1skill":0.92,"Accjob_field":0.90,"F1relation":0.88}'::jsonb);
