"""학과별 전공필수/전공선택/전공기초 등 요건 데이터를 Supabase에서 뽑아 엑셀로 만든다.
사람이 학과별로 데이터가 제대로 들어갔는지 스프레드시트로 훑어볼 때 쓴다.

실행:
    DATABASE_URL=... python -m scripts.export_department_requirements_report [출력경로.xlsx]
"""
import os
import sys

import pandas as pd
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ["DATABASE_URL"]
OUTPUT_PATH = sys.argv[1] if len(sys.argv) > 1 else "requirement_courses_by_department.xlsx"

CATEGORY_LABELS = {
    "major_required": "전공필수",
    "major_elective": "전공선택",
    "major_foundation": "전공기초",
    "deep_major": "심화전공",
    "minimum_major_total": "최소전공(합계)",
    "major_total": "전공합계",
    "general_total": "교양합계",
    "general_required": "교양필수",
    "general_elective_area": "교양선택",
    "general_core": "효원핵심",
    "general_balanced": "효원균형",
    "general_creative": "효원창의",
    "free_elective": "일반선택",
    "teacher_training": "교직",
    "minor_total": "부전공총학점",
    "dual_major_total": "복수전공총학점",
    "unknown": "미분류",
}
PROGRAM_TYPE_LABELS = {
    "primary": "주전공",
    "dual": "복수전공",
    "minor": "부전공",
    "contract": "계약학과",
    "advanced_major": "심화전공",
}

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

with engine.connect() as conn:
    categories_df = pd.read_sql(
        text(
            """
            select coalesce(rc.program_name, rs.major) as program_name,
                   rs.program_type, rs.academic_program_code,
                   rc.category_code, rc.category_name, rc.minimum_credits,
                   rc.rule_type, rc.needs_review
            from requirement_categories rc
            join requirement_sets rs on rs.id = rc.requirement_set_id
            order by 1, rs.program_type, rc.category_code
            """
        ),
        conn,
    )

    courses_df = pd.read_sql(
        text(
            """
            select coalesce(rcs.program_name, rs.major) as program_name,
                   rs.program_type, rs.academic_program_code,
                   rcs.category_code, rcs.raw_course_code, rcs.raw_course_name,
                   rcs.raw_credit, rcs.matched_course_code, rcs.matched_course_name,
                   rcs.match_status, rcs.needs_review, rcs.review_reason,
                   rcs.recommended_year, rcs.recommended_semester, rcs.source_file
            from requirement_courses rcs
            join requirement_sets rs on rs.id = rcs.requirement_set_id
            order by 1, rs.program_type, rcs.category_code, rcs.raw_course_name
            """
        ),
        conn,
    )

    sets_df = pd.read_sql(
        text(
            """
            select rs.major as program_name, rs.program_type, rs.academic_program_code,
                   rs.curriculum_year, rs.required_total_credits, rs.department
            from requirement_sets rs
            order by 1, rs.program_type
            """
        ),
        conn,
    )

for df in (categories_df, courses_df):
    df["category_label"] = df["category_code"].map(CATEGORY_LABELS).fillna(df["category_code"])
for df in (categories_df, courses_df, sets_df):
    df["program_type_label"] = df["program_type"].map(PROGRAM_TYPE_LABELS).fillna(df["program_type"])

# --- 요약: 학과 x 프로그램타입 x 카테고리별 과목수/매칭/검토 현황 ---
target_categories = {"major_required", "major_elective", "major_foundation", "deep_major"}
course_summary = (
    courses_df.assign(is_target=courses_df["category_code"].isin(target_categories))
    .groupby(["program_name", "program_type_label", "category_label"], dropna=False)
    .agg(
        과목수=("raw_course_name", "count"),
        매칭됨=("match_status", lambda s: (s == "matched").sum()),
        모호함=("match_status", lambda s: (s == "ambiguous").sum()),
        미매칭=("match_status", lambda s: (s == "unmatched").sum()),
        검토완료=("needs_review", lambda s: (~s).sum()),
    )
    .reset_index()
    .rename(columns={"program_name": "학과", "program_type_label": "구분", "category_label": "카테고리"})
)

