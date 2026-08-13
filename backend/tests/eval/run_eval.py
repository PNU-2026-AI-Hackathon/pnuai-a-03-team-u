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
import statistics
import sys
import time
import traceback
from dataclasses import dataclass, field
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

    if kind == "llm_judge":
        ok, reason = _llm_judge(result.reply, str(target), result.tool_calls)
        return None if ok else f"[llm_judge] {reason}"

    return f"unknown assertion kind: {kind}"


# 판정 LLM은 피검사 모델과 다른 걸 써야 방법론적으로 깔끔하다 (같은 모델이 자기 판정
# 하면 편향). gpt-4o-mini는 저렴하고 non-reasoning이라 채점 태스크에 안정적.
_JUDGE_MODEL = "openai:gpt-4o-mini"


def _llm_judge(reply: str, criterion: str, tool_calls: list[dict]) -> tuple[bool, str]:
    """자연어 기준으로 응답이 조건을 만족하는지 판정. (passed, reason) 반환.

    문자열 매칭 assertion으로 잡을 수 없는 의미 기반 검증에 쓴다. 예:
    - "부·복수전공 옵션을 능동적으로 제안했는가?"
    - "'공학작문'이 이번 학기 개설 안 됨을 정직하게 알렸는가? 지어내지 않고?"
    """
    from langchain.chat_models import init_chat_model

    tool_names = [c.get("name") for c in tool_calls]
    prompt = f"""너는 챗봇 응답 채점자다. 아래 판정 기준을 만족하는지 엄격히 판정해라.

판정 기준: {criterion}

챗봇이 호출한 도구 순서: {tool_names}

챗봇의 최종 응답:
\"\"\"
{reply}
\"\"\"

응답 형식(반드시 순수 JSON, 다른 텍스트 금지):
{{"pass": true 또는 false, "reason": "한 문장 판정 근거"}}"""

    try:
        llm = init_chat_model(_JUDGE_MODEL, temperature=0)
        r = llm.invoke(prompt)
        content = r.content if isinstance(r.content, str) else str(r.content)
        import json
        data = json.loads(_strip_markdown_fence(content))
        return bool(data["pass"]), str(data.get("reason", ""))
    except Exception as e:  # noqa: BLE001 - 판정 실패는 fail로 처리하되 이유 노출
        return False, f"judge_error: {type(e).__name__}: {e}"


def _strip_markdown_fence(text: str) -> str:
    """LLM이 ```json ... ``` 로 감싸서 낸 응답에서 fence만 제거하고 본문 반환.

    이전 구현은 `text.lstrip("json\\n")` 문자셋 기반이라 "javascript"로 시작하는
    응답을 "avascript"로 왜곡할 수 있었다 (실제 발생 확률 낮지만 명시적 오류).
    라인 단위 제거로 안전화.
    """
    s = text.strip()
    if not s.startswith("```"):
        return s
    lines = s.split("\n")
    # 첫 줄이 ```json 또는 ``` 이면 제거
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    # 마지막 줄이 ``` 이면 제거
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


# --- 실행 -----------------------------------------------------------------


@dataclass
class CaseOutcome:
    slug: str
    ok: bool
    failures: list[str]                    # assertion 실패 사유
    error: str | None = None               # 예외로 죽은 경우
    reply_preview: str = ""
    elapsed_ms: float = 0.0                # wall-clock (LLM 왕복 포함)
    iterations: int = 0                    # tool call 반복 수 (finish_response 포함)
    input_tokens: int = 0                  # 케이스 한 번 대화에 쓴 누적 input 토큰
    output_tokens: int = 0                 # 누적 output(=visible) 토큰
    reasoning_tokens: int = 0              # GPT-5 계열의 숨은 reasoning 토큰


# USD/1M 토큰 (2026-08 openai 공식 페이지 기준, verify: developers.openai.com/api/docs/pricing).
# reasoning은 output 토큰과 같은 가격.
_PRICING_USD_PER_M: dict[str, tuple[float, float]] = {
    "openai:gpt-4o-mini":  (0.15, 0.60),
    "openai:gpt-4o":       (2.50, 10.00),
    "openai:gpt-5":        (1.25, 10.00),
    "openai:gpt-5-mini":   (0.25, 2.00),
    "openai:gpt-5-nano":   (0.05, 0.40),
    "openai:gpt-5.4-mini": (0.75, 4.50),   # Terra
    "openai:gpt-5.4-nano": (0.20, 1.25),   # Luna
}


