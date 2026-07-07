"""EVOS 人岗匹配算法 (MVP)

对齐评测方案:ScoreMatch = 0.5*Acc_level + 0.3*F1_gap + 0.2*Acc_path
本模块产出 matching 侧的系统输出:匹配分、匹配等级、能力缺口、学习路径。
数据来源:PostgreSQL 事实主库 (relations 表 REQUIRES / HAS_SKILL / PREREQUISITE_OF)。

设计决策(已确认):
- 单技能等级分:级差分档 (>=要求=1.0, 低一级=0.5, 低两级及以上/缺失=0)
- 覆盖率加权:coverage = 0.8*必备均分 + 0.2*加分均分
- 匹配等级:总分阈值分档 (>=0.8 高, >=0.5 中, 否则低)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

# 等级 -> 数值
LEVEL_VALUE = {"BASIC": 1, "PROFICIENT": 2, "EXPERT": 3}

# 可调参数(集中放置,便于验证集调优)
MANDATORY_WEIGHT = 0.8
BONUS_WEIGHT = 0.2
LEVEL_MATCH = 1.0        # 等级达标
LEVEL_ONE_GAP = 0.5      # 低一级
LEVEL_HIGH = 0.8         # 高匹配阈值
LEVEL_MID = 0.5          # 中匹配阈值


@dataclass
class SkillReq:
    skill_id: str
    canonical: str
    required_level: str
    requirement_type: str    # MANDATORY / BONUS


@dataclass
class SkillHave:
    skill_id: str
    level: str


@dataclass
class SkillResult:
    canonical: str
    requirement_type: str
    required_level: str
    have_level: Optional[str]
    score: float
    status: str              # OK / INSUFFICIENT / MISSING


@dataclass
class MatchResult:
    job_name: str
    coverage: float
    match_level: str                       # HIGH / MEDIUM / LOW
    mandatory_avg: float
    bonus_avg: float
    skill_results: list[SkillResult] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)      # 缺失的必备技能 canonical
    learning_paths: dict[str, list[str]] = field(default_factory=dict)  # 缺失技能 -> 前置学习顺序


def level_match_score(need: str, have: Optional[str]) -> float:
    """级差分档打分。"""
    if have is None:
        return 0.0
    diff = LEVEL_VALUE[have] - LEVEL_VALUE[need]
    if diff >= 0:
        return LEVEL_MATCH
    if diff == -1:
        return LEVEL_ONE_GAP
    return 0.0


def score_status(need: str, have: Optional[str], s: float) -> str:
    if have is None:
        return "MISSING"
    if s >= LEVEL_MATCH:
        return "OK"
    return "INSUFFICIENT"


def compute_match(job_name: str,
                  reqs: list[SkillReq],
                  haves: list[SkillHave],
                  prereq_edges: dict[str, list[str]] | None = None,
                  skill_name: dict[str, str] | None = None) -> MatchResult:
    """核心匹配计算。

    reqs: 岗位 REQUIRES 的技能(含 level 与 必备/加分)
    haves: 候选人 HAS_SKILL 的技能与等级
    prereq_edges: {skill_id: [前置 skill_id, ...]},用于学习路径回溯
    skill_name: {skill_id: canonical},用于把 id 转可读名
    """
    have_map = {h.skill_id: h.level for h in haves}
    prereq_edges = prereq_edges or {}
    skill_name = skill_name or {}

    results: list[SkillResult] = []
    mand_scores, bonus_scores = [], []
    missing = []

    for r in reqs:
        have_lvl = have_map.get(r.skill_id)
        s = level_match_score(r.required_level, have_lvl)
        st = score_status(r.required_level, have_lvl, s)
        results.append(SkillResult(r.canonical, r.requirement_type,
                                   r.required_level, have_lvl, s, st))
        if r.requirement_type == "MANDATORY":
            mand_scores.append(s)
            if st == "MISSING":
                missing.append(r.canonical)
        else:
            bonus_scores.append(s)

    mand_avg = sum(mand_scores) / len(mand_scores) if mand_scores else 1.0
    bonus_avg = sum(bonus_scores) / len(bonus_scores) if bonus_scores else 0.0

    # 无加分技能时,覆盖率完全由必备决定
    if bonus_scores:
        coverage = MANDATORY_WEIGHT * mand_avg + BONUS_WEIGHT * bonus_avg
    else:
        coverage = mand_avg

    if coverage >= LEVEL_HIGH:
        level = "HIGH"
    elif coverage >= LEVEL_MID:
        level = "MEDIUM"
    else:
        level = "LOW"

    # 学习路径:对每个缺失/不足的必备技能,回溯 PREREQUISITE_OF 链
    # "已达标" = 拥有且等级达要求(级差分满分);未达标(缺失或不足)才进路径
    def is_satisfied(sid: str) -> bool:
        # 找该技能在 reqs 中的要求等级;找不到要求时按 have 是否存在判断
        need = next((r.required_level for r in reqs if r.skill_id == sid), None)
        have = have_map.get(sid)
        if need is None:
            return have is not None
        return level_match_score(need, have) >= LEVEL_MATCH

    paths: dict[str, list[str]] = {}
    gap_ids = [r.skill_id for r in reqs
               if r.requirement_type == "MANDATORY"
               and level_match_score(r.required_level, have_map.get(r.skill_id)) < LEVEL_MATCH]
    for gid in gap_ids:
        order = _prereq_chain(gid, prereq_edges, is_satisfied)
        name_chain = [skill_name.get(x, x) for x in order]
        paths[skill_name.get(gid, gid)] = name_chain

    return MatchResult(job_name, round(coverage, 4), level,
                       round(mand_avg, 4), round(bonus_avg, 4),
                       results, missing, paths)


def _prereq_chain(target: str, edges: dict[str, list[str]],
                  is_satisfied) -> list[str]:
    """回溯 target 的前置依赖链,返回建议学习顺序(前置在前)。
    已达标(拥有且等级够)的技能跳过,只列尚未达标的(含缺失与等级不足)。
    """
    order: list[str] = []
    seen = set()

    def dfs(node: str):
        if node in seen:
            return
        seen.add(node)
        for pre in edges.get(node, []):
            dfs(pre)
        if not is_satisfied(node):    # 未达标才列入学习路径
            order.append(node)

    dfs(target)
    return order


# ============================================================
# 与评测金标比对:Acc_level / F1_gap
# ============================================================
def eval_against_gold(system: MatchResult, gold_level: str,
                      gold_missing: list[str]) -> dict:
    """单样例评测。Acc_path 需人工评审,不在此计算。"""
    level_correct = int(system.match_level == gold_level)

    sys_gap = set(system.missing_skills)
    gold_gap = set(gold_missing)
    tp = len(sys_gap & gold_gap)
    fp = len(sys_gap - gold_gap)
    fn = len(gold_gap - sys_gap)
    prec = tp / (tp + fp) if (tp + fp) else (1.0 if not gold_gap else 0.0)
    rec = tp / (tp + fn) if (tp + fn) else (1.0 if not gold_gap else 0.0)
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

    return {"level_correct": level_correct,
            "gap_precision": round(prec, 4),
            "gap_recall": round(rec, 4),
            "gap_f1": round(f1, 4)}
