# EVOS 数据库设计决策记录

本文件记录 PG + Neo4j 数据库设计的 11 个核心决策及理由,配套 SQL/Cypher 见同目录。

## 决策总览

| # | 决策点 | 选择 | 理由 |
|---|--------|------|------|
| 1 | 权威数据源 | **PG 唯一事实源**,Neo4j 投影 | 单一事实源,契合文档"PG 可信事实主库";同步失败可降级为 PG 直出 nodes/edges |
| 2 | 实体异构属性 | **公共 entities 表 + 子类型表** | 强类型约束 + 可索引;关系表统一指向 entity_id |
| 3 | 技能 8 分类 vs 节点类型 | **Skill 为原子实体 + category 枚举** | 消除 Tool/Database 既是分类又是节点的矛盾;type={JOB,SKILL,TECHSTACK,SCENARIO,CERT,EVIDENCE,CANDIDATE} |
| 4 | 抽象 Job vs 原始 JD | **分离** | 300 条 JD 作证据留 job_postings;抽象 Job 承载 REQUIRES,支撑新岗位发现/演化 |
| 5 | 关系专属属性 | **relations 可空强类型列** | required_level / requirement_type 匹配算法直接查,不解 JSON |
| 6 | 关系-证据(图) | **evidence_ids 存边属性** | Neo4j 边不能连边;PG 侧用 relation_evidence 多对多为权威;图上点边回 PG 查原文 |
| 7 | 时间演化 | **当前关系 + skill_trends 快照表** | relations 只存当前态;趋势图查 skill_trends,新增/削弱靠相邻窗对比 |
| 8 | 技能别名/归一 | **canonical + 独立 skill_aliases 表** | 别名多对一映射 canonical_skill_id;评测/去重按 canonical 算,归一与 SIMILAR_TO 相似解耦 |
| 9 | 评测金标 + 划分 | **独立 gold_* 表 + dataset_splits 表** | 金标与系统产出物理隔离,防泄漏;split 映射 jd_id→train/valid/test |
| 10 | embedding | **按用途分表** | skill/jd/resume 各自固定维度和 HNSW 索引,聚类与匹配检索隔离 |
| 11 | PG→Neo4j 同步 | **异步任务批量 MERGE 投影** | 写 tasks 表;300 条量级全量重建也快;JD 流水线末步或手动触发 |

## 附加约定

- **主键**:UUID(gen_random_uuid) + 人可读 slug(如 `skill:langchain`),兼顾分布式与调试可读
- **删除**:软删除,`status` 枚举(active/deprecated/deleted)+ valid_to,保留演化/溯源历史
- **置信度**:relations.confidence 存 0–1 聚合总分;多源明细拆到 relation_evidence.source_score
- **生成来源**:entities/relations 带 created_by 枚举(rule/ner/embedding/llm/human),支撑幻觉防控与分来源评估

## 投影契约 (PG → Neo4j)

- 节点:pg_id(=entities.id)唯一约束,冗余 name/canonical_name/category/status
- 边:冗余 weight/confidence/required_level/requirement_type/evidence_ids/valid_from/valid_to
- 只投影 status='active' 的实体与关系;失效关系在全量重建时按 active_ids 集合删除
- 图算法(REQUIRES 缺口、PREREQUISITE_OF 路径)与 G6 可视化不回查 PG,仅点证据时回查

## 评测口径映射 (对齐评测方案文档)

- **ScoreJD** = 0.6·F1skill + 0.2·Accjob_field + 0.2·F1relation
  → gold_jd_entities(技能/字段) + gold_jd_relations(关系),按 canonical 对齐算 TP/FP/FN
- **ScoreResume** = 0.5·F1resume_skill + 0.3·Accbasic_field + 0.2·Accproject
  → gold_resume_annotations(field_kind = skill/basic_field/project)
- **ScoreMatch** = 0.5·Acclevel + 0.3·F1gap + 0.2·Accpath
  → gold_matching(match_level / missing_skills / path_reasonable)
- 结果写 evaluations 表,绑定 dataset_version + model_version + split;错误样例写 error_cases

---

## 实现进展 (2026-07-08)

### 1. Schema + 种子数据验证(真机)

**环境**:临时 PostgreSQL 18.4 实例(conda evos_pg)  
**验证范围**:
- Schema 建表(12 枚举 + 全部业务表,跳过 3 张 embedding 表因本机无 pgvector 服务端扩展)
- 种子数据导入(17 实体 / 23 关系 / 2 JD / 3 别名 / 3 趋势快照)
- 8 条验证查询(岗位能力图谱 / 别名归一 / 多源证据 / 人岗缺口 / 学习路径 / 趋势 / 软删除)

**修复的 Bug**:`relation_evidence.source_kind` 原用 `created_source` 枚举(rule/ner/llm/human),应为 `evidence_source`(jd/github/paper/doc/blog/human)。纸面看不出,导入时炸出。已修正 schema。