def _est_cost_usd(model: str, in_tok: int, out_tok_total: int) -> float | None:
    """out_tok_total = output_tokens + reasoning_tokens (동일 요율로 과금됨)."""
    p = _PRICING_USD_PER_M.get(model)
    if not p:
        return None
    return (in_tok * p[0] + out_tok_total * p[1]) / 1_000_000


def _declared_tool_names(agent: str) -> set[str]:
    """에이전트가 LLM에 노출하는 도구 이름 집합. 하드코딩 대신 실제 _TOOLS에서 뽑는다."""
    from app.domains.planning import roadmap_chat as rc_mod
    from app.domains.planning import timetable_chat as tc_mod

    tools = rc_mod._TOOLS if agent == "roadmap" else tc_mod._TOOLS
    return {t["function"]["name"] for t in tools}


def _validate_expectations(case: EvalCase) -> list[str]:
    """assertion 명세 자체의 정합성을 LLM 없이 정적 검사한다.

    도구를 리네임했는데 케이스의 `tool_called` target을 안 고치면, 그 assertion은
    live에서 조용히 '항상 실패'(또는 tool_not_called면 '항상 통과')로 변해 회귀 감지력을
    잃는다. dry-run에서 미리 잡는다.
    """
    problems: list[str] = []
    valid_tools = _declared_tool_names(case.agent)
    for exp in case.expectations:
        if exp.kind in ("tool_called", "tool_not_called"):
            if exp.target not in valid_tools:
                problems.append(
                    f"{exp.kind} target '{exp.target}'은 {case.agent} 에이전트의 도구가 "
                    f"아님 (실제: {sorted(valid_tools)})"
                )
        elif exp.kind in ("pending_change_count", "schedules_count"):
            if not (isinstance(exp.target, tuple) and len(exp.target) == 2
                    and exp.target[0] in ("==", "<=", ">=")):
                problems.append(f"{exp.kind} target은 (op, n) 튜플이어야 함: {exp.target!r}")
        elif exp.kind == "custom" and not callable(exp.target):
            problems.append(f"custom target은 callable이어야 함: {exp.target!r}")
        elif exp.kind in ("response_mentions", "response_absent", "llm_judge"):
            if not isinstance(exp.target, str) or not exp.target.strip():
                problems.append(f"{exp.kind} target은 비어있지 않은 문자열이어야 함")
    # 시간표 케이스가 pending_change_count를, 로드맵 케이스가 schedules_count를 거는 건
    # 항상 0이라 무의미한 검사가 된다.
    kinds = {e.kind for e in case.expectations}
    if case.agent == "timetable" and "pending_change_count" in kinds:
        problems.append("시간표 케이스에 pending_change_count assertion은 항상 0이라 무의미")
    if case.agent == "roadmap" and "schedules_count" in kinds:
        problems.append("로드맵 케이스에 schedules_count assertion은 항상 0이라 무의미")
    return problems


def run_dry(case: EvalCase) -> CaseOutcome:
    """LLM 없이 시드 + 컨텍스트 블록 + tool 스모크 호출 + assertion 명세 정적 검사."""
    from app.domains.planning import roadmap_chat as rc_mod
    from app.domains.planning import timetable_chat as tc_mod

    try:
        spec_problems = _validate_expectations(case)
        if spec_problems:
            return CaseOutcome(slug=case.slug, ok=False, failures=spec_problems)

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


def _pending_change_view(change) -> dict:
    """PendingRoadmapChange ORM 객체를 assertion이 읽기 좋은 평범한 dict으로.

    세션이 닫힌 뒤 lazy load로 터지지 않도록 여기서 값을 뽑아 고정한다.
    """
    return {
        "action": getattr(change, "action", None),
        "course_id": getattr(change, "course_id", None),
        "item_id": getattr(change, "item_id", None),
        "planned_grade": getattr(change, "planned_grade", None),
        "planned_year": getattr(change, "planned_year", None),
        "planned_semester": getattr(change, "planned_semester", None),
        "program_type": getattr(change, "program_type", None),
        "reason": getattr(change, "reason", None),
    }


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


