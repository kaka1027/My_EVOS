"""JD 解析评测:ScoreJD = 0.6·F1skill + 0.2·Accjob_field + 0.2·F1relation

比对系统从 JD 抽取的结果 vs 金标:
- 技能实体:按 canonical_name 对齐,算 precision/recall/F1
- 岗位字段(job_title/city/salary 等):按字段名算准确率(归一后精确匹配)
- 关系(REQUIRES):按 (source_canonical, target_canonical) 对对齐,算 F1

数据来源:
- 金标:gold_jd_entities + gold_jd_fields + gold_jd_relations
- 系统:relations(REQUIRES) + entities + job_postings(字段)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

@dataclass
class JDSkillGold:
    canonical: str
    category: Optional[str]
    level: Optional[str]
    req_type: Optional[str]

@dataclass
class JDRelationGold:
    source: str
    target: str
    rel_type: str

@dataclass
class JDFieldGold:
    field_name: str       # job_title / city / salary_range / ...
    canonical_value: str  # 归一后的值

def precision_recall_f1(sys_set: set, gold_set: set) -> dict:
    """通用 P/R/F1 计算。"""
    tp = len(sys_set & gold_set)
    fp = len(sys_set - gold_set)
    fn = len(gold_set - sys_set)
    prec = tp / (tp + fp) if (tp + fp) else (1.0 if not gold_set else 0.0)
    rec  = tp / (tp + fn) if (tp + fn) else (1.0 if not gold_set else 0.0)
    f1   = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {"precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "tp": tp, "fp": fp, "fn": fn}

def field_accuracy(sys_fields: dict[str, str], gold_fields: dict[str, str]) -> float:
    """字段准确率:归一后精确匹配。
    sys_fields / gold_fields: {field_name: canonical_value}
    """
    if not gold_fields:
        return 1.0 if not sys_fields else 0.0
    match = sum(1 for k, v in gold_fields.items() if sys_fields.get(k) == v)
    return round(match / len(gold_fields), 4)

def score_jd(sys_skills: set[str],
             sys_relations: set[tuple[str, str]],  # (source_canonical, target_canonical)
             sys_fields: dict[str, str],
             gold_skills: set[str],
             gold_relations: set[tuple[str, str]],
             gold_fields: dict[str, str]) -> dict:
    """计算 ScoreJD 及分项指标。

    返回:
        {
          "score_jd": float,
          "f1_skill": float,
          "acc_job_field": float,
          "f1_relation": float,
          "skill_metrics": {precision, recall, f1, tp, fp, fn},
          "relation_metrics": {...}
        }
    """
    skill_m = precision_recall_f1(sys_skills, gold_skills)
    rel_m   = precision_recall_f1(sys_relations, gold_relations)
    acc_field = field_accuracy(sys_fields, gold_fields)

    score = 0.6 * skill_m["f1"] + 0.2 * acc_field + 0.2 * rel_m["f1"]

    return {
        "score_jd": round(score, 4),
        "f1_skill": skill_m["f1"],
        "acc_job_field": acc_field,
        "f1_relation": rel_m["f1"],
        "skill_metrics": skill_m,
        "relation_metrics": rel_m
    }


# ============================================================
# 与 PostgreSQL 集成:从金标表 + 系统表取数
# ============================================================
def load_jd_gold_from_db(cur, jd_id: str) -> tuple[set[str], set[tuple], dict[str, str]]:
    """从 gold_jd_entities / gold_jd_relations / gold_jd_fields 取金标。"""
    # 技能
    cur.execute("""
        SELECT canonical_name FROM gold_jd_entities
        WHERE jd_id = %s AND entity_type = 'SKILL'
    """, (jd_id,))
    skills = {row[0] for row in cur.fetchall()}

    # 关系
    cur.execute("""
        SELECT source_canonical, target_canonical FROM gold_jd_relations
        WHERE jd_id = %s
    """, (jd_id,))
    rels = {(row[0], row[1]) for row in cur.fetchall()}

    # 字段:岗位标题、城市、目标方向等非实体字段
    cur.execute("""
        SELECT field_name, canonical_value FROM gold_jd_fields
        WHERE jd_id = %s
    """, (jd_id,))
    fields = {row[0]: row[1] for row in cur.fetchall()}

    return skills, rels, fields


def load_jd_system_from_db(cur, jd_id: str) -> tuple[set[str], set[tuple], dict[str, str]]:
    """从系统表取 JD 解析结果。

    技能:relations(REQUIRES) + entities
    关系:relations(REQUIRES) 的 (job_canonical, skill_canonical)
    字段:job_postings 的字段(job_title / city / target_group 等)
    """
    # 技能:该 JD 关联的 job_entity 的 REQUIRES 目标技能
    cur.execute("""
        SELECT DISTINCT s.canonical_name
        FROM job_postings jp
        JOIN relations r ON r.source_id = jp.job_entity_id AND r.rel_type = 'REQUIRES'
        JOIN entities s ON s.id = r.target_id
        WHERE jp.jd_id = %s AND r.status = 'active'
    """, (jd_id,))
    skills = {row[0] for row in cur.fetchall()}

    # 关系:(job_canonical, skill_canonical)
    cur.execute("""
        SELECT j.canonical_name, s.canonical_name
        FROM job_postings jp
        JOIN relations r ON r.source_id = jp.job_entity_id AND r.rel_type = 'REQUIRES'
        JOIN entities j ON j.id = r.source_id
        JOIN entities s ON s.id = r.target_id
        WHERE jp.jd_id = %s AND r.status = 'active'
    """, (jd_id,))
    rels = {(row[0], row[1]) for row in cur.fetchall()}

    # 字段:job_postings 的字段(这里只取 job_title / city / target_group,可按需扩展)
    cur.execute("""
        SELECT job_title, city, target_group::text
        FROM job_postings WHERE jd_id = %s
    """, (jd_id,))
    row = cur.fetchone()
    fields = {}
    if row:
        fields["job_title"] = row[0] or ""
        fields["city"] = row[1] or ""
        fields["target_group"] = row[2] or ""

    return skills, rels, fields
