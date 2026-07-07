"""从 PostgreSQL 取数并运行人岗匹配,打印结果并与金标比对。"""
import os
import psycopg2
import psycopg2.extras
from match_algorithm import (SkillReq, SkillHave, compute_match,
                             eval_against_gold)

DSN = dict(host=os.environ.get("PGHOST", "127.0.0.1"),
           port=int(os.environ.get("PGPORT", "54329")),
           user=os.environ.get("PGUSER", "postgres"),
           dbname=os.environ.get("PGDATABASE", "evos"))


def load_reqs(cur, job_slug):
    cur.execute("""
        SELECT s.id::text, s.canonical_name, r.required_level, r.requirement_type
        FROM relations r
        JOIN entities j ON j.id = r.source_id AND j.slug = %s
        JOIN entities s ON s.id = r.target_id
        WHERE r.rel_type = 'REQUIRES' AND r.status = 'active'
    """, (job_slug,))
    return [SkillReq(*row) for row in cur.fetchall()]


def load_haves(cur, cand_slug):
    cur.execute("""
        SELECT s.id::text, r.required_level
        FROM relations r
        JOIN entities c ON c.id = r.source_id AND c.slug = %s
        JOIN entities s ON s.id = r.target_id
        WHERE r.rel_type = 'HAS_SKILL' AND r.status = 'active'
    """, (cand_slug,))
    return [SkillHave(*row) for row in cur.fetchall()]


def load_prereq(cur):
    cur.execute("""
        SELECT b.id::text AS target, a.id::text AS pre
        FROM relations r
        JOIN entities a ON a.id = r.source_id
        JOIN entities b ON b.id = r.target_id
        WHERE r.rel_type = 'PREREQUISITE_OF' AND r.status = 'active'
    """)
    edges = {}
    for target, pre in cur.fetchall():
        edges.setdefault(target, []).append(pre)
    return edges


def load_skill_names(cur):
    cur.execute("SELECT id::text, canonical_name FROM entities WHERE type='SKILL'")
    return dict(cur.fetchall())


def main():
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()

    job_slug = "job:ai-agent-engineer"
    cand_slug = "cand:a"

    reqs = load_reqs(cur, job_slug)
    haves = load_haves(cur, cand_slug)
    prereq = load_prereq(cur)
    names = load_skill_names(cur)

    cur.execute("SELECT name FROM entities WHERE slug=%s", (job_slug,))
    job_name = cur.fetchone()[0]

    result = compute_match(job_name, reqs, haves, prereq, names)

    print("=" * 56)
    print(f"岗位: {result.job_name}   候选人: {cand_slug}")
    print(f"覆盖率: {result.coverage}  (必备均分 {result.mandatory_avg} / 加分均分 {result.bonus_avg})")
    print(f"匹配等级: {result.match_level}")
    print("-" * 56)
    print(f"{'技能':<14}{'类型':<11}{'要求':<11}{'拥有':<11}{'分':>5}  状态")
    for r in result.skill_results:
        have = r.have_level or "-"
        print(f"{r.canonical:<12}{r.requirement_type:<11}{r.required_level:<11}{have:<11}{r.score:>5}  {r.status}")
    print("-" * 56)
    print("缺失必备技能:", result.missing_skills)
    print("学习路径建议:")
    for gap, path in result.learning_paths.items():
        print(f"  {gap}: {' -> '.join(path) if path else '(前置已全部掌握,可直接学)'}")

    # 与金标比对
    cur.execute("""
        SELECT match_level, missing_skills
        FROM gold_matching gm
        JOIN resumes rs ON rs.id = gm.resume_id
        WHERE rs.anon_name = '候选人A'
    """)
    gold_level, gold_missing = cur.fetchone()
    metrics = eval_against_gold(result, gold_level, list(gold_missing))
    print("=" * 56)
    print(f"金标: 等级={gold_level}  缺失={list(gold_missing)}")
    print(f"评测: 等级命中={metrics['level_correct']}  "
          f"缺口F1={metrics['gap_f1']} "
          f"(P={metrics['gap_precision']}, R={metrics['gap_recall']})")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
