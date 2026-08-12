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
        # gpt-4o-mini가 종종 ```json ... ``` 로 감싸서 낸다 — 스트립.
        text = content.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1].lstrip("json\n").rstrip("`\n ")
        import json
        data = json.loads(text)
        return bool(data["pass"]), str(data.get("reason", ""))
    except Exception as e:  # noqa: BLE001 - 판정 실패는 fail로 처리하되 이유 노출
        return False, f"judge_error: {type(e).__name__}: {e}"


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


def run_live(case: EvalCase) -> CaseOutcome:
    """LLM 실호출 후 assertion 채점. wall-clock latency도 함께 잰다."""
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
                # finish_response는 spy에 안 잡히므로 (dispatch 경유 X) 수동 태깅.
                tool_log.append({"name": "finish_response", "args": {}})
                # iterations는 roadmap_chat이 return 안 주니 tool 호출 수로 근사.
                iterations = len(tool_log)
                result = EvalResult(
                    reply=out.get("reply", ""), tool_calls=tool_log,
                    iterations_used=iterations,
                    pending_changes_count=len(out.get("pending_changes", []) or []),
                )
            else:
                out = tc_mod.run_timetable_chat(
                    db, user,
                    year=case.timetable_year, semester=case.timetable_semester,
                    message=case.prompt,
                )
                iterations = int(out.get("iterations", 0) or 0)
                result = EvalResult(
                    reply=out.get("reply", ""),
                    tool_calls=list(out.get("tool_calls", []) or []),
                    iterations_used=iterations,
                    schedules_count=len(out.get("schedules", []) or []),
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