class _UsageSpy:
    """langchain ChatModel 래퍼. invoke 결과의 usage_metadata를 누적한다.

    bind_tools가 반환하는 Runnable도 감싸야 대화 루프의 모든 턴이 잡힌다.
    """

    def __init__(self, inner, log: list[dict]):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_log", log)

    def invoke(self, *args, **kwargs):
        r = self._inner.invoke(*args, **kwargs)
        um = getattr(r, "usage_metadata", None)
        if um:
            self._log.append(dict(um))
        return r

    def bind_tools(self, *args, **kwargs):
        return _UsageSpy(self._inner.bind_tools(*args, **kwargs), self._log)

    def __getattr__(self, name):
        return getattr(self._inner, name)


@contextlib.contextmanager
def _spy_token_usage():
    """`_build_llm`을 _UsageSpy로 감싸서 이번 케이스 대화의 토큰 사용량을 모은다.

    roadmap_chat과 timetable_chat 두 모듈 모두에서 참조하므로 둘 다 패치.
    """
    from app.domains.planning import roadmap_chat as rc_mod
    from app.domains.planning import timetable_chat as tc_mod

    log: list[dict] = []
    orig = rc_mod._build_llm

    def wrapped():
        return _UsageSpy(orig(), log)

    with patch.object(rc_mod, "_build_llm", wrapped), \
         patch.object(tc_mod, "_build_llm", wrapped):
        yield log


# TPM(200k) 초과로 429가 나면 그 케이스는 "실패"로 집계돼 pass율을 오염시킨다. 실제로
# 26케이스 × N=3 스윕에서 **실패 20건 중 12건이 429**였다 — 모델 품질이 아니라 하니스가
# 만들어낸 실패다. 케이스 하나가 입력 66k 토큰을 쓰기도 해서 연속 실행이면 1분 안에 한도를
# 넘는다. 429는 재시도로 흡수하고, 진짜 assertion 실패만 결과에 남긴다.
_RATE_LIMIT_BACKOFF_S = (20, 45, 90)


def _hit_rate_limit(outcome: CaseOutcome) -> bool:
    """이 결과가 429 때문인지. 두 경로를 모두 본다.

    - 에이전트 LLM 429 → 예외로 터져 `error`에 담긴다.
    - 판정 LLM(gpt-4o-mini) 429 → `_llm_judge`가 예외를 삼키고 `judge_error: ...`를
      failure 문자열로 돌려주므로 `failures`에 담긴다.
    """
    blobs = [outcome.error or ""] + list(outcome.failures)
    joined = " ".join(blobs).lower()
    return "ratelimiterror" in joined or "rate limit" in joined or "rate_limit" in joined


def run_live(case: EvalCase) -> CaseOutcome:
    """LLM 실호출 후 assertion 채점. 429는 백오프 재시도로 흡수한다."""
    outcome = _run_live_once(case)
    for i, backoff in enumerate(_RATE_LIMIT_BACKOFF_S, start=1):
        if not _hit_rate_limit(outcome):
            return outcome
        print(f"       (rate limit — {backoff}s 대기 후 재시도 {i}/{len(_RATE_LIMIT_BACKOFF_S)})")
        time.sleep(backoff)
        outcome = _run_live_once(case)
    return outcome  # 재시도를 다 써도 429면 그대로 실패로 남긴다


