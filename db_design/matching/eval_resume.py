"""简历提取评测:ScoreResume = 0.5·F1resume_skill + 0.3·Accbasic_field + 0.2·Accproject

比对系统从简历抽取的结果 vs 金标:
- 技能:按 canonical_name 对齐,算 precision/recall/F1
- 基本字段(education/years_experience/target_job_group 等):按字段名算准确率
- 项目:按 project_name 匹配,算准确率(归一后精确匹配或模糊匹配)

数据来源:
- 金标:gold_resume_annotations(field_kind = skill/basic_field/project)
- 系统:relations(HAS_SKILL) + candidates + resume_projects
"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class ResumeSkillGold:
    canonical: str
    level: str | None

@dataclass
class ResumeFieldGold:
    field_name: str       # education / years_experience / target_job_group / anon_label
    canonical_value: str

@dataclass
class ResumeProjectGold:
    project_name: str     # 项目名(归一后)
    role_desc: str | None
    tech_used: str | None

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
    """字段准确率:归一后精确匹配。"""
    if not gold_fields:
        return 1.0 if not sys_fields else 0.0
    match = sum(1 for k, v in gold_fields.items() if sys_fields.get(k) == v)
    return round(match / len(gold_fields), 4)

def project_accuracy(sys_projects: set[str], gold_projects: set[str]) -> float:
    """项目准确率:按 project_name 匹配(归一后精确匹配)。"""
    if not gold_projects:
        return 1.0 if not sys_projects else 0.0
    match = len(sys_projects & gold_projects)
    return round(match / len(gold_projects), 4)

def score_resume(sys_skills: set[str],
                 sys_fields: dict[str, str],
                 sys_projects: set[str],
                 gold_skills: set[str],
                 gold_fields: dict[str, str],
                 gold_projects: set[str]) -> dict:
    """计算 ScoreResume 及分项指标。

    返回:
        {
          "score_resume": float,
          "f1_resume_skill": float,
          "acc_basic_field": float,
          "acc_project": float,
          "skill_metrics": {precision, recall, f1, tp, fp, fn}
        }
    """
    skill_m = precision_recall_f1(sys_skills, gold_skills)
    acc_field = field_accuracy(sys_fields, gold_fields)
    acc_proj  = project_accuracy(sys_projects, gold_projects)

    score = 0.5 * skill_m["f1"] + 0.3 * acc_field + 0.2 * acc_proj

    return {
        "score_resume": round(score, 4),
        "f1_resume_skill": skill_m["f1"],
        "acc_basic_field": acc_field,
        "acc_project": acc_proj,
        "skill_metrics": skill_m
    }


# ============================================================
# 与 PostgreSQL 集成:从金标表 + 系统表取数
# ============================================================
def load_resume_gold_from_db(cur, resume_id: str) -> tuple[set[str], dict[str, str], set[str]]:
    """从 gold_resume_annotations 取金标,按 field_kind 分组。"""
    # 技能
    cur.execute("""
        SELECT canonical_value FROM gold_resume_annotations
        WHERE resume_id = %s AND field_kind = 'skill'
    """, (resume_id,))
    skills = {row[0] for row in cur.fetchall()}

    # 基本字段
    cur.execute("""
        SELECT field_name, canonical_value FROM gold_resume_annotations
        WHERE resume_id = %s AND field_kind = 'basic_field'
    """, (resume_id,))
    fields = {row[0]: row[1] for row in cur.fetchall()}

    # 项目
    cur.execute("""
        SELECT canonical_value FROM gold_resume_annotations
        WHERE resume_id = %s AND field_kind = 'project'
    """, (resume_id,))
    projects = {row[0] for row in cur.fetchall()}

    return skills, fields, projects


def load_resume_system_from_db(cur, resume_id: str) -> tuple[set[str], dict[str, str], set[str]]:
    """从系统表取简历解析结果。

    技能:relations(HAS_SKILL) + entities
    字段:candidates 表字段(education / years_experience / target_job_group / anon_label)
    项目:resume_projects 的 project_name
    """
    # 技能:该简历对应 candidate 的 HAS_SKILL 关系
    cur.execute("""
        SELECT DISTINCT s.canonical_name
        FROM candidates c
        JOIN relations r ON r.source_id = c.entity_id AND r.rel_type = 'HAS_SKILL'
        JOIN entities s ON s.id = r.target_id
        WHERE c.resume_id = %s AND r.status = 'active'
    """, (resume_id,))
    skills = {row[0] for row in cur.fetchall()}

    # 字段:candidates 表
    cur.execute("""
        SELECT education, years_experience, target_job_group::text, anon_label
        FROM candidates WHERE resume_id = %s
    """, (resume_id,))
    row = cur.fetchone()
    fields = {}
    if row:
        fields["education"] = row[0] or ""
        # years_experience 转整数字符串(去掉 .0)
        fields["years_experience"] = str(int(row[1])) if row[1] is not None else ""
        fields["target_job_group"] = row[2] or ""
        fields["anon_label"] = row[3] or ""

    # 项目:resume_projects 的 project_name
    cur.execute("""
        SELECT project_name FROM resume_projects WHERE resume_id = %s
    """, (resume_id,))
    projects = {row[0] for row in cur.fetchall()}

    return skills, fields, projects
