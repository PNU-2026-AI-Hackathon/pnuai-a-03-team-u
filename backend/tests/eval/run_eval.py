"""로컬 실행기 — Phase 3.1.

기본(dry-run): 페르소나 시드 → 학생 컨텍스트 블록 렌더 → 각 tool을 인자 없이 한 번씩
호출해서 크래시만 확인. LLM 안 부름. 파이프라인 회귀 감지용.

--live: 실제 LLM(OPENAI_API_KEY 필요)을 호출해 대화 한 턴 진행 후 assertion 채점.
        _current_academic_term은 2026-08 기준으로 고정(엇학기 케이스가 명시적이도록).

Usage (backend/ 디렉터리에서):
    python -m tests.eval.run_eval                  # dry-run 전체
    python -m tests.eval.run_eval --live           # LLM 호출
    python -m tests.eval.run_eval --case 10        # 특정 케이스만 (slug prefix)
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import traceback
from dataclasses import dataclass
from unittest.mock import patch

# personas 모듈이 domains를 import 하므로 sys.path에 backend/를 미리 넣어둔다
# (pytest는 자동이지만 python -m로 직접 실행하는 경우도 있으므로 방어).
try:
    from tests.eval.case_spec import EvalCase, EvalResult, ExpectedBehavior
    from tests.eval.cases import ALL_CASES
    from tests.eval.personas import build_persona_db
except ImportError:  # pragma: no cover - 실행 편의
    from backend.tests.eval.case_spec import EvalCase, EvalResult, ExpectedBehavior
    from backend.tests.eval.cases import ALL_CASES
    from backend.tests.eval.personas import build_persona_db


# --- assertion 채점 --------------------------------------------------------


def _eval_assertion(exp: ExpectedBehavior, result: EvalResult) -> str | None:
    """passed=None, failed=문자열(사유)."""
    kind = exp.kind
    target = exp.target
    tool_names = [c["name"] for c in result.tool_calls]

    if kind == "tool_called":
        if target in tool_names:
            return None
        return f"tool '{target}'가 호출되지 않음 (실제: {tool_names})"

    if kind == "tool_not_called":
        if target not in tool_names:
            return None
        return f"tool '{target}'가 호출되면 안 됨 (실제: {tool_names})"

    if kind == "response_mentions":
        if str(target) in (result.reply or ""):
            return None
        return f"응답에 '{target}' 없음. 응답 프리뷰: {(result.reply or '')[:120]!r}"

    if kind == "response_absent":
        if str(target) not in (result.reply or ""):
            return None
        return f"응답에 '{target}'가 포함됨 (있으면 안 됨)"

    if kind == "iterations_le":
        if result.iterations_used <= int(target):
            return None
        return f"iterations {result.iterations_used} > 상한 {target}"

    if kind == "pending_change_count":
        op, n = target  # type: ignore[misc]
        actual = result.pending_changes_count
        ok = ({"==": actual == n, "<=": actual <= n, ">=": actual >= n}).get(op)
        return None if ok else f"pending_changes {actual} !{op} {n}"

    if kind == "schedules_count":
        op, n = target  # type: ignore[misc]
        actual = result.schedules_count
        ok = ({"==": actual == n, "<=": actual <= n, ">=": actual >= n}).get(op)
        return None if ok else f"schedules {actual} !{op} {n}"

    if kind == "custom":
        return target(result)  # type: ignore[operator]

    return f"unknown assertion kind: {kind}"


# --- 실행 -----------------------------------------------------------------


@dataclass
class CaseOutcome:
    slug: str
    ok: bool
    failures: list[str]                    # assertion 실패 사유
    error: str | None = None               # 예외로 죽은 경우
    reply_preview: str = ""


def run_dry(case: EvalCase) -> CaseOutcome:
    """LLM 없이 시드 + 컨텍스트 블록 + tool 스모크 호출."""
    from app.domains.planning import roadmap_chat as rc_mod
    from app.domains.planning import timetable_chat as tc_mod

    try:
        db, user, roadmap = build_persona_db(case.persona)
        # 학생 컨텍스트 블록이 렌더되는지 (모든 hierarchy 조회 통과 확인).
        block = rc_mod._build_student_context_block(db, user)
        assert isinstance(block, str) and len(block) > 0, "context block empty"

        if case.agent == "roadmap":
            ctx = rc_mod._ToolContext(db, user, roadmap)
            # 부작용 없는 read tool들을 한 번씩 호출.
            for name in ("get_graduation_progress", "get_program_evaluations",
                          "get_roadmap_items"):
                r = ctx.dispatch(name, {})
                assert isinstance(r, dict), f"tool {name} returned non-dict"
            # search_courses는 필터 없이는 빈 결과일 수 있으니 category만 걸어봄.
            r = ctx.dispatch("search_courses", {"query": "", "category": "전공선택"})
            assert isinstance(r, dict)
        else:  # timetable
            ctx = tc_mod._TimeTableToolContext(
                db=db, user=user, year=case.timetable_year, semester=case.timetable_semester,
            )
            for name in ("get_student_context", "list_offered_courses"):
                r = ctx.dispatch(name, {})
                assert isinstance(r, dict), f"tool {name} returned non-dict"
        return CaseOutcome(slug=case.slug, ok=True, failures=[])
    except Exception as e:  # noqa: BLE001
        return CaseOutcome(
            slug=case.slug, ok=False, failures=[],
            error=f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=4)}",
        )


@contextlib.contextmanager
def _spy_roadmap_tool_calls():
    """`_ToolContext.dispatch`를 감싸 (name, args) 로그를 쌓는다."""
    from app.domains.planning import roadmap_chat as rc_mod

    log: list[dict] = []
    orig = rc_mod._ToolContext.dispatch

    def spy(self, name, tool_input):
        log.append({"name": name, "args": tool_input})
        return orig(self, name, tool_input)

    with patch.object(rc_mod._ToolContext, "dispatch", spy):
        yield log


def run_live(case: EvalCase) -> CaseOutcome:
    """LLM 실호출 후 assertion 채점."""
    from app.domains.planning import roadmap_chat as rc_mod
    from app.domains.planning import timetable_chat as tc_mod

    try:
        db, user, roadmap = build_persona_db(case.persona)
        # 엇학기 케이스가 성립하려면 현재 학기가 2026-2로 고정돼야 명확.
        with patch.object(rc_mod, "_current_academic_term", return_value=(2026, 2)):
            if case.agent == "roadmap":
                with _spy_roadmap_tool_calls() as tool_log:
                    out = rc_mod.run_roadmap_chat(db, user, roadmap, case.prompt)
                # finish_response는 spy에 안 잡히므로 (dispatch 경유 X) 수동 태깅.
                tool_log.append({"name": "finish_response", "args": {}})
                result = EvalResult(
                    reply=out.get("reply", ""), tool_calls=tool_log,
                    iterations_used=0,  # roadmap_chat은 이 값을 return하지 않음
                    pending_changes_count=len(out.get("pending_changes", []) or []),
                )
            else:
                out = tc_mod.run_timetable_chat(
                    db, user,
                    year=case.timetable_year, semester=case.timetable_semester,
                    message=case.prompt,
                )
                result = EvalResult(
                    reply=out.get("reply", ""),
                    tool_calls=list(out.get("tool_calls", []) or []),
                    iterations_used=int(out.get("iterations", 0) or 0),
                    schedules_count=len(out.get("schedules", []) or []),
                )

        failures = [msg for exp in case.expectations
                    if (msg := _eval_assertion(exp, result)) is not None]
        return CaseOutcome(
            slug=case.slug, ok=not failures, failures=failures,
            reply_preview=(result.reply or "")[:200],
        )
    except Exception as e:  # noqa: BLE001
        return CaseOutcome(
            slug=case.slug, ok=False, failures=[],
            error=f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=4)}",
        )


# --- CLI ------------------------------------------------------------------


def _print_outcome(o: CaseOutcome, verbose: bool) -> None:
    tag = "PASS" if o.ok else "FAIL"
    print(f"[{tag}] {o.slug}")
    if o.error:
        print(f"       ERROR: {o.error}")
    for f in o.failures:
        print(f"       - {f}")
    if verbose and o.reply_preview:
        print(f"       reply: {o.reply_preview!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 3.1 golden dataset runner")
    ap.add_argument("--live", action="store_true", help="LLM 실호출 (OPENAI_API_KEY 필요)")
    ap.add_argument("--case", type=str, help="slug prefix로 필터 (예: 10)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    cases = [c for c in ALL_CASES if (args.case is None or c.slug.startswith(args.case))]
    if not cases:
        print(f"no cases match {args.case!r}", file=sys.stderr)
        return 2

    runner = run_live if args.live else run_dry
    print(f"Running {len(cases)} case(s) in {'live' if args.live else 'dry'} mode")

    outcomes = [runner(c) for c in cases]
    for o in outcomes:
        _print_outcome(o, args.verbose)

    passed = sum(1 for o in outcomes if o.ok)
    print(f"\nSummary: {passed}/{len(outcomes)} passed")
    return 0 if passed == len(outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