def _run_live_once(case: EvalCase) -> CaseOutcome:
    """run_live의 1회 실행분. 재시도 판정은 호출부가 한다."""
    from app.domains.planning import roadmap_chat as rc_mod
    from app.domains.planning import timetable_chat as tc_mod

    start = time.perf_counter()
    try:
        db, user, roadmap = build_persona_db(case.persona)
        # 엇학기 케이스가 성립하려면 현재 학기가 2026-2로 고정돼야 명확.
        with patch.object(rc_mod, "_current_academic_term", return_value=(2026, 2)), \
             _spy_token_usage() as usage_log:
            if case.agent == "roadmap":
                with _spy_roadmap_tool_calls() as tool_log:
                    out = rc_mod.run_roadmap_chat(db, user, roadmap, case.prompt)
                # finish_response는 dispatch를 안 거쳐서 spy에 안 잡힌다. 예전에는 무조건
                # 태깅해서 `tool_called finish_response` assertion이 항상 통과하는 무의미한
                # 검사가 됐다 — 이제 run_roadmap_chat이 돌려주는 실제 종료 여부로 태깅한다.
                if out.get("finished"):
                    tool_log.append({"name": "finish_response", "args": {}})
                # iterations는 LLM 왕복 수 (도구 호출 수 아님) — timetable 쪽과 같은 의미.
                iterations = int(out.get("iterations", 0) or 0)
                pending = list(out.get("pending_changes", []) or [])
                result = EvalResult(
                    reply=out.get("reply", ""), tool_calls=tool_log,
                    iterations_used=iterations,
                    pending_changes_count=len(pending),
                    pending_changes=[_pending_change_view(c) for c in pending],
                )
            else:
                out = tc_mod.run_timetable_chat(
                    db, user,
                    year=case.timetable_year, semester=case.timetable_semester,
                    message=case.prompt,
                )
                iterations = int(out.get("iterations", 0) or 0)
                schedules = list(out.get("schedules", []) or [])
                result = EvalResult(
                    reply=out.get("reply", ""),
                    tool_calls=list(out.get("tool_calls", []) or []),
                    iterations_used=iterations,
                    schedules_count=len(schedules),
                    schedules=schedules,
                )

        elapsed_ms = (time.perf_counter() - start) * 1000
        in_tok = sum(u.get("input_tokens", 0) for u in usage_log)
        out_tok = sum(u.get("output_tokens", 0) for u in usage_log)
        reasoning_tok = sum(
            (u.get("output_token_details", {}) or {}).get("reasoning", 0)
            for u in usage_log
        )
        failures = [msg for exp in case.expectations
                    if (msg := _eval_assertion(exp, result)) is not None]
        return CaseOutcome(
            slug=case.slug, ok=not failures, failures=failures,
            reply_preview=(result.reply or "")[:200],
            elapsed_ms=elapsed_ms, iterations=iterations,
            input_tokens=in_tok, output_tokens=out_tok,
            reasoning_tokens=reasoning_tok,
        )
    except Exception as e:  # noqa: BLE001
        return CaseOutcome(
            slug=case.slug, ok=False, failures=[],
            error=f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=4)}",
            elapsed_ms=(time.perf_counter() - start) * 1000,
        )


@contextlib.contextmanager
def _override_model(model: str | None):
    """`settings.ROADMAP_AGENT_MODEL`을 임시로 덮어써서 A/B 비교를 가능하게 한다.

    `_build_llm`이 매 대화 턴 이걸 읽어 langchain init_chat_model에 넘기므로
    (provider·모델 자동 dispatch), env를 안 건드리고 프로세스 안에서 스왑 가능.
    """
    from app.core.config import settings

    if model is None:
        yield
        return
    old = settings.ROADMAP_AGENT_MODEL
    settings.ROADMAP_AGENT_MODEL = model
    try:
        yield
    finally:
        settings.ROADMAP_AGENT_MODEL = old


# --- CLI ------------------------------------------------------------------


def _print_outcome(o: CaseOutcome, verbose: bool) -> None:
    tag = "PASS" if o.ok else "FAIL"
    extra = ""
    if o.elapsed_ms:
        tok_str = f"in={o.input_tokens} out={o.output_tokens}"
        if o.reasoning_tokens:
            tok_str += f" reasoning={o.reasoning_tokens}"
        extra = f" ({o.elapsed_ms:.0f}ms, {o.iterations}it, {tok_str})"
    print(f"[{tag}] {o.slug}{extra}")
    if o.error:
        print(f"       ERROR: {o.error}")
    for f in o.failures:
        print(f"       - {f}")
    if verbose and o.reply_preview:
        print(f"       reply: {o.reply_preview!r}")


def _summarize(outcomes: list[CaseOutcome], model: str | None = None) -> dict:
    times = [o.elapsed_ms for o in outcomes if o.elapsed_ms]
    iters = [o.iterations for o in outcomes if o.iterations]
    total_in = sum(o.input_tokens for o in outcomes)
    total_out = sum(o.output_tokens for o in outcomes)
    total_reasoning = sum(o.reasoning_tokens for o in outcomes)
    cost = _est_cost_usd(model, total_in, total_out + total_reasoning) if model else None
    return {
        "passed": sum(1 for o in outcomes if o.ok),
        "total": len(outcomes),
        "median_ms": statistics.median(times) if times else 0,
        "mean_ms": statistics.mean(times) if times else 0,
        "median_iters": statistics.median(iters) if iters else 0,
        "input_tokens": total_in,
        "output_tokens": total_out,
        "reasoning_tokens": total_reasoning,
        "cost_usd": cost,
    }


def _group_by_slug(outcomes: list[CaseOutcome]) -> dict[str, list[CaseOutcome]]:
    """slug 순서 보존해서 outcomes를 그룹핑."""
    grouped: dict[str, list[CaseOutcome]] = {}
    for o in outcomes:
        grouped.setdefault(o.slug, []).append(o)
    return grouped