**结论**:Schema 全量可运行,关系图谱结构成立,外键 + 枚举约束全通过。

---

### 2. 匹配算法实现与验证

**位置**:`matching/match_algorithm.py` + `matching/run_matching.py`

**确定的公式**(已落地):
1. **单技能等级分**:级差分档
   - 拥有等级 ≥ 要求 → 1.0
   - 低一级 → 0.5
   - 低两级及以上 / 缺失 → 0.0
   - BASIC/PROFICIENT/EXPERT 映射为 1/2/3

2. **覆盖率加权**:必备/加分分组加权
   ```
   coverage = 0.8 × 必备技能均分 + 0.2 × 加分技能均分
   ```
   无加分技能时,覆盖率 = 必备均分

3. **匹配等级划分**:总分阈值分档
   - coverage ≥ 0.8 → HIGH
   - 0.5 ≤ coverage < 0.8 → MEDIUM
   - coverage < 0.5 → LOW

4. **学习路径**:按 PREREQUISITE_OF 回溯,跳过已达标技能(拥有且等级满足要求),保留缺失/等级不足的技能

**真机验证结果**(候选人A vs AI Agent 岗位):
- 必备均分 = 0.5 (Python 1.0 + RAG 0.0 + LangChain 0.5) / 3
- 加分均分 = 0.5 (Prompt 0.0 + Docker 1.0) / 2
- 覆盖率 = 0.5 → **MEDIUM** ✓
- 缺失必备 = [RAG] ✓
- 学习路径 RAG: `LangChain → RAG` ✓ (Python 已达标跳过)
- 与金标比对:**等级命中=1, 缺口 F1=1.0** ✓

**可调参数**(位于 `match_algorithm.py` 顶部,需用验证集调优):
- `MANDATORY_WEIGHT = 0.8` / `BONUS_WEIGHT = 0.2`
- `LEVEL_HIGH = 0.8` / `LEVEL_MID = 0.5`
- `LEVEL_MATCH = 1.0` / `LEVEL_ONE_GAP = 0.5`

**评测函数**:`eval_against_gold()` 已实现,产出 `level_correct` / `gap_precision` / `gap_recall` / `gap_f1`。Acc_path 需人工评审,未自动化。

---

### 3. JD 解析与简历提取评测

**位置**:`matching/eval_jd.py` + `matching/eval_resume.py` + `matching/run_eval_jd_resume.py`

**ScoreJD 实现**:
- 技能实体:按 canonical_name 对齐,算 P/R/F1
- 岗位字段(job_title/city/target_group):归一后精确匹配,算 Acc
- 关系(REQUIRES):按 (source_canonical, target_canonical) 对对齐,算 F1
- 公式:`ScoreJD = 0.6·F1skill + 0.2·Accjob_field + 0.2·F1relation`

**ScoreResume 实现**:
- 技能:按 canonical_name 对齐,算 P/R/F1
- 基本字段(education/years_experience/target_job_group/anon_label):归一后精确匹配,算 Acc
- 项目:按 project_name 归一后匹配,算 Acc
- 公式:`ScoreResume = 0.5·F1resume_skill + 0.3·Accbasic_field + 0.2·Accproject`

**真机验证结果**(AI Agent JD + 候选人A):
- **JD 解析**:ScoreJD=0.8 (F1skill=0.75, Acc_field=1.0, F1rel=0.75)
  - 金标 3 必备技能全召回,系统多抽 2 加分技能 → Precision=0.6
  - 岗位字段(job_title)完全匹配 ✓
- **简历提取**:ScoreResume=0.9 (F1skill=0.8, Acc_field=1.0, Acc_proj=1.0)
  - 金标 2 技能全召回,系统多抽 1 技能(Docker) → Precision=0.67
  - 基本字段 4/4 全匹配 ✓,项目名匹配 ✓

**已知问题**:
- 金标只标了必备技能,未标加分技能 → 系统抽出加分技能算 FP,压低 F1。完整评测需在金标中标注全部技能(含加分),或评测前过滤掉系统的加分技能。
- JD 字段金标已拆到 `gold_jd_fields(field_name, canonical_value)`,不再复用 `gold_jd_entities.entity_type`,避免 LOCATION/CATEGORY 与实体枚举冲突。

---

## 下一步

1. **扩展种子数据**:造更多测试简历(高/中/低三档各若干),压测匹配算法区分度
2. **完善评测脚本**:补全 ScoreJD(JD 解析评测)与 ScoreResume(简历提取评测)
3. **验证集调优**:用 60 条 JD 调匹配算法权重与阈值(切忌在测试集上调)
4. **Neo4j 投影验证**:用 `02_neo4j_projection.cypher` 建图,验证 Cypher 路径查询与可视化
