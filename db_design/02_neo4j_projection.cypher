// ============================================================
// EVOS Neo4j 投影层 (由 PG 异步任务批量 MERGE 生成)
// 权威源:PostgreSQL。Neo4j 只做图查询/图算法/G6 可视化。
// 节点主键:pg_id (= PG entities.id)。边冗余匹配算法所需属性。
// ============================================================

// ------------------------------------------------------------
// 1. 唯一约束 + 索引 (每类节点用 pg_id 唯一)
// ------------------------------------------------------------
CREATE CONSTRAINT job_pg_id       IF NOT EXISTS FOR (n:Job)       REQUIRE n.pg_id IS UNIQUE;
CREATE CONSTRAINT skill_pg_id     IF NOT EXISTS FOR (n:Skill)     REQUIRE n.pg_id IS UNIQUE;
CREATE CONSTRAINT techstack_pg_id IF NOT EXISTS FOR (n:TechStack) REQUIRE n.pg_id IS UNIQUE;
CREATE CONSTRAINT scenario_pg_id  IF NOT EXISTS FOR (n:Scenario)  REQUIRE n.pg_id IS UNIQUE;
CREATE CONSTRAINT cert_pg_id      IF NOT EXISTS FOR (n:Cert)      REQUIRE n.pg_id IS UNIQUE;
CREATE CONSTRAINT candidate_pg_id IF NOT EXISTS FOR (n:Candidate) REQUIRE n.pg_id IS UNIQUE;

// 展示/筛选常用索引
CREATE INDEX skill_category IF NOT EXISTS FOR (n:Skill) ON (n.category);
CREATE INDEX skill_canon    IF NOT EXISTS FOR (n:Skill) ON (n.canonical_name);

// ------------------------------------------------------------
// 2. 节点投影 (以 Skill 为例;其余类型同构)
//    冗余展示属性:name / canonical_name / category / status
//    $rows 由投影任务从 PG 批量传入
// ------------------------------------------------------------
UNWIND $skill_rows AS row
MERGE (s:Skill {pg_id: row.entity_id})
SET s.name           = row.name,
    s.canonical_name = row.canonical_name,
    s.category       = row.category,
    s.status         = row.status;

UNWIND $job_rows AS row
MERGE (j:Job {pg_id: row.entity_id})
SET j.name        = row.name,
    j.target_group = row.target_group,
    j.is_emerging  = row.is_emerging,
    j.status       = row.status;

// TechStack / Scenario / Cert / Candidate 投影同理,略。

// ------------------------------------------------------------
// 3. 关系投影 (边冗余匹配算法所需属性 + evidence_ids)
//    只投影 PG 中 status='active' 的关系
// ------------------------------------------------------------

// 3.1 岗位 REQUIRES 技能 (带 required_level / requirement_type)
UNWIND $requires_rows AS row
MATCH (j:Job   {pg_id: row.source_id})
MATCH (s:Skill {pg_id: row.target_id})
MERGE (j)-[r:REQUIRES]->(s)
SET r.pg_id            = row.relation_id,
    r.weight           = row.weight,
    r.confidence       = row.confidence,
    r.required_level   = row.required_level,
    r.requirement_type = row.requirement_type,
    r.evidence_ids     = row.evidence_ids,      // int/uuid 数组,点边时回 PG 查原文
    r.evidence_count   = row.evidence_count,
    r.valid_from       = row.valid_from,
    r.valid_to         = row.valid_to;

// 3.2 技能 BELONGS_TO 技术栈
UNWIND $belongs_rows AS row
MATCH (s:Skill     {pg_id: row.source_id})
MATCH (t:TechStack {pg_id: row.target_id})
MERGE (s)-[r:BELONGS_TO]->(t)
SET r.pg_id = row.relation_id, r.confidence = row.confidence, r.evidence_ids = row.evidence_ids;

// 3.3 技能 PREREQUISITE_OF 技能 (学习路径推理用)
UNWIND $prereq_rows AS row
MATCH (a:Skill {pg_id: row.source_id})
MATCH (b:Skill {pg_id: row.target_id})
MERGE (a)-[r:PREREQUISITE_OF]->(b)
SET r.pg_id = row.relation_id, r.confidence = row.confidence, r.weight = row.weight;

// 3.4 技能 USED_IN 场景
UNWIND $usedin_rows AS row
MATCH (s:Skill    {pg_id: row.source_id})
MATCH (sc:Scenario{pg_id: row.target_id})
MERGE (s)-[r:USED_IN]->(sc)
SET r.pg_id = row.relation_id, r.confidence = row.confidence;

// 3.5 技能 SIMILAR_TO 技能 (相似,非等价别名;别名在 PG skill_aliases)
UNWIND $similar_rows AS row
MATCH (a:Skill {pg_id: row.source_id})
MATCH (b:Skill {pg_id: row.target_id})
MERGE (a)-[r:SIMILAR_TO]->(b)
SET r.pg_id = row.relation_id, r.weight = row.weight;

// 3.6 候选人 HAS_SKILL 技能 (带实际熟练度)
UNWIND $hasskill_rows AS row
MATCH (c:Candidate {pg_id: row.source_id})
MATCH (s:Skill     {pg_id: row.target_id})
MERGE (c)-[r:HAS_SKILL]->(s)
SET r.pg_id = row.relation_id, r.required_level = row.required_level, r.confidence = row.confidence;

// ------------------------------------------------------------
// 4. 全量重建时清理失效关系 (PG 软删除 -> Neo4j 删边)
//    投影任务传入当前 active 的 relation pg_id 集合 $active_ids
// ------------------------------------------------------------
// MATCH ()-[r]->() WHERE NOT r.pg_id IN $active_ids DELETE r;

// ============================================================
// 5. 典型查询模板 (供 Service 层调用)
// ============================================================

// 5.1 某岗位的能力图谱 (必备/加分 + 技能所属技术栈)
// MATCH (j:Job {pg_id:$job_id})-[req:REQUIRES]->(s:Skill)
// OPTIONAL MATCH (s)-[:BELONGS_TO]->(t:TechStack)
// RETURN j, req, s, t;

// 5.2 人岗匹配:候选人已有技能 vs 岗位必备技能的缺口
// MATCH (j:Job {pg_id:$job_id})-[req:REQUIRES {requirement_type:'MANDATORY'}]->(s:Skill)
// OPTIONAL MATCH (c:Candidate {pg_id:$cand_id})-[has:HAS_SKILL]->(s)
// RETURN s.canonical_name AS skill,
//        req.required_level AS need,
//        has.required_level AS have,
//        (has IS NULL)      AS is_gap;

// 5.3 学习路径:缺失技能的前置依赖链 (拓扑)
// MATCH (j:Job {pg_id:$job_id})-[:REQUIRES]->(target:Skill)
// WHERE NOT EXISTS { MATCH (:Candidate {pg_id:$cand_id})-[:HAS_SKILL]->(target) }
// MATCH path = (base:Skill)-[:PREREQUISITE_OF*0..]->(target)
// RETURN target.canonical_name, [n IN nodes(path) | n.canonical_name] AS learn_order;