category_min_credits = categories_df[
    categories_df["category_code"].isin(target_categories)
][
    ["program_name", "program_type_label", "category_label", "minimum_credits", "rule_type", "needs_review"]
].rename(
    columns={
        "program_name": "학과",
        "program_type_label": "구분",
        "category_label": "카테고리",
        "minimum_credits": "최소학점기준",
        "rule_type": "규칙유형",
        "needs_review": "검토필요",
    }
)

summary = course_summary.merge(
    category_min_credits, on=["학과", "구분", "카테고리"], how="outer"
).sort_values(["학과", "구분", "카테고리"])

# 학과 x 구분 단위로 전필/전선/기초 자체가 아예 없는(0건) 케이스만 따로 뽑아 우선순위 확인용으로 제공
pivot = summary.pivot_table(
    index=["학과", "구분"], columns="카테고리", values="과목수", aggfunc="sum", fill_value=0
).reset_index()
missing_flag_cols = [c for c in ["전공필수", "전공선택", "전공기초"] if c in pivot.columns]
if missing_flag_cols:
    pivot["결측(전필/전선/기초 중 0건 있음)"] = (pivot[missing_flag_cols] == 0).any(axis=1)
    missing_only = pivot[pivot["결측(전필/전선/기초 중 0건 있음)"]].sort_values(["학과", "구분"])
else:
    missing_only = pivot

courses_display = courses_df.rename(
    columns={
        "program_name": "학과",
        "program_type_label": "구분",
        "category_label": "카테고리",
        "raw_course_code": "원문과목코드",
        "raw_course_name": "원문과목명",
        "raw_credit": "원문학점",
        "matched_course_code": "매칭과목코드",
        "matched_course_name": "매칭과목명",
        "match_status": "매칭상태",
        "needs_review": "검토필요",
        "review_reason": "검토사유",
        "recommended_year": "권장학년",
        "recommended_semester": "권장학기",
        "source_file": "출처파일",
    }
)[
    [
        "학과", "구분", "카테고리", "원문과목코드", "원문과목명", "원문학점",
        "매칭과목코드", "매칭과목명", "매칭상태", "검토필요", "검토사유",
        "권장학년", "권장학기", "출처파일",
    ]
]

sets_display = sets_df.rename(
    columns={
        "program_name": "학과",
        "program_type_label": "구분",
        "academic_program_code": "학사프로그램코드",
        "curriculum_year": "교육과정연도",
        "required_total_credits": "졸업총학점",
        "department": "단과대학/학과원문",
    }
)[["학과", "구분", "학사프로그램코드", "단과대학/학과원문", "교육과정연도", "졸업총학점"]]

with pd.ExcelWriter(OUTPUT_PATH, engine="openpyxl") as writer:
    summary.to_excel(writer, sheet_name="1_요약(학과x카테고리)", index=False)
    missing_only.to_excel(writer, sheet_name="2_결측의심(전필전선기초0건)", index=False)
    sets_display.to_excel(writer, sheet_name="3_요건세트목록", index=False)
    courses_display.to_excel(writer, sheet_name="4_전체과목목록", index=False)

# 열 너비 자동 조정 (대충)
from openpyxl import load_workbook

wb = load_workbook(OUTPUT_PATH)
for ws in wb.worksheets:
    for col_cells in ws.columns:
        length = max((len(str(c.value)) if c.value is not None else 0) for c in col_cells)
        col_letter = col_cells[0].column_letter
        ws.column_dimensions[col_letter].width = min(max(length + 2, 10), 45)
    ws.freeze_panes = "A2"
wb.save(OUTPUT_PATH)

print(f"저장 완료: {OUTPUT_PATH}")
print(f"  요약 행수: {len(summary)}")
print(f"  결측의심 행수: {len(missing_only)}")
print(f"  요건세트 행수: {len(sets_display)}")
print(f"  전체과목 행수: {len(courses_display)}")
