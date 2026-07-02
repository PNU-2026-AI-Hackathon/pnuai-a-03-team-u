"""비교과 활동 추천 정확도 오프라인 평가.

실사용(클릭/지원) 데이터가 없으므로, 전공/진로가 다른 가상 페르소나별로
추천 top-k를 뽑고 LLM-as-judge(OpenAI)로 관련성을 0~2점 채점해
Precision@k / nDCG@k를 계산한다.

가중치(career_weight, recency_weight 등)를 튜닝할 때 전후 비교 기준선으로 쓴다.

실행:
    python -m app.ai.evaluation.recommendation_eval [--top-k 10]
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.embeddings.openai_client import _get_client
from app.ai.recommendations.extracurricular_recommender import recommend_for_user
from app.domains.academics.models import UserAcademicProgram
from app.domains.activities.models import Activity, UserActivityRecommendation
from app.domains.users.models import User

JUDGE_MODEL = "gpt-4o-mini"

# 점수 해석: 2=진로/전공에 직접 관련, 1=일반 대학생으로서 유용, 0=무관
RELEVANT_THRESHOLD = 1


@dataclass(frozen=True)
class Persona:
    name: str
    department: str
    major: str
    career_goal: str


PERSONAS: list[Persona] = [
    Persona("backend_dev", "정보컴퓨터공학부", "컴퓨터공학", "백엔드 개발자"),
    Persona("data_scientist", "정보컴퓨터공학부", "인공지능", "데이터 사이언티스트"),
    Persona("ux_designer", "디자인학과", "시각디자인", "UX 디자이너"),
    Persona("chem_researcher", "화학과", "화학", "제약회사 연구원"),
    Persona("marketer", "경영학과", "경영학", "마케터"),
    Persona("public_officer", "행정학과", "행정학", "행정직 공무원"),
]

_JUDGE_PROMPT = """당신은 대학생 비교과 활동 추천 시스템의 평가자입니다.

학생 프로필:
- 학부: {department}
- 전공: {major}
- 희망 진로: {career_goal}

아래는 이 학생에게 추천된 교내 공지사항 목록입니다.
각 공지가 이 학생에게 얼마나 관련 있는지 채점하세요.

채점 기준:
- 2: 전공이나 희망 진로와 직접 관련 (해당 분야 공모전/채용/교육 등)
- 1: 진로와 직접 관련은 없지만 이 학생이 참여할 만한 일반적 활동 (장학금, 특강, 도서관 프로그램 등)
- 0: 이 학생과 무관 (다른 전공 전용, 대상 아님)

공지 목록:
{items}

JSON 배열로만 답하세요. 예: [{{"id": 1, "score": 2}}, {{"id": 2, "score": 0}}]"""


def _judge_relevance(persona: Persona, activities: list[Activity]) -> list[int]:
    """페르소나에 대한 각 활동의 관련성을 0~2로 채점한다."""
    items = "\n".join(
        f"{i + 1}. [{a.category or '미분류'}] {a.title}" for i, a in enumerate(activities)
    )
    prompt = _JUDGE_PROMPT.format(
        department=persona.department,
        major=persona.major,
        career_goal=persona.career_goal,
        items=items,
    )
    client = _get_client()
    response = client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    parsed = json.loads(text)
    scores_by_id = {item["id"]: int(item["score"]) for item in parsed}
    return [scores_by_id.get(i + 1, 0) for i in range(len(activities))]


def _precision_at_k(scores: list[int], k: int) -> float:
    top = scores[:k]
    if not top:
        return 0.0
    return sum(1 for s in top if s >= RELEVANT_THRESHOLD) / len(top)


def _ndcg_at_k(scores: list[int], k: int) -> float:
    top = scores[:k]
    if not top:
        return 0.0
    dcg = sum(s / math.log2(i + 2) for i, s in enumerate(top))
    ideal = sorted(top, reverse=True)
    idcg = sum(s / math.log2(i + 2) for i, s in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def _recommend_for_persona(
    db: Session, persona: Persona, top_k: int
) -> list[tuple[Activity, float]]:
    """임시 유저를 만들어 추천을 계산하고, 정리 후 (Activity, final_score)를 반환한다."""
    user = User(
        email=f"eval-{persona.name}@eval.local",
        password_hash="-",
        name=f"eval-{persona.name}",
        department=persona.department,
        career_goal=persona.career_goal,
    )
    db.add(user)
    db.flush()
    db.add(
        UserAcademicProgram(
            user_id=user.id, department=persona.department, major=persona.major
        )
    )
    db.commit()

    try:
        recommend_for_user(db, user.id, top_k=top_k)
        rows = db.execute(
            select(Activity, UserActivityRecommendation.final_score)
            .join(
                UserActivityRecommendation,
                UserActivityRecommendation.activity_id == Activity.id,
            )
            .where(UserActivityRecommendation.user_id == user.id)
            .order_by(UserActivityRecommendation.final_score.desc())
            .limit(top_k)
        ).all()
        return [(activity, score) for activity, score in rows]
    finally:
        db.query(UserAcademicProgram).filter(
            UserAcademicProgram.user_id == user.id
        ).delete()
        db.delete(user)  # 추천 레코드는 FK CASCADE로 함께 삭제
        db.commit()


def run_eval(db: Session, top_k: int = 10) -> dict:
    results = []
    for persona in PERSONAS:
        recommended = _recommend_for_persona(db, persona, top_k)
        activities = [a for a, _ in recommended]
        scores = _judge_relevance(persona, activities)
        results.append(
            {
                "persona": persona.name,
                "career_goal": persona.career_goal,
                f"precision@{top_k}": round(_precision_at_k(scores, top_k), 3),
                f"ndcg@{top_k}": round(_ndcg_at_k(scores, top_k), 3),
                "items": [
                    {
                        "title": a.title,
                        "category": a.category,
                        "final_score": round(s, 3),
                        "judge_score": j,
                    }
                    for (a, s), j in zip(recommended, scores)
                ],
            }
        )

    summary = {
        f"mean_precision@{top_k}": round(
            sum(r[f"precision@{top_k}"] for r in results) / len(results), 3
        ),
        f"mean_ndcg@{top_k}": round(
            sum(r[f"ndcg@{top_k}"] for r in results) / len(results), 3
        ),
    }
    return {"summary": summary, "personas": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--output", type=str, default=None, help="JSON 리포트 저장 경로")
    args = parser.parse_args()

    from app.core.db import SessionLocal

    db = SessionLocal()
    try:
        report = run_eval(db, top_k=args.top_k)
    finally:
        db.close()

    print(f"\n{'페르소나':<20}{'진로':<16}P@{args.top_k:<6}nDCG@{args.top_k}")
    for r in report["personas"]:
        print(
            f"{r['persona']:<20}{r['career_goal']:<16}"
            f"{r[f'precision@{args.top_k}']:<8}{r[f'ndcg@{args.top_k}']}"
        )
    print(f"\n평균: {report['summary']}")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"리포트 저장: {args.output}")


if __name__ == "__main__":
    main()
