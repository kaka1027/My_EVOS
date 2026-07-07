"""运行 JD 解析和简历提取评测,打印结果。"""
import os
import psycopg2
from eval_jd import load_jd_gold_from_db, load_jd_system_from_db, score_jd
from eval_resume import load_resume_gold_from_db, load_resume_system_from_db, score_resume

DSN = dict(host=os.environ.get("PGHOST", "127.0.0.1"),
           port=int(os.environ.get("PGPORT", "54329")),
           user=os.environ.get("PGUSER", "postgres"),
           dbname=os.environ.get("PGDATABASE", "evos"))


def main():
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()

    # ========== JD 评测 ==========
    # 找到 AI Agent JD 的 jd_id
    cur.execute("SELECT jd_id FROM job_postings WHERE target_group='AI_AGENT' LIMIT 1")
    jd_id = cur.fetchone()[0]

    gold_skills, gold_rels, gold_fields = load_jd_gold_from_db(cur, jd_id)
    sys_skills, sys_rels, sys_fields = load_jd_system_from_db(cur, jd_id)

    # 注意:金标的字段用的是 entity_type(JOB/LOCATION/CATEGORY),系统用的是 job_title/city/target_group
    # 需要做个映射。这里简化:直接手工对齐金标与系统的字段名
    # 金标 fields: {'job': 'AI Agent 开发工程师', 'location': '上海', 'category': 'AI_AGENT'}
    # 系统 fields: {'job_title': '...', 'city': '...', 'target_group': 'AI_AGENT'}
    # 映射后统一字段名
    gold_fields_mapped = {}
    sys_fields_mapped = {}
    for entity_type, val in gold_fields.items():
        if entity_type == 'job':
            gold_fields_mapped['job_title'] = val
        elif entity_type == 'location':
            gold_fields_mapped['city'] = val
        elif entity_type == 'category':
            gold_fields_mapped['target_group'] = val
    sys_fields_mapped = sys_fields  # 系统字段已经是标准名

    result_jd = score_jd(sys_skills, sys_rels, sys_fields_mapped,
                         gold_skills, gold_rels, gold_fields_mapped)

    print("=" * 60)
    print("JD 解析评测 (AI Agent JD)")
    print("=" * 60)
    print(f"ScoreJD: {result_jd['score_jd']}")
    print(f"  - F1 Skill:        {result_jd['f1_skill']}")
    print(f"  - Acc Job Field:   {result_jd['acc_job_field']}")
    print(f"  - F1 Relation:     {result_jd['f1_relation']}")
    print("-" * 60)
    print("技能指标:", result_jd['skill_metrics'])
    print("关系指标:", result_jd['relation_metrics'])
    print("-" * 60)
    print(f"金标技能({len(gold_skills)}): {gold_skills}")
    print(f"系统技能({len(sys_skills)}): {sys_skills}")
    print(f"金标关系({len(gold_rels)}): {gold_rels}")
    print(f"系统关系({len(sys_rels)}): {sys_rels}")
    print(f"金标字段: {gold_fields_mapped}")
    print(f"系统字段: {sys_fields_mapped}")

    # ========== 简历评测 ==========
    cur.execute("SELECT id FROM resumes WHERE anon_name='候选人A'")
    resume_id = cur.fetchone()[0]

    gold_r_skills, gold_r_fields, gold_r_projects = load_resume_gold_from_db(cur, resume_id)
    sys_r_skills, sys_r_fields, sys_r_projects = load_resume_system_from_db(cur, resume_id)

    result_resume = score_resume(sys_r_skills, sys_r_fields, sys_r_projects,
                                  gold_r_skills, gold_r_fields, gold_r_projects)

    print("\n" + "=" * 60)
    print("简历提取评测 (候选人A)")
    print("=" * 60)
    print(f"ScoreResume: {result_resume['score_resume']}")
    print(f"  - F1 Resume Skill:  {result_resume['f1_resume_skill']}")
    print(f"  - Acc Basic Field:  {result_resume['acc_basic_field']}")
    print(f"  - Acc Project:      {result_resume['acc_project']}")
    print("-" * 60)
    print("技能指标:", result_resume['skill_metrics'])
    print("-" * 60)
    print(f"金标技能({len(gold_r_skills)}): {gold_r_skills}")
    print(f"系统技能({len(sys_r_skills)}): {sys_r_skills}")
    print(f"金标字段: {gold_r_fields}")
    print(f"系统字段: {sys_r_fields}")
    print(f"金标项目: {gold_r_projects}")
    print(f"系统项目: {sys_r_projects}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
