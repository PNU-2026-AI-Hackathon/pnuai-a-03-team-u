"""Langfuse Datasets 업로드 헬퍼.

Phase 3.2. 골든 데이터셋 케이스를 Langfuse Cloud의 Dataset으로 sync 한다.
- 소스 진실은 여전히 Python 코드 (`cases.py`) — Langfuse는 관측·A/B 실험 UI 목적
- 매 sync는 idempotent (case slug를 dataset item id로 사용)
- 케이스가 늘어나면 add-only, 기존 슬러그는 update

Usage:
    from tests.eval.langfuse_sync import sync_cases_to_langfuse
    sync_cases_to_langfuse()  # 환경변수(LANGFUSE_*)에서 auth 자동 픽업
"""

from __future__ import annotations

import os
from typing import Any

from app.core.config import settings

from .case_spec import EvalCase, ExpectedBehavior, PersonaSpec
from .cases import ALL_CASES


# Langfuse UI에 뜨는 Dataset 이름. v2 넘어가면 뒤에 -v2 붙여서 이력 남긴다.
DATASET_NAME = "planu-golden-v1"


def _serialize_expectation(exp: ExpectedBehavior) -> dict[str, Any]:
    """assertion을 JSON-safe dict으로. custom lambda·llm_judge 기준 문자열은 그대로 담는다."""
    target = exp.target
    if callable(target):
        # custom callable은 코드 정체성 대신 이름/모듈로 표시 (lambda면 <lambda>)
        target_repr = f"<callable {getattr(target, '__qualname__', repr(target))}>"
    elif isinstance(target, tuple):
        target_repr = list(target)  # ("<=", 3) 같은 튜플
    else:
        target_repr = target
    return {"kind": exp.kind, "target": target_repr, "reason": exp.reason}


def _serialize_persona(p: PersonaSpec) -> dict[str, Any]:
    """페르소나 요약. 전체 시드는 너무 크니 UI에서 identify에 필요한 필드만."""
    return {
        "id": p.id, "label": p.label,
        "user": {
            "department_id": p.department_id, "major_id": p.major_id,
            "career_goal": p.career_goal, "admission_type": p.admission_type,
        },
        "programs": [
            {"program_type": pr.program_type, "department_id": pr.department_id,
             "major_id": pr.major_id, "curriculum_year": pr.curriculum_year}
            for pr in p.programs
        ],
        "counts": {
            "requirements": len(p.requirements), "courses": len(p.courses),
            "records": len(p.records), "roadmap_items": len(p.roadmap_items),
            "offerings": len(p.offerings),
        },
    }


def _case_to_item(case: EvalCase) -> dict[str, Any]:
    """EvalCase → dataset item payload."""
    return {
        "id": case.slug,
        "input": {
            "agent": case.agent,
            "prompt": case.prompt,
            "persona": _serialize_persona(case.persona),
            "timetable_year": case.timetable_year,
            "timetable_semester": case.timetable_semester,
        },
        "expected_output": {
            "assertions": [_serialize_expectation(e) for e in case.expectations],
        },
        "metadata": {
            "slug": case.slug,
            "persona_label": case.persona.label,
            "agent": case.agent,
        },
    }


def sync_cases_to_langfuse(cases: list[EvalCase] | None = None,
                            dataset_name: str = DATASET_NAME) -> int:
    """케이스를 Langfuse Dataset으로 upsert 한다. 업로드된 케이스 수 반환.

    LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL 환경변수 필요.
    셋 중 하나라도 없으면 RuntimeError.
    """
    # pydantic BaseSettings가 .env를 이미 로드했으므로 settings 값을 확인 → os.environ에
    # 채워서 langfuse SDK가 픽업하게 한다 (SDK는 raw env만 봄).
    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        v = getattr(settings, key, None)
        if not v:
            raise RuntimeError(f"{key}가 없어서 Langfuse Datasets sync 불가 (.env 확인)")
        os.environ.setdefault(key, v)
    if getattr(settings, "LANGFUSE_BASE_URL", None):
        os.environ.setdefault("LANGFUSE_HOST", settings.LANGFUSE_BASE_URL)

    from langfuse import Langfuse
    lf = Langfuse()

    # create_dataset은 이름 동일하면 기존 것 반환(idempotent).
    lf.create_dataset(
        name=dataset_name,
        description=(
            "Plan-U 챗 에이전트 골든 데이터셋. 소스 진실은 backend/tests/eval/cases.py. "
            "이 dataset은 Langfuse UI에서 A/B 실험 결과 tie-in 용도."
        ),
        metadata={"phase": "3.1", "source": "backend/tests/eval/cases.py"},
    )

    items = cases if cases is not None else ALL_CASES
    for case in items:
        payload = _case_to_item(case)
        # v4 SDK: id 인자로 upsert. 같은 id면 기존 아이템 덮어씀.
        lf.create_dataset_item(
            dataset_name=dataset_name,
            id=payload["id"],
            input=payload["input"],
            expected_output=payload["expected_output"],
            metadata=payload["metadata"],
        )

    lf.flush()  # background HTTP client 대기 후 종료
    return len(items)