def _print_comparison(by_model: dict[str, list[CaseOutcome]]) -> None:
    """다중 모델 A/B 요약. 정성(pass율) + 정량(latency·iterations·tokens·cost).

    N>1(--runs)일 때 각 케이스의 pass 프로파일도 보여줌 (예: ✓✓✗ = 3회 중 2번 통과).
    """
    models = list(by_model.keys())
    # runs 수는 모든 (model, slug) 쌍이 동일하다고 가정.
    first_slug_group = _group_by_slug(by_model[models[0]])
    runs = len(next(iter(first_slug_group.values())))

    print("\n" + "=" * 100)
    print(f"A/B 비교 (N={runs} runs/case)")
    print("=" * 100)
    # 모델별 총계.
    header = f"\n{'model':<24}  {'pass rate':<10}  {'med ms':<8}  {'med it':<6}  " \
             f"{'in tok':<8}  {'out tok':<8}  {'reas tok':<9}  {'cost USD':<10}"
    print(header)
    print("-" * 100)
    for m in models:
        s = _summarize(by_model[m], model=m)
        cost = f"{s['cost_usd']:.4f}" if s["cost_usd"] is not None else "?"
        pass_pct = 100 * s["passed"] / s["total"] if s["total"] else 0
        pass_str = f"{s['passed']}/{s['total']} ({pass_pct:.0f}%)"
        print(f"{m:<24}  {pass_str:<10}  "
              f"{s['median_ms']:<8.0f}  {s['median_iters']:<6.1f}  "
              f"{s['input_tokens']:<8}  {s['output_tokens']:<8}  "
              f"{s['reasoning_tokens']:<9}  {cost:<10}")
    print("\n※ 비용은 openai 공식 요율(2026-08). 요율 미등록 모델은 '?'.")

    # 케이스별 나란히 (pass 프로파일 + median 시간 + 케이스 총 비용).
    col_w = 22 if runs > 1 else 26
    print(f"\n{'case':<32}  " + "  ".join(f"{m:<{col_w}}" for m in models))
    print("-" * (32 + (col_w + 2) * len(models)))
    for slug in first_slug_group:
        cells = []
        for m in models:
            runs_for_case = _group_by_slug(by_model[m])[slug]
            passes = sum(1 for o in runs_for_case if o.ok)
            profile = "".join("✓" if o.ok else "✗" for o in runs_for_case)
            med = statistics.median([o.elapsed_ms for o in runs_for_case if o.elapsed_ms] or [0])
            tok = sum(o.input_tokens + o.output_tokens + o.reasoning_tokens for o in runs_for_case)
            if runs > 1:
                cells.append(f"{profile} {passes}/{runs} med{med:>4.0f}ms".ljust(col_w))
            else:
                mark = "✓" if passes else "✗"
                cells.append(f"{mark} {med:>5.0f}ms {tok:>5}tk".ljust(col_w))
        print(f"{slug:<32}  " + "  ".join(cells))


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 3.1 golden dataset runner")
    ap.add_argument("--live", action="store_true", help="LLM 실호출 (OPENAI_API_KEY 필요)")
    ap.add_argument("--case", type=str, help="slug prefix로 필터 (예: 10)")
    ap.add_argument(
        "--model", action="append", metavar="PROVIDER:MODEL",
        help="비교할 모델 (반복 지정 가능, --live 필요). 예: --model openai:gpt-4o-mini "
             "--model openai:gpt-4o. 미지정 시 settings.ROADMAP_AGENT_MODEL 사용.",
    )
    ap.add_argument(
        "--runs", type=int, default=1, metavar="N",
        help="각 케이스를 N번 반복해 LLM 확률성을 평균낸다 (기본 1). --live에서만 유효.",
    )
    ap.add_argument(
        "--langfuse-upload", action="store_true",
        help="케이스 실행 대신 Langfuse Datasets에 sync만 하고 종료. "
             "LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY env 필요.",
    )
    ap.add_argument(
        "--langfuse-run", metavar="NAME",
        help="--live 실행 결과를 Langfuse dataset run으로 링크한다. NAME이 그룹 이름 "
             "(모델·시각이 뒤에 붙어 유일화). 모델별로 별도 run이 만들어져 UI에서 A/B 비교 가능.",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    cases = [c for c in ALL_CASES if (args.case is None or c.slug.startswith(args.case))]
    if not cases:
        print(f"no cases match {args.case!r}", file=sys.stderr)
        return 2

    if args.langfuse_upload:
        from .langfuse_sync import DATASET_NAME, sync_cases_to_langfuse
        n = sync_cases_to_langfuse(cases)
        print(f"Uploaded {n} case(s) to Langfuse dataset '{DATASET_NAME}'")
        return 0

    if not args.live:
        # dry-run은 모델 무관.
        print(f"Running {len(cases)} case(s) in dry mode")
        outcomes = [run_dry(c) for c in cases]
        for o in outcomes:
            _print_outcome(o, args.verbose)
        passed = sum(1 for o in outcomes if o.ok)
        print(f"\nSummary: {passed}/{len(outcomes)} passed")
        return 0 if passed == len(outcomes) else 1

    models: list[str | None] = args.model if args.model else [None]  # None = env 기본값
    runs = max(1, args.runs)
    by_model: dict[str, list[CaseOutcome]] = {}

    if args.langfuse_run:
        # Langfuse experiment 모드 — dataset.run_experiment로 실행. observe_agent_call이
        # 만든 trace가 dataset run에 자동 링크된다.
        #
        # `run_experiment`는 dataset item당 task를 딱 한 번만 부른다. 예전에는 `--runs 3`을
        # 넘겨도 라벨의 "(N=3)"만 바뀌고 실제로는 1회만 돌았다 — weekly CI가 N=3이라고
        # 적어두고 실제로는 N=1을 관측하고 있었다. 이제 experiment 자체를 N번 돌려서
        # (`-r1`, `-r2`, ...) 반복분이 별개 dataset run으로 남게 한다. Langfuse UI에서는
        # 같은 run_group으로 묶여 비교된다.
        from .langfuse_sync import run_experiment_for_model
        slug_to_case = {c.slug: c for c in cases}
        for m in models:
            label = m if m is not None else "(env default)"
            print(f"\n=== Langfuse experiment: {args.langfuse_run} / model: {label} (N={runs}) ===")

            def _task(*, item, **_kw):
                case = slug_to_case.get(item.id)
                if case is None:
                    return {"skipped": f"no local case for slug {item.id}"}
                outcome = run_live(case)
                return {
                    "reply": outcome.reply_preview,
                    "passed": outcome.ok,
                    "failures": outcome.failures,
                    "elapsed_ms": outcome.elapsed_ms,
                    "iterations": outcome.iterations,
                    "input_tokens": outcome.input_tokens,
                    "output_tokens": outcome.output_tokens,
                    "reasoning_tokens": outcome.reasoning_tokens,
                }

            def _ev_passed(*, output, **_kw):
                return {"name": "passed", "value": 1.0 if output.get("passed") else 0.0}

            def _ev_latency(*, output, **_kw):
                return {"name": "latency_ms", "value": float(output.get("elapsed_ms") or 0)}

            def _ev_iterations(*, output, **_kw):
                return {"name": "iterations", "value": float(output.get("iterations") or 0)}

            for r in range(runs):
                run_label = args.langfuse_run if runs == 1 else f"{args.langfuse_run}-r{r + 1}"
                with _override_model(m):
                    info = run_experiment_for_model(
                        run_name=run_label, model_override=m,
                        task_fn=_task,
                        evaluators=[_ev_passed, _ev_latency, _ev_iterations],
                        run_group=args.langfuse_run,
                    )
                print(f"→ Langfuse run ({r + 1}/{runs}): {info['run_name']}")
                if info.get("url"):
                    print(f"→ URL: {info['url']}")
        return 0

    for m in models:
        label = m if m is not None else "(env default)"
        print(f"\n=== model: {label} (N={runs}) ===")
        with _override_model(m):
            # 케이스 순서 보존을 위해 outer=case, inner=run으로 실행.
            outcomes = [run_live(c) for c in cases for _ in range(runs)]
        for o in outcomes:
            _print_outcome(o, args.verbose)
        by_model[label] = outcomes
        s = _summarize(outcomes)
        print(f"Summary: {s['passed']}/{s['total']} passed  "
              f"median {s['median_ms']:.0f}ms  median iters {s['median_iters']:.1f}")

    if len(by_model) > 1:
        _print_comparison(by_model)

    # exit 코드: 어떤 모델이라도 실패가 있으면 non-zero.
    total_failed = sum(1 for outs in by_model.values() for o in outs if not o.ok)
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
