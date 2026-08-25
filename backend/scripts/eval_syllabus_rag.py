"""강의계획서 크롤링(2026-08-24, PR #241~#248) 기반 진로 매칭 검색의 RAG 품질
오프라인 평가.

`search_courses`(로드맵/시간표 챗이 실제로 쓰는 도구)가 내부적으로 부르는
`CurriculumRetriever.search()`(키워드 매칭 경로, `use_vector=False` — 실제
서비스가 쓰는 기본 경로)를 가상 페르소나(학과/전공 + 진로 목표) 여러 명에
대해 돌리고, 상위 10개 결과를 LLM-as-judge로 관련성 판정해 Precision@10 /
nDCG@10을 낸다.

방법론은 이 저장소의 다른 RAG 기능 평가(비교과 추천, `docs/backend/features/
activity-recommendations.md` — "LLM-as-judge(가상 페르소나 6명) 오프라인 평가로
P@10/nDCG@10 측정")와 동일하게 맞췄다 — 같은 평가 축으로 여러 기능을 비교할 수
있게.

실행 (backend/ 디렉터리에서, OPENAI_API_KEY 필요):
    python -m scripts.eval_syllabus_rag [--out backend/docs 경로 등 JSON 저장 위치]
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field

from openai import OpenAI

from app.ai.rag.curriculum_retriever import CurriculumRetriever
from app.core.config import settings
from app.core.db import SessionLocal

_JUDGE_MODEL = "gpt-4o-mini"


@dataclass
class Persona:
    label: str
    department_id: int
    major_id: int | None
    career_goal: str
    curriculum_year: str = "2024"


# 2026-2학기 강의계획서 파일럿 대상 6개 학과/전공(사회학과는 AI융합트랙 데모용)에서
# 학생이 실제로 입력할 법한 진로 목표를 하나씩 뽑았다 — 지어낸 조합이 아니라 이
# 세션에서 실제로 크롤링한 대상 그대로다.
PERSONAS: list[Persona] = [
    Persona("컴퓨터공학전공-AI엔지니어", department_id=108, major_id=36, career_goal="AI 엔지니어"),
    Persona("컴퓨터공학전공-백엔드개발자", department_id=108, major_id=36, career_goal="백엔드 개발자"),
    Persona("경영학과-마케팅기획자", department_id=96, major_id=None, career_goal="마케팅 기획자"),
    Persona("핀테크융합전공-핀테크개발자", department_id=97, major_id=None, career_goal="핀테크 개발자"),
    Persona("통계학과-데이터사이언티스트", department_id=29, major_id=None, career_goal="데이터 사이언티스트"),
    Persona("데이터사이언스전공-데이터분석가", department_id=1, major_id=1, career_goal="데이터 분석가"),
    Persona("사회학과-사회조사전문가", department_id=17, major_id=None, career_goal="사회조사 분석사"),
]


@dataclass
class JudgedResult:
    course_name: str
    course_id: int
    is_syllabus_sourced: bool
    relevant: bool


@dataclass
class PersonaEval:
    persona: Persona
    results: list[JudgedResult] = field(default_factory=list)
    precision_at_10: float = 0.0
    ndcg_at_10: float = 0.0


def _judge_relevance(client: OpenAI, career_goal: str, candidates: list[dict]) -> list[bool]:
    """career_goal에 대해 candidates(course_name+evidence) 각각의 관련성을 LLM으로
    한 번에 판정한다(10개 각각 API 호출하지 않고 배치로 묶어 비용 절감)."""
    if not candidates:
        return []
    numbered = "\n".join(
        f"{i+1}. {c['course_name']} — {(c['evidence'] or '')[:400]}"
        for i, c in enumerate(candidates)
    )
    prompt = (
        f'진로 목표: "{career_goal}"\n\n'
        f"아래는 어떤 학생에게 추천된 과목 후보 목록이다. 각 과목이 이 진로 목표를 "
        "준비하는 데 실질적으로 도움이 되는지(직접적인 실무/이론 관련성이 있는지) "
        "판정해라. 과목명만 보고 막연히 판단하지 말고 제공된 설명(강의개요/교수목표)을 "
        "근거로 삼아라. 애매하면 관련 없음으로 판정해라.\n\n"
        f"{numbered}\n\n"
        f'다음 JSON 객체 형태로만 답해라(설명 없이): '
        f'{{"judgments": [{{"index": 1, "relevant": true}}, {{"index": 2, "relevant": false}}, ...]}} '
        f"— judgments 배열에 반드시 {len(candidates)}개 전부(index 1~{len(candidates)}) 포함해라."
    )
    resp = client.chat.completions.create(
        model=_JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    content = resp.choices[0].message.content or "{}"
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return [False] * len(candidates)
    # response_format=json_object는 최상위가 반드시 object라 배열을 바로 못 돌려준다 —
    # "judgments" 키에 담아달라고 프롬프트로 요청했다. 혹시 모델이 다른 키를 쓰면 흔한
    # 대안 키들도 흡수하고, 이론상 안 나오지만 최상위가 배열로 온 경우도 방어한다.
    # (독립 리뷰 2026-08-25 지적: 예전엔 이 배열 방어가 `parsed.get(...)` 뒤에 있어서,
    # parsed가 진짜 list면 그 get() 호출 자체가 AttributeError로 먼저 죽어 방어 코드가
    # 실행되기 전에 크래시했다 — isinstance 체크를 맨 앞으로 옮겨서 실제로 방어되게 했다.)
    if isinstance(parsed, list):
        items = parsed
    else:
        items = parsed.get("judgments") or parsed.get("results") or parsed.get("items") or []
    verdicts = [False] * len(candidates)
    for item in items:
        idx = item.get("index")
        if isinstance(idx, int) and 1 <= idx <= len(candidates):
            verdicts[idx - 1] = bool(item.get("relevant"))
    return verdicts


def _ndcg_at_k(relevances: list[bool], k: int) -> float:
    rel = [1.0 if r else 0.0 for r in relevances[:k]]
    dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rel))
    ideal = sorted(rel, reverse=True)
    idcg = sum(r / math.log2(i + 2) for i, r in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def evaluate_persona(client: OpenAI, db, persona: Persona) -> PersonaEval:
    retriever = CurriculumRetriever(db)
    results = retriever.search(
        query=persona.career_goal,
        department_id=persona.department_id,
        major_id=persona.major_id,
        curriculum_year=persona.curriculum_year,
        filters={"limit": 10},
    )
    verdicts = _judge_relevance(client, persona.career_goal, results)
    judged = [
        JudgedResult(
            course_name=r["course_name"],
            course_id=r["course_id"],
            is_syllabus_sourced="교수계획표" in (r.get("evidence") or ""),
            relevant=v,
        )
        for r, v in zip(results, verdicts)
    ]
    precision = sum(1 for j in judged if j.relevant) / 10 if judged else 0.0
    ndcg = _ndcg_at_k([j.relevant for j in judged], 10)
    return PersonaEval(persona=persona, results=judged, precision_at_10=precision, ndcg_at_10=ndcg)


def run_eval() -> list[PersonaEval]:
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다 (.env 확인)")
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    db = SessionLocal()
    try:
        return [evaluate_persona(client, db, p) for p in PERSONAS]
    finally:
        db.close()


def _to_json(evals: list[PersonaEval]) -> dict:
    return {
        "judge_model": _JUDGE_MODEL,
        "mean_precision_at_10": sum(e.precision_at_10 for e in evals) / len(evals) if evals else 0.0,
        "mean_ndcg_at_10": sum(e.ndcg_at_10 for e in evals) / len(evals) if evals else 0.0,
        "personas": [
            {
                "label": e.persona.label,
                "career_goal": e.persona.career_goal,
                "precision_at_10": e.precision_at_10,
                "ndcg_at_10": e.ndcg_at_10,
                "results": [
                    {
                        "course_name": r.course_name,
                        "course_id": r.course_id,
                        "syllabus_sourced": r.is_syllabus_sourced,
                        "relevant": r.relevant,
                    }
                    for r in e.results
                ],
            }
            for e in evals
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=None, help="결과를 JSON으로 저장할 경로(생략 시 stdout 요약만)")
    args = parser.parse_args()

    evals = run_eval()
    payload = _to_json(evals)

    print(f"판정 모델: {payload['judge_model']}")
    for e in evals:
        print(f"  {e.persona.label:32s} P@10={e.precision_at_10:.3f}  nDCG@10={e.ndcg_at_10:.3f}")
    print(f"평균 Precision@10 = {payload['mean_precision_at_10']:.3f}")
    print(f"평균 nDCG@10      = {payload['mean_ndcg_at_10']:.3f}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"결과 저장: {args.out}")


if __name__ == "__main__":
    main()
