# Changelog

바이브코딩 세션이 끝날 때마다 맨 위에 새 항목을 추가하세요. 형식은 아래 예시 참고.

"기능이 지금 어떻게 동작하는지"는 여기가 아니라 `docs/backend/features/`(백엔드)
또는 `docs/frontend/`(프론트엔드)에 기능별로 정리합니다.
이 파일은 "언제 무엇을 왜 했는지" 시간순 기록입니다.

<!--
## YYYY-MM-DD (github아이디)

- 무엇을 했는지, 왜 했는지, 막혔던 부분/해결법 (필요한 만큼만)
- 관련 기능 문서를 바꿨다면 `docs/backend/features/xxx.md`(백엔드) 또는
  `docs/frontend/xxx.md`(프론트엔드) 갱신도 같이
-->

## 2026-08-13 (blackest21) — 백엔드 전수 점검 + 보안 P0 구현

- **[fix] ⚠️ 졸업요건 판정 버그 2건 (`app/domains/academics/graduation_progress.py`)**:
  백엔드 전수 점검에서 나온 P0. 둘 다 학생에게 잘못된 판정이 보이거나 아예 에러가 났다.

  ① **균형교양 이수학점이 통째로 사라졌다.** portal_sync가 One-Stop 판정을 근거로
  `student_course_records.category`를 '교양선택' → 세부영역명('사상과역사' 등)으로 덮어쓰는데
  (로드맵 챗이 세부영역별 조언을 하려면 필요), 판정 엔진은 raw category로 group by하고
  '교양선택'만 찾았다. 결과: **균형교양 18학점을 이수한 학생이 포털 동기화 후 "교양선택
  0학점 이수, 18학점 남음"** 으로 표시된다. 총 이수학점은 맞아서 눈에 잘 안 띈다.
  영향 범위가 넓다 — 졸업 진단 화면, 로드맵 챗의 `get_graduation_progress`,
  시간표 챗의 `remaining_by_category` 전부. `_CATEGORY_ROLLUP`으로 세부영역을 '교양선택'에
  합산하고, 세부영역 상수를 academics로 옮겨 단일 출처로 만들었다(roadmap_chat이 가져다 씀).

  ② **중복 요건 행이 있으면 500 에러.** `_find_requirement`가 `.one_or_none()`이라
  같은 (program_type, department_id, curriculum_year) 조합이 두 행이면 MultipleResultsFound가
  난다. 실제로 있다 — **간호학과 dual 2026이 2행**이라 그 학생은 졸업요건 조회가 통째로
  죽었다. `graduation_requirements`에 유니크 제약이 없는 게 근본 원인.
  id 순으로 하나를 고르되 `warnings`에 "행이 N개 있어 id=X를 사용함"을 남겨 조용히
  달라지지 않게 했다. 감시는 `scripts/report_duplicate_requirements.py`(read-only).

- **[feat] 보안 P0 4건 구현 (`docs/backend/security-privacy-plan.md` 참고)**:
  - **레이트 리밋** (`app/core/ratelimit.py`): slowapi 도입. 로그인 `5/minute;30/hour`,
    회원가입 `5/hour`, 재설정 `3/hour;10/day`, **챗 `10/minute;100/day`**, portal-sync `5/hour`.
    가장 급했던 건 챗이다 — 로그인만 하면 무제한 OpenAI 호출이 가능했고 한 대화가 입력
    6만 토큰을 쓰기도 한다. 키는 인증 후면 user_id, 아니면 IP(`_user_or_ip`) — IP로만 세면
    같은 학교 네트워크·NAT 뒤 학생들이 서로의 몫을 잡아먹는다. 429는 한국어 + `Retry-After`.
    ⚠️ in-memory 저장소라 워커가 여러 개면 한도가 프로세스 수만큼 느슨해진다.
  - **JWT 무효화** (`core/security.py`): 토큰에 `password_hash` 지문(`pv`)을 넣고 매 요청
    대조. 비밀번호가 바뀌면 옛 토큰이 즉시 무효다. **스키마 변경 없이** 해결했다 —
    사용자 행은 인증 과정에서 어차피 로드하므로 추가 쿼리도 없고, 공유 Supabase에
    손대지 않아도 된다. `pv` 없는 옛 토큰은 거절하므로 **배포 시 재로그인이 한 번 필요**하다.
  - **SecretStr + 422 sanitizer**: portal-sync 비밀번호를 `SecretStr`로(로그·repr에 마스킹),
    `_validation_handler`가 422 응답에서 `input`/`ctx` 제거. pydantic v2는 검증 실패한
    입력값을 에러에 그대로 담아서, 비밀번호가 응답으로 되돌아올 수 있었다.
  - **메일 로그 가드**: `ENV != local`이면 재설정 링크 본문을 로그에 안 찍는다.

  회귀 테스트 `tests/test_security_hardening.py` — 리밋은 TestClient로 실제 429를 확인하고,
  나머지는 "막혀야 하는 시나리오"를 직접 태운다. 유닛 테스트가 엔드포인트 함수를 직접
  호출하는 스타일이라 `tests/conftest.py`에서 리밋을 기본 비활성화하고
  `@pytest.mark.ratelimit`을 붙인 테스트에서만 켠다(리밋 카운터는 프로세스 전역이라
  켜두면 테스트끼리 간섭한다).

## 2026-08-13 (blackest21) — 챗 품질 + 골든 하니스

보안·개인정보 계획 문서화 + 골든 데이터셋 감사/보강 + 그 과정에서 드러난 챗 결함 3건 수정.
DB 마이그레이션 없음, 팀 공유 Supabase 반영 없음 (전부 코드·문서·테스트).

- **[docs] 보안·개인정보 계획 (`docs/backend/security-privacy-plan.md`)**: 데이터 인벤토리
  (S/A/B/C 등급별 저장 위치·암호화·외부 전송 여부), 현재 방어선 감사 결과, 확인된 갭을
  P0/P1/P2로 정리. **P0 4건**: ① 레이트 리밋 전무(로그인 brute force + 챗 LLM 비용 폭탄)
  ② JWT 무효화 수단 없음(비밀번호 변경·탈퇴 후에도 최대 7일 유효) ③ 포털 비밀번호가
  요청 본문으로 들어오는 구간의 잔여 노출(422 echo·예외 로깅) ④ SMTP 미설정 시 재설정
  링크가 로그에 평문 출력(`core/mailer.py:31`). LLM 특화 위협은 별도 표로 정리 — 도구가
  전부 `_ToolContext(db, user, roadmap)`에 바인딩돼 user_id를 인자로 받지 않으므로
  프롬프트 인젝션으로 타인 데이터 조회는 구조적으로 불가하다는 점을 명시하고, 이 성질을
  깨는 변경(도구에 user_id 파라미터 추가)을 PR 체크리스트에 금지 항목으로 넣었다.

- **[docs] LLM 개인정보 경계 감사 (`docs/backend/features/llm-privacy-audit.md`)**:
  `langfuse_masking.py`가 참조하는데 실제로는 레포에 없던 문서(git 히스토리 전체에 없음).
  외부 전송 경로 2개(OpenAI·Langfuse), 프롬프트에 넣는 것/안 넣는 것(이름·학번·이메일은
  코드상 미전송 확인), 마스킹 4패턴과 그 설계 결정 2가지(`\b` 대신 digit 바운더리를 쓰는
  이유 = 파이썬 `\w`가 한글 포함, 학번을 연도 앵커로 좁힌 이유 = course_id 오탐 방지),
  알려진 한계 3가지를 기록.

- **[fix] 골든 하니스의 무의미·오탐 assertion 2건 (`backend/tests/eval/`)**:
  ① `run_live`가 로드맵 케이스에 `finish_response`를 **무조건** 태깅해서 케이스 01의
  `tool_called finish_response`가 항상 통과하는 공허한 검사였다. `run_roadmap_chat`이
  `finished`/`iterations`를 반환하게 하고(timetable 쪽 반환 형태와 정합) 실제 값으로 태깅.
  `iterations`도 도구 호출 수 근사가 아니라 실제 LLM 왕복 수로 바뀌어 두 에이전트를 같은
  기준으로 비교할 수 있다. ② 케이스 18의 `response_absent "화"`는 "최적화"·"변화" 같은
  평범한 단어에 걸리는 오탐이었다 — 반환된 `schedules`의 offering_ids를 직접 보는 custom
  assertion으로 교체(`EvalResult`에 `schedules`/`pending_changes` 원본 추가).

- **[fix] weekly CI의 `--runs`가 조용히 무시되고 있었다 (`.github/workflows/golden-eval-weekly.yml`,
  `backend/tests/eval/run_eval.py`)**: Langfuse `run_experiment`는 dataset item당 task를
  한 번만 부른다. `--runs 3`을 넘겨도 라벨의 "(N=3)"만 바뀌고 실제로는 N=1이 돌았다 —
  주간 관측이 계속 단발 실행이었다는 뜻. experiment 자체를 N번 반복하고
  `weekly-<date>-r1..r3`으로 남기도록 수정(`metadata.run_group`으로 묶어 조회). 워크플로
  주석의 규모·비용 추정과 timeout(45→70분)도 실제와 맞춤.

- **[feat] 골든 데이터셋 21 → 26 케이스 (`backend/tests/eval/cases.py`)**: 도구 자동 판정
  필드 3종 중 `critical_missing_required`(케이스 13)만 회귀 방지가 있었고 나머지 2종과
  도구 단 가드들은 골든에 아예 없었다. 추가: **22** 재수강 요청(`is_retake` 우회 흐름)
  · **23** 선수과목 차단 · **24** 학기당 학점 상한 초과 시 swap 제안 · **25** 계절수업 전용
  과목 정규학기 제외 · **26** 요청 범위 준수. 시드가 의도한 상태를 실제로 만드는지 도구
  응답으로 직접 확인하고 만들었다(24는 처음에 18학점이라 상한 21에 안 걸렸고, 25·26은
  무관한 `critical_missing` 경고에 묻혀서 각각 고쳤다). dry-run에 assertion 명세 정적 검사도
  추가 — 도구를 리네임했는데 케이스를 안 고치면 CI에서 잡힌다.

- **[fix] `propose_change(action="create")`에 course_id 필수 (`roadmap_chat.py`)**:
  케이스 22가 실제 제품 결함을 잡았다. LLM이 `is_retake=True, course_id=None`으로 재수강을
  제안했는데 **모든 가드를 통과**했다 — 이수·중복·재수강·계절수업 검증이 전부
  `course_obj is not None` 분기 안에 있기 때문. 승인하면 과목명·학점·이수구분이 전부 NULL인
  빈 로드맵 행이 생기고 요건 집계에도 안 잡힌다(이 도구는 course_name을 받지 않고
  `apply_pending_changes`가 이름·학점을 Course에서만 가져온다). 마지막 관문으로 거절 추가 —
  과거 학기·학년·학점 상한 같은 더 구체적인 위반이 있으면 그 에러가 먼저 보이도록 순서를
  맨 뒤에 뒀다. 케이스 22: FAIL → PASS.

- **[fix] 진로-전공 mismatch 규칙이 거의 모든 학생에게 붙던 문제 (`roadmap_chat.py`,
  `app/ai/rag/career_keywords.py`)**: 옛 probe는 "진로 목표가 있고 부·복수전공이 없으면"
  무조건 규칙을 붙여서, 정컴 학생 + 백엔드 진로처럼 완벽히 맞는 경우에도 "부전공/복수전공을
  능동적으로 제안해라"는 강한 지시가 매 대화에 실렸다(로드맵 케이스 16개 중 10개에서 발동).
  불필요한 부전공 권유를 유발하고 프롬프트 fatigue로 다른 규칙 준수도까지 떨어뜨린다.
  기존 `CAREER_ALIASES`를 재사용해 근거 기반으로 교체: 진로군에 걸릴 때만, 그 진로군 키워드가
  학과 개설과목(과목명+교과목개요)에 하나도 없을 때만 발동. alias가 느슨해서 생기는 오탐
  ("재무분석가"가 '분석' 때문에 data 진로군에 걸림)은 진로 문구와 과목명의 2글자 겹침으로
  구제한다("재무분석가" ↔ "재무관리"). 결과: 16개 중 **케이스 14 하나에서만** 발동.

- **[fix] 시간표 골든 케이스 5개가 `--live`에서 아예 못 돌고 있었다 (`backend/tests/eval/personas.py`)**:
  시간표 챗이 PR #120에서 세션 영속형이 된 뒤로 `run_timetable_chat`이 `timetable_chat_sessions`/
  `timetable_chat_messages`를 읽고 쓰는데, 페르소나 시더의 `_TABLES`에 그 두 테이블이 없었다.
  케이스 17~21이 LLM에 닿지도 못하고 `no such table`로 즉사(0ms, 0토큰) — 주간 CI는 실패를
  게이트로 안 쓰니 아무도 못 봤다. dry-run이 초록불이었던 이유는 `run_dry`가
  `_TimeTableToolContext`를 직접 부르고 `run_timetable_chat`을 안 거치기 때문. 테이블 추가로
  이제 실제로 돈다.

- **[fix] 429가 pass율을 오염시키고 있었다 (`backend/tests/eval/run_eval.py`)**: 26케이스 × N=3
  스윕에서 **실패 20건 중 12건이 RateLimitError**였다 — 모델 품질이 아니라 하니스가 만든
  실패다. 케이스 하나가 입력 66k 토큰을 쓰기도 해서 연속 실행이면 1분 안에 TPM 200k를 넘는다.
  `run_live`를 1회 실행분(`_run_live_once`)과 재시도 래퍼로 분리하고 20/45/90초 백오프를 넣었다.
  429는 두 경로로 나타나므로(에이전트 LLM은 예외 → `error`, 판정 LLM은 `_llm_judge`가 예외를
  삼켜 `judge_error:` failure 문자열) 둘 다 감지한다.

- **[fix] 시간표 시간 제약을 도구 계층에서 강제 (`backend/app/domains/planning/timetable_chat.py`)**:
  케이스 18이 3/3으로 잡아낸 결함 — 에이전트가 `offering_ids: [6001, 6003]`을 반환하면서
  rationale에는 "월수 오전에 진행되는 데이터베이스와 머신러닝"이라고 **거짓 설명**을 붙였다
  (6003은 화·목 14:00). 제약 위반과 설명 불일치가 동시에 나서 사용자는 잘못된 시간표를
  그대로 믿게 된다. `_CORE_PROMPT`에 이미 "시간 보고 걸러라" 규칙이 있었지만 지켜지지 않았다.
  → 판정을 LLM에 맡기지 않는다. 메시지에서 제약을 파싱(`_parse_time_constraint`)해
  **세 지점에서 강제**한다: ① `list_offered_courses`가 위반 분반을 후보에서 제외
  (`excluded_by_time_constraint`로 사유는 알려줘서 "제약 지키면 학점 모자람"을 설명할 수 있게)
  ② `validate_timetable`이 `time_constraint_violation`으로 거절 ③ `finish_response`가
  위반 조합을 한 번 되돌리고, 그래도 고쳐오지 않으면 해당 조합만 떨어뜨린다.
  파서는 확신 높은 표현만 잡는다 — 오탐으로 정상 후보를 지우는 게 놓치는 것보다 나쁘다.
  "화요일 빼고" 같은 부정형은 오파싱 위험이 커서 의도적으로 제약 없음 처리.
  **케이스 18: 0/3 → 2/3** (남은 1건은 아래 별개 원인).

- **[fix] `finish_response` 3중 가드 — 시간표가 사용자에게 안 나가는 경로 차단 (`timetable_chat.py`)**:
  제약 위반을 막고 나니 케이스 18의 남은 실패가 매번 **다른 형태**로 나타났다. 셋 다
  "검증된 시간표가 사용자 화면에 안 나간다"는 같은 결과라 도구 계층에서 순서대로 막았다
  (각각 한 번씩만 되돌린다 — 무한 왕복 방지, `MAX_TOOL_ITERATIONS=8` 안에서 동작):
  ① **개설 과목이 있는데(`has_any_offering`) validate를 한 번도 안 부르고 빈 schedules로 종료**
  ② **조합을 제출하면서 검증은 안 함** — 충돌·학점 상한 미확인 상태로 사용자에게 나감
  ③ **검증까지 해놓고 결과를 message 텍스트에만 적고 schedules는 비워서 냄** — UI가
  렌더링하는 건 schedules라 사용자에겐 시간표가 안 보인다. `validated_ok_combos`를 기억해뒀다가
  "이 조합을 담아라"라고 지목한다.
  프롬프트에 후퇴 문구를 넣으면 LLM이 그 경로를 선호한다는 게 이미 관측돼 있어(2026-08-12)
  프롬프트 대신 도구로 막았다. **케이스 18: 0/3 → 3/3.**

- **[fix] ⚠️ 운영 데이터 버그 — 개설된 과목을 "미개설"이라고 답하고 있었다 (`timetable_chat.py`)**:
  케이스 21을 파다가 **실제 운영 DB의 문제**를 찾았다. 부산대는 같은 과목명에 개설 주체별로
  다른 교과목코드를 발급하고(ZE/DM/CB/MS 접두사), 개설(`course_offerings`)이 그 형제 행들에
  흩어져 붙는다:

  | 과목 | 2026-2 개설 분산 |
  |---|---|
  | 인공지능과디지털사고 | 65개가 4행 중 1행에만 |
  | 대학영어 | 88개가 2행 중 1행에만 |
  | 공학작문및발표 | 28개가 5행 중 3행에 (24 / 2 / 2) |

  `list_offered_courses`는 카탈로그 `semester`로 후보를 먼저 거른 뒤 그 행의 개설만 조회했다.
  공학작문및발표는 분반 24개가 달린 행(ZE1000043)의 카탈로그 `semester`가 '1'이라 2학기 검색에서
  통째로 빠지고, 살아남은 행(ZE1000119)은 개설이 0이라 **"이번 학기 미개설"로 답했다** —
  실제로는 28개 분반이 열려 있는데. 팀원이 이번 학기 수강 중인 과목이라 실사용에서 바로
  드러났을 버그다.
  → 두 가지로 수정: ① `_sibling_course_ids` — 개설 조회를 검색이 집어온 행 하나가 아니라
  **같은 과목 전체**(과목명+학과+전공이 같은 행들) 대상으로 한다. 학과가 다른 동명 과목
  (일반물리학(I)은 31개 학과에 각각 존재)까지 합치지 않도록 학과·전공을 판정 기준에 포함
  (회귀 테스트 있음). ② 과목명을 콕 집어 물은 경우 카탈로그 `semester` 필터를 푼 재검색을
  병행한다 — 이 필드는 "권장 학기"라 실제 개설과 자주 어긋나고, **개설 여부의 진짜 근거는
  `course_offerings`이지 `courses.semester`가 아니다.**

- **[chore] 중복 행은 ingestion 버그가 아니다 — 탐지 스크립트로 대응 (`scripts/report_course_alias_groups.py`,
  `scripts/import_courses_from_ais.py`)**: 위 건을 ingestion 단계에서 정리할지 조사한 결과,
  **정리 대상이 아니라는 결론**이다. 실측:
  - 같은 (course_code, 과목명, 학과, 전공) 완전 중복 행: **0건** — importer는 멱등하다.
  - 같은 (과목명, 학과, 전공)인데 코드가 갈린 그룹: **7개 / 19행** (전체 6,526행 중).
    코드가 다른 건 부산대가 개설 주체별로 별도 교과목코드를 발급하기 때문이고, 코드는
    수강신청에 필요하므로 **합치면 안 된다**.
  - 같은 course_code가 여러 행인 44건은 교직과목(XA4xxxxx)이 학과별로 등록된 **의도된 구조**다.
  → 그래서 dedup 대신 감시로 간다: `report_course_alias_groups.py`(read-only)가 그룹별 개설
  분산과 학점·이수구분 불일치를 보고하고, AIS importer는 이런 그룹이 **새로 생길 때 경고**를
  출력한다. `--fail-on-inconsistent`로 적재 후 검증에 걸 수 있다.
  **부수 발견 + 병합 기준 정정**: 같은 (과목명, 학과, 전공)인데 이수구분이 두 값인 그룹이
  2건 있다 — `이산수학`(컴퓨터공학전공: CB1501027 1-1 **전공기초** / CB2001104 2-2
  **전공선택**), `생활과통계`(기초교양 | 효원균형교양). 이걸 발견하고 형제 병합 기준을
  (과목명, 학과, 전공) → **(과목명, 학과, 전공, 이수구분, 학점)** 으로 좁혔다. 이수구분이
  다른 항목의 분반을 합쳐 보여주면 학생이 어느 요건을 채우는지 오인하고, 졸업요건 집계가
  이수구분 기준이라 결과가 실제로 달라진다. 정컴 3개 전공(컴퓨터공학 36 / 인공지능 35 /
  디자인테크놀로지 34)은 `major_id`로 이미 정확히 분리돼 있어 서로 섞이지 않는다.
  이수구분 불일치는 교육과정 개편 흔적일 수 있어 원본 확인 전에는 고치지 않고 보고서에
  별도 섹션으로 남긴다.

- **[fix] 미개설 과목이 `results`에 섞여 오독되던 문제 (`timetable_chat.py`)**: 개설이 0인
  과목도 `offered_sections: []`로 `results`에 함께 들어가서, LLM이 "존재하는 과목"으로 읽고
  미개설 사실을 안 알리거나 심지어 시간표에 넣었다고 거짓 주장했다(케이스 21에서 관측).
  → 담을 수 있는 것과 없는 것을 아예 다른 필드로 분리: `results`에는 이번 학기 분반이
  실제로 있는 과목만, 나머지는 `matched_but_not_offered_this_term` + 명시 안내 문구.
  도구 description에도 반영. **케이스 21: 0/3 → 3/3.**

- **[fix] 부전공 학생 시간표에 부전공 과목이 아예 안 나오던 문제 (`timetable_chat.py`)**:
  `list_offered_courses`가 주전공 학과로만 스코프를 잡아서, 부전공·복수전공 학과 개설과목이
  후보에 **한 번도 뜨지 않았다**. 로드맵 챗 `search_courses`에는 `program_type` 파라미터가
  있는데 시간표 챗에만 없던 갭이다. 골든 케이스 20(경영 주전공 + 전자 부전공)에서 회로이론이
  안 보여 담을 수 있는 과목이 주전공 1과목뿐인 상태로 매번 반복 상한까지 헤맸고, 그래서
  이 케이스의 pass율이 1/3~3/3을 오갔다(오늘만 1,3,2,3,1). → `_search_scope()` + 도구
  파라미터 `program_type` 추가(로드맵과 동일 규칙) + 조건부 규칙 `non_primary_programs`로
  "주전공용 한 번, 부전공용 한 번 호출해라" 안내.

- **[fix] 가드 되돌림이 탐색 예산을 잡아먹던 문제 (`timetable_chat.py`)**: 위 가드들은 각각
  iteration을 하나씩 소모하는데, `MAX_TOOL_ITERATIONS=8`은 원래 "후보를 몇 번 훑을까"를
  제한하려고 둔 값이다. 가드가 예산을 먹으면 정작 시간표를 못 짜고 상한에 걸린다 —
  케이스 20·21이 8 iterations에 도달해 실패하는 게 관측됐다. 되돌림은 탐색이 아니라 강제
  교정이므로 예산에서 빼준다(`while iteration < MAX_TOOL_ITERATIONS + guard_retries`).
  되돌림은 종류별 1회씩이라 보정은 최대 +3으로 묶여 있다. 루프를 `range` → `while`로
  바꾸면서 `iteration`이 0-based에서 "실행 횟수"로 바뀌었으므로 반환값·score의 `+1` 보정도
  함께 제거했다.

- **[fix] 케이스 18 시드가 의도한 시나리오를 반만 만들고 있었다 (`tests/eval/cases.py`)**:
  "오전 후보 2개" 설정인데 offering 6002가 인공지능(카탈로그상 **1학기** 과목)에 붙어 있었다.
  `list_offered_courses`가 semester 필터로 먼저 거르므로 후보에 아예 안 잡혀서 실질 후보가
  1개뿐이었다. 2학기 과목(컴퓨터네트워크)으로 교체 — 이제 에이전트가 두 과목을 조합해
  6학점 시간표를 만든다.

- **[known issue] 엇학기 규칙이 사실상 죽어 있다 (`roadmap_chat.py` `_select_applicable_rules`)**:
  조건이 `최신 SCR 연도 - curriculum_year >= 4`인데 이건 엇학기가 아니라 "입학한 지 오래됐나"를
  잰다. 정작 대상인 한 학기 휴학생은 gap 2~3이라 안 걸린다 — 케이스 10이 그래서 3/3 실패
  (**변경 전 코드에서도 0/3, 이번 작업의 회귀 아님**). 고치려다 되돌렸고 근거를 코드 주석에
  남겼다: (a) `project_curriculum_term`은 미래 학기에 "쉬지 않고 다닌다"를 가정해 계산하므로
  "실제 좌표 vs 쉬지 않았을 때 좌표" 비교가 구조적으로 항상 같아진다. (b) 올바른 지표
  (이수 정규 학기 수 < 경과 학기 수)를 적용하면 페르소나 7개가 잘못 걸린다 — 페르소나 데이터가
  자기모순이라서다(케이스 02는 "3학년까지 이수" 설정인데 이수 기록이 2학기치, 그것도 전부
  curriculum_year보다 뒤인 연도). **선행 작업**: 페르소나 이수 기록 연도 정합화 → 지표 교체 →
  N=3 검증.

- **[fix] 범위 한정 요청에 제안 남발 (`roadmap_chat.py`)**: "데이터베이스를 4학년 2학기로
  옮겨주세요. 그것만요"에 컴퓨터네트워크까지 같이 옮기는 게 N=3 중 2회 재현됐다. CORE에
  같은 취지의 규칙이 이미 있었지만 긴 프롬프트 뒤쪽에 묻혀 준수도가 낮았다. 조건부 규칙
  `narrow_scope_request`를 추가하고, **유일하게 학생 DB가 아니라 이번 턴 메시지로** 판정한다
  (`_looks_like_narrow_scope_request`). 프롬프트 맨 끝에 붙어 recency를 확보한다.
  케이스 26: 1/3 → **3/3**, 반복 횟수도 4 → 3으로 감소.

## 2026-07-29 (blackest21)

이번 세션에서 4개 주제 반영. 마이그레이션(`e1f2a3b4c5d6`) 실행이 필요하고, `course_offerings`
적재 파이프라인은 Docker 로컬 검증 후 Supabase 반영이 남았다.

- **[bug fix] 휴학 학기 반영 planned_grade 계산 (`backend/app/domains/planning/history.py`)**:
  3학년 2학기 휴학 후 복학한 학생의 실제 3-2 수강분이 로드맵에서 4-1로 잡히던 버그.
  기존 로직이 `year - curriculum_year + 1`처럼 달력 연도만 썼기 때문. 이수 기록의
  정규 학기(1/2)만 시간순으로 정렬해 1-based 순번을 매기고 `(rank+1)//2`로 학년,
  홀/짝으로 학기를 도출하도록 재작성(`_build_semester_rank`, `_curriculum_term`).
  프론트가 `${planned_grade}-${planned_semester}`로 bucket하기 때문에 planned_semester도
  커리큘럼 기준으로 저장해야 3-2가 제자리에 뜬다. upsert 키에서 planned_semester를
  빼서(달력→커리큘럼 마이그레이션 시 중복 방지) `status=completed, source=manual` 조건으로만
  기존 행을 찾도록 완화. 2021 입학 + 2023-2 휴학 시나리오 유닛 검증 통과.

- **[feat] 로드맵 추천 후보 확장 — 이전 학년 미이수 과목까지 (`backend/app/domains/planning/roadmap_chat.py`)**:
  "4학년 1학기 추천"을 요청하면 4-1 개설 과목만 뽑아 이전 학년에 못 들은 미이수분이
  후보에서 빠지던 문제. 시스템 프롬프트 규칙과 `search_courses` 툴 description을 수정해
  **grade 필터를 웬만하면 걸지 말고 semester+category만 걸도록** 유도. 이전 학년 권장
  과목이라도 학생이 아직 안 들었으면 요청 학기 배치 우선순위에 두고, planned_grade는
  실제 배치할 학년으로 저장하도록 규칙 명시(2학년 권장 전공필수를 4-1에 배치할 땐
  planned_grade=4). category 필드 description에는 세분류(효원균형교양/효원창의교양/
  효원핵심교양/기초교양)까지 나열해 균형만 채우고 싶다 같은 요청에 정확히 반응하게 함
  (별칭 확장은 이미 `_CATEGORY_ALIASES`에 있어 그대로 활용).

- **[feat] AI 대화 세션 관리 API (`backend/app/domains/planning/models.py`, `roadmap_chat.py`,
  `backend/app/api/roadmap_agent.py`, `migrations/versions/e1f2a3b4c5d6_add_roadmap_chat_sessions.py`)**:
  기존엔 로드맵당 하나의 연속 스레드였는데, 사용자가 "새 대화 시작"으로 컨텍스트를
  끊을 수 있도록 세션 개념 도입. 새 테이블 `course_roadmap_chat_sessions(id, roadmap_id,
  title, timestamps)`, `course_roadmap_chat_messages`에 `session_id` FK 추가. 마이그레이션에서
  기존 메시지는 로드맵당 "기본 대화" 세션 하나로 backfill(NOT NULL 승격은 backfill 완료
  후). `run_roadmap_chat`이 `session_id` 옵션을 받고, 히스토리 로딩은 session_id로 좁힘.
  새 API: `POST /agent/sessions`(생성), `GET /agent/sessions`(목록·message_count 포함),
  `DELETE /agent/sessions/{id}`(세션+메시지 삭제, pending_changes는 유지). 기존
  `POST /agent/chat`은 `session_id` 옵션 필드 추가, 응답에 session_id 포함. 기존
  `POST /agent/reset`은 세션까지 지우도록 확장. **pending_roadmap_changes는 세션이
  아니라 로드맵 전역 유지** — 어느 세션에서 제안받든 승인 대상은 하나의 로드맵이라
  일관성을 위해. session title은 첫 메시지 앞 20자로 자동 생성(별도 LLM 호출 없음).

- **[feat] 시간표 추천 AI + Onestop 수강편람 importer**:
  - 크롤러가 만든 `raw_data/crawled_data/onestop_course_catalog/{year}_{semester}/*.csv`를
    `course_offerings`+`course_times`로 적재하는 importer 신설
    (`backend/scripts/import_course_offerings.py`, `backend/app/ingestion/parsers/onestop_course_catalog.py`).
    파서는 `timetable_raw`의 3가지 형태(`HH:MM-HH:MM`, `HH:MM(분수)`, `(외부)병원실습` 태그)를
    처리해 2026-1(6605세션)·2026-2(2292세션) 모두 100% 파싱. importer는 upsert 키
    `(course_id, year, semester, section)`로 멱등, 재실행 시 CourseTime을 전량 삭제
    후 재삽입(강의실/시간 변경 흡수).
  - 2026-2 수강편람 크롤 완료(전 카테고리 4282행). 단 이 시점 2학기 시간표는 개설 정보 중
    시간이 배정된 건 33%뿐 — 학기 개시 전 편람 초기 상태 특성. 시간이 확정된 뒤 크롤을
    한 번 더 돌려 importer 재실행하면 됨(멱등).
  - 시간표 추천 코어(`backend/app/domains/planning/timetable.py`): 대상 학기의 로드맵
    항목에 대해 실제 개설 분반을 조회, (a) 미개설 항목은 `unavailable_courses`로 분리,
    (b) 남은 항목의 분반 조합을 요일·시간 충돌 없이 짜서 완전 조합 상위 M개(`feasible_schedules`),
    (c) 완전 조합이 없으면 부분 조합 상위 M개(`partial_schedules`, 최소 학점 = cap × 0.5,
    N-2 이상 크기), (d) 학점 상한 초과 조합은 `over_cap_schedules`로 분리, (e) 미개설·
    문제 과목에 대해 학과 교육과정 내 대체 후보(`replacement_suggestions`)를 뽑되
    "확정 세트의 어떤 분반과도 안 겹치는 분반이 하나도 없는" 후보는 조용히 배제 —
    사용자 재시도 UX 보호. 조합 랭킹은 요일 수 오름차순 → 같은 요일 공백 시간 오름차순 →
    학점 많은 순. 대체 후보는 대체 대상의 권장 학년 근접도 → 개설 분반 많은 순.
    엔드포인트: `GET /me/roadmaps/{id}/timetable/recommend?year=&semester=`. LLM 미사용
    (결정론적). 이 응답이 반환하는 `unavailable_courses`가 있으면 프론트는 기존 로드맵
    상담 채팅으로 유도해 사용자가 로드맵을 조정한 뒤 시간표를 다시 호출하는 흐름.
  - 코어 로직 유닛 검증(충돌 감지·조합 랭킹·부분 조합·`_grade_to_int` 케이스) 통과.
    실측 검증은 로컬 Postgres에 course_offerings 적재 후 진행 예정.

## 2026-07-22 (blackest21)

- **PNU 통합로그인(SSO) 개편으로 `POST /me/portal-sync` 자동 로그인이 막힘 — 원인은 우리 코드가 아니라 PNU 사이트 버그**:
  - 07-08~07-11 세션(d0won)에선 정상 동작했는데, 그 사이 PNU가 로그인을 `onestop.pusan.ac.kr` 인페이지 레이어 방식에서 완전히 별도 도메인(`login.pusan.ac.kr`, "부산대학교 통합로그인")으로 옮겼다. 실제 로그인 진입점은 `https://login.pusan.ac.kr/onestop/loginPage#login_id`.
  - `pnu_session.py`를 이 새 흐름에 맞게 다시 작성: 직링크 진입 + 탭 클릭 실패 시 페이지 전체 재시도(`_reach_login_form`), 헤드리스 Chromium의 `HeadlessChrome` UA와 `navigator.webdriver` 노출을 정상 브라우저처럼 패치, alert/팝업/네트워크 응답을 캡처하는 진단 로깅 추가.
  - 이렇게 고친 뒤에도 실계정으로 계속 실패해서 끝까지 파봤다: 아이디/비밀번호 인증(`/common/sso/loginProcess`)은 **매번 정상 성공**(`nResult:0`, 유효한 sToken 발급)한다. 문제는 그다음 단계 — 사이트 자체 JS `restoreSite()`가 `onestop.pusan.ac.kr/login/loginCheck`로 세션을 넘기는 폼을 POST하는데, 이때 실어 보내는 `_csrf` 필드 값이 로그인 페이지 HTML에 **`var csrfToken = '';`로 하드코딩된 빈 문자열**이다(자동화 여부와 무관하게 `curl`로 그냥 받아봐도 빈 값 — 저희 크롤러가 만든 문제가 아니라 PNU 페이지 자체의 버그로 보인다). 그래서 onestop 서버가 CSRF 검증에 실패해 `/login`으로 되돌려보낸다.
  - **결론**: 이 상태에선 자동 로그인은커녕 사람이 직접 브라우저로 로그인해도 같은 경로로는 안 될 가능성이 높다. PNU IT에 문의/신고가 필요한 사안. 지도교수 크롤링(`advisor.py`)도 같은 로그인 위에서 동작하므로 동일하게 막혀있다.
  - 이 조사와 별개로 실제로 고쳐서 커밋 대기 중인 것: 편입생 1,2학년 로드맵 추천 버그(`roadmap_chat.py`— `earliest_recorded_grade` 가드), 로드맵 채팅 stateless 여부 확인(정상, 서버가 `course_roadmap_chat_messages`로 영속화), 지도교수 크롤링/DB/프론트 배선(`advisor.py`, `User.advisor_name`) — 단 위 SSO 버그 때문에 실계정 검증은 아직 못 함.

## 2026-07-20 (d0won)

- **로드맵 상담 에이전트를 OpenAI SDK 직접 호출 → langchain으로 전환(멀티 LLM 지원)**:
  `roadmap_chat.py`의 LLM 호출부를 langchain `init_chat_model` + `bind_tools`로
  바꿔서, `settings.ROADMAP_AGENT_MODEL`("provider:model", 기본 `openai:gpt-4o`)
  한 줄만 바꾸면 OpenAI/Anthropic/Google 프로바이더가 교체되게 함. tool 스키마
  (`_TOOLS`, OpenAI function-schema dict를 langchain이 그대로 수용)·`_ToolContext`·
  tool 루프·HITL(제안→confirm) 구조는 그대로 유지. `tool_choice="required"`도
  프로바이더 무관한 `"any"`로 바꿈(langchain이 각 SDK 형식으로 변환).
  `config.py`에 `GOOGLE_API_KEY`/`ROADMAP_AGENT_MODEL` 추가, requirements.txt에
  `langchain-anthropic`/`langchain-google-genai`를 주석 옵션으로 명시(쓸 때 설치).
  실계정으로 chat→propose→confirm 전체 플로우 재검증 완료, 프로바이더 스왑
  (anthropic 지정 시 패키지 없으면 명확한 에러) 동작 확인. 문서:
  `docs/backend/features/growth-roadmap.md` 갱신 + 발표자료 `docs/presentation.md` 추가.

## 2026-07-14 (d0won) - 2

- **로그인 식별자를 학번에서 다시 이메일로 되돌림**: PR #81(학번 전환) 머지 후
  프론트엔드(`AuthPage.tsx`, `api/auth.ts`)가 여전히 이메일 기반 계약을 쓰고
  있어서(목업 로직도 `mock@plan-u.local` 등 이메일 전제) `POST /auth/login`이
  422로 깨지는 걸 실제로 확인했다. 학번 기반으로 바꾸려면 프론트도 같이 바꿔야
  하는데 지금은 조율이 안 된 상태라, 백엔드를 원래 이메일 방식으로 되돌렸다.
  `SignupRequest`/`LoginRequest`/`UserResponse`에 `email` 필드 복구,
  `User.email` 컬럼 다시 NOT NULL로. PR #81이 추가한 마이그레이션
  (`d0e1f2a3b4c5`, email nullable화)은 라이브 DB에 한 번도 적용되지 않은 상태였어서
  파일째로 삭제 — 안전하게 되돌릴 수 있었다. 문서: `docs/backend/features/core-auth.md`,
  `docs/frontend/frontend-api-guide.md` 갱신. 나중에 학번 방식으로 다시 갈 땐 프론트
  작업과 같이 진행할 것.

## 2026-07-14 (d0won)

- **로그인/회원가입 식별자를 이메일 → 학번(student_id)으로 변경**: 프론트 팀이
  공유한 "1b. 로그인 → 학생정보 입력(포털 계정 자동 크롤링 온보딩)" 와이어프레임에
  맞춤. 앱 계정(학번+비밀번호)과 One-Stop 포털 크롤링 자격증명(`POST /me/portal-sync`)은
  계속 분리 유지하되, 로그인 화면 자체는 학번 하나로 통일. `SignupRequest`/
  `LoginRequest`/`UserResponse`에서 `email` 필드 제거. `User.email` 컬럼은 지우지
  않고 nullable로만 바꿈(과거 데이터 호환, 마이그레이션 `d0e1f2a3b4c5`).
  `student_id`는 원래도 nullable+unique 컬럼이라 DB 스키마 변경 없이 애플리케이션
  레벨에서 필수로 강제. **주의**: 기존 라이브 유저 중 `student_id`가 비어있는 계정은
  로그인 식별자가 없어져서 로그인이 불가능해짐(현재 4명 중 3명 — 테스트 계정으로
  추정, 확인 후 정리 필요). **브레이킹 체인지 — 프론트엔드 `AuthPage.tsx`의 이메일
  입력칸을 학번 입력칸으로 바꿔야 함.** 문서: `docs/backend/features/core-auth.md`,
  `docs/frontend/frontend-api-guide.md` 갱신.

## 2026-07-14 (d0won)

- **로드맵 Agent가 요청 범위를 벗어나 제안을 남발하던 문제 수정**: "이 과목
  4학년 1학기로 옮겨줘"처럼 기존 항목 하나만 콕 집어 요청해도, gpt-4o가 물어보지
  않은 과목을 3개씩 추가로 `propose_change`하다가 `MAX_TOOL_ITERATIONS`를 다 써서
  `finish_response`를 못 부르고 뭉뚱그린 사과문으로 응답이 끝나는 경우를 실계정
  테스트로 재현. 시스템 프롬프트에 "요청 범위를 벗어난 제안 금지" 규칙을 추가하고,
  `finish_response` 없이 루프가 끝나는 경우 사과문 대신 `tool_choice="none"`으로
  한 번 더 불러 지금까지의 tool 결과를 요약한 실제 답변을 받아내도록 폴백을
  고쳤다. 재현 테스트로 "하나만 추천해줘"/"이 과목만 옮겨줘" 둘 다 정확히 1개
  제안만 나오는 것 확인.


## 2026-07-13 (d0won) - 4

- **로드맵 Agent update/delete/멀티턴 E2E 테스트, delete FK 위반 버그 수정**:
  실계정으로 `action="update"`(과목 학기 변경), `action="delete"`(과목 제거),
  멀티턴 대화("방금 제안한 과목을 4학년 1학기로 옮겨줘" 같은 이전 턴 참조)까지
  마저 테스트했다. `confirm`에서 `action="delete"`를 승인하면
  `course_roadmap_items`를 지우는데, 그 항목을 가리키는
  `pending_roadmap_changes.item_id`(승인 대상 change 자신 포함)가 남아있어서
  FK 제약 위반(`ForeignKeyViolation`)으로 confirm 자체가 실패하는 버그를 발견 —
  삭제 직전에 해당 item을 가리키는 모든 `pending_roadmap_changes.item_id`를
  null로 끊어준 뒤 삭제하도록 고쳤다. 테스트 중 쌓인 더미 로드맵 항목/pending
  change/채팅 기록은 정리함.


## 2026-07-13 (d0won) - 3

- **AI 로드맵 상담 Agent를 OpenAI로 전환 + 실계정 E2E 테스트, 신뢰성 버그 수정**:
  `.env`에 `ANTHROPIC_API_KEY`가 없어서 `roadmap_chat.py`를 OpenAI(`gpt-4o`)
  tool-calling으로 다시 짜서 실제 채팅 흐름을 처음부터 끝까지 테스트했다.
  테스트 중 `gpt-4o`가 `search_courses`/`propose_change` 없이 그냥 텍스트로
  과목명을 나열하고 끝내버려 `pending_changes`가 비어있는 경우를 발견 —
  매 턴 `tool_choice="required"`를 강제하고, 사용자에게 보이는 답변도
  `finish_response` 도구 호출로만 나가게 만들어(일반 텍스트 응답 자체를
  차단) 고쳤다. 실계정으로 반복 테스트해서 매번 과목 제안 → `pending_roadmap_changes`
  생성 → 부분 승인/거절(`POST .../agent/confirm`)까지 정상 동작 확인.
  문서: `docs/backend/features/growth-roadmap.md`의 "AI 로드맵 상담" 절 갱신.

## 2026-07-12 (d0won)

- **AI 로드맵 상담(human-in-the-loop) 추가**: `POST /me/roadmaps/{id}/agent/chat`
  (Anthropic tool-calling으로 로드맵 변경 "제안") + `POST /me/roadmaps/{id}/agent/confirm`
  (사용자가 승인한 것만 실제 반영). Agent는 `course_roadmap_items`를 절대 직접
  쓰지 않고 항상 `pending_roadmap_changes`에 제안만 쌓는다 — 생성/수정/삭제 모두
  동일한 승인 절차를 거친다. 신규 테이블: `course_roadmap_chat_messages`(대화
  히스토리, 로드맵당 하나의 연속 대화), `pending_roadmap_changes`. LangGraph는
  쓰지 않음 — tool 호출 루프 한 번 → 제안 저장 → confirm 별도 호출, 순서가 고정된
  단순 파이프라인이라 그래프 엔진이 필요 없다고 판단.
  RAG 담당자가 만든 `CurriculumRetriever`(`app/ai/rag/curriculum_retriever.py`)를
  `search_courses` 도구에 그대로 연결해 과목 후보 검색을 맡겼다.
  문서: `docs/backend/features/growth-roadmap.md`의 "AI 로드맵 상담" 절 추가.

## 2026-07-13 (d0won) - 2

- **RAG pgvector 임베딩 검색을 기본으로 끔**: `courses`/`graduation_requirements`가
  이미 학과/전공/학년/학기/이수구분이 정형 컬럼으로 있는 카탈로그 데이터라, 자유
  텍스트 의미 검색이 필요한 상황이 아니라고 판단. `CurriculumRetriever.search`/
  `GraduationRequirementRetriever.search`와 `RagSearchRequest`의 `use_vector`
  기본값을 `false`로 변경 — 구조화 DB 필터 + 진로 키워드 랭킹만 기본 경로로 쓴다.
  `RagChunk`/pgvector 스키마는 지우지 않고 남겨둠(나중에 필요해지면 `use_vector=true`로
  다시 켤 수 있음). 이 결정으로 벡터 검색 관련 미해결 이슈 3건(테스트 부재, 예외 처리,
  `embed_missing` 연도 미scope)은 우선순위에서 빠지고, `career_keywords.py` 진로
  키워드 확장이 랭킹 품질을 좌우하는 유일한 경로가 되어 우선순위가 올라감. 문서:
  `docs/backend/features/roadmap-rag.md` 갱신.

## 2026-07-13 (blackest21)

- **RAG / 학사 지식 기반 구축 PR #69 반영 및 Supabase 적용**
  - 수강 로드맵 Agent가 `courses`와 `graduation_requirements`를 구조화된 검색 결과로
    받을 수 있도록 DB-first Retriever를 추가했다. 입력은 `query`, `department_id`,
    `major_id`, `curriculum_year`, `filters`이고, 출력은 `course_id`, `course_name`,
    `category`, `credits`, `grade`, `semester`, `evidence`와 보조 필드 `source`, `score`,
    `document_type`이다.
  - `POST /rag/curriculum/search`, `POST /rag/graduation-requirements/search`,
    `POST /rag/ingest` API를 추가했다. Agent 담당자는 우선 `use_vector=false`로 안정적인
    DB-first 검색을 사용하고, embedding 생성 후 `use_vector=true`로 pgvector 검색을 함께
    사용할 수 있다.
  - pgvector 확장을 위해 `rag_chunks` 테이블을 추가했다. `courses`와
    `graduation_requirements`를 읽어 `document_type`, `department_id`, `major_id`,
    `curriculum_year`, `category`, `grade`, `semester`, `course_id`, `content`, `evidence`,
    `source`, `metadata`, `embedding`을 저장한다. 마이그레이션 리비전은
    `a3b4c5d6e7f8`.
  - `CurriculumRagIngestionService`와 `scripts.build_rag_chunks`를 추가했다. 재실행 시 해당
    교육과정연도의 기존 chunk를 지우고 다시 생성한다. `OPENAI_API_KEY`가 있으면 embedding을
    생성하고, 없으면 `--skip-embeddings`로 chunk만 생성할 수 있다.
  - 진로 질의 1차 ranking을 위해 `AI 개발자`, `백엔드 개발자`, `데이터 분석가` 같은 표현을
    관련 키워드로 확장하는 `career_keywords.py`를 추가했다. DB-first 검색에서도 관련 과목이
    우선 정렬되고, pgvector 검색 시 query embedding에도 확장 키워드를 반영한다.
  - 로컬 검증: `compileall` 통과, `tests.test_rag_retriever` 3개 통과, OpenAI
    `text-embedding-3-small` 호출 결과가 1536차원임을 확인해 `VECTOR(1536)` 설계와 일치함을
    확인했다. API 키는 코드/커밋/PR 본문에 저장하지 않았다.
  - Supabase 적용: `alembic upgrade head`로 `a3b4c5d6e7f8`까지 적용했고,
    `python -m scripts.build_rag_chunks --curriculum-year 2026 --skip-embeddings`로
    `rag_chunks` 7,298개를 생성했다. 세부 수량은 curriculum 6,444개,
    graduation_requirement 854개, embedding 0개다. 현재는 embedding 미생성 상태라
    vector 검색은 DB-first fallback으로 동작한다. `OPENAI_API_KEY` 설정 후
    `python -m scripts.build_rag_chunks --curriculum-year 2026`을 실행하면 embedding까지 생성된다.

## 2026-07-11 (d0won)

- **`GET /me/graduation` 실계정 E2E 검증**: 크롤링 데이터 삭제 → `POST /me/portal-sync`
  재크롤링 → `GET /me/graduation` 순서로 전체 플로우 확인. 매칭 로직은 정상 동작.
  2023년 입학생 계정 테스트 중 `graduation_requirements`에 2026년 기준만 있어 정확한
  연도 매칭이 안 되고 최신 연도 폴백으로 대체되는 게 확인됨 — **2026년 기준만 우선
  지원하기로 결정**, 다른 연도 seed는 보류. 폴백 로직이 이미 처리 중이라 코드 변경
  없음. 문서: `docs/features/my-info-graduation-check.md`의 "졸업요건" 절 갱신.

## 2026-07-10 (d0won) - 4

- **`GET /me/graduation` 재구현**: PR #59 철회로 유일하게 남은 flat
  `graduation_requirements` 테이블과 `student_course_records`를 이수구분별 합계로
  대조해 졸업까지 남은 학점을 계산하는 API를 다시 만들었다(팀원 엔진 삭제 전
  한 차례 만들었다가 되돌린 것과 동일한 설계 — 이번엔 유지).
  `app/domains/academics/graduation_progress.py`(매칭 로직), `app/api/graduation.py`
  (엔드포인트, `main.py`에 등록). 기본은 주전공만 계산하고
  `include_non_primary=true`로 복수전공/부전공까지 확장한다. 문서:
  `docs/features/my-info-graduation-check.md`의 "졸업요건" 절 갱신.

## 2026-07-10 (d0won) - 3

- **팀원의 졸업요건 스키마(PR #59, `feat/graduation-requirement-schema`) 전체 철회** —
  팀원과 상의 후 결정. 삭제 대상: `academic_programs`/`academic_program_aliases`/
  `requirement_sets`/`requirement_categories`/`requirement_courses`/
  `requirement_condition_groups`/`requirement_condition_group_courses` 모델 클래스,
  `app/domains/academics/graduation_engine.py`, `app/api/graduation.py`
  (`GET /me/graduation`), 관련 마이그레이션 5개(`a1c3e5b7d9f2`~`e5a7c9d1f3b6`), seed
  스크립트 3개(`seed_academic_programs.py`/`seed_graduation_requirements.py`/
  `seed_regulation_credit_requirements.py`), seed CSV 6개, `docs/features/db-schema-reference.md`.
- 삭제한 5개 마이그레이션은 애초에 라이브 Supabase에 한 번도 적용되지 않은 상태였다
  (alembic head가 그 이전 리비전 `f6a7b8c9d0e1`에 머물러 있었음 — `departments.id`
  91개, `graduation_requirements` 125행 등 실제 라이브 데이터와 대조해 확인). 그래서
  파일만 지우면 로컬 마이그레이션 head가 라이브 DB 실제 상태와 다시 정확히 일치하고
  (`alembic check` "No new upgrade operations detected." 확인), 별도 downgrade 마이그레이션
  없이도 안전했다.
  `GraduationRequirement`(flat, `graduation_requirements`) 모델 클래스는 되살려서
  `app/domains/academics/models.py`에 유지 — 이게 지금 유일하게 남은 졸업요건 테이블이다.
- 문서: `docs/features/my-info-graduation-check.md`의 "졸업요건" 절 전면 갱신.
  졸업요건 확인 페이지(학생 이수내역 대조 API)는 아직 구현 전 — 다시 만들어야 함.

## 2026-07-10 (d0won)

- **"교과목구분별 이수구분" 크롤링 저장 방향 철회**: 2026-07-09에 결정했던, One-Stop
  졸업예정정보 표(테이블 1)를 그대로 크롤링해 졸업요건 진행 현황으로 저장하는 방향을
  철회한다. 실제 계정으로 확인한 결과 이 표의 "기준학점" 값이 실제 학과가 요구하는
  기준학점과 다른 경우가 있어, 그대로 신뢰하면 사용자에게 잘못된 졸업요건 충족 여부를
  보여줄 위험이 있다고 판단했다. 코드 구현 전(문서 설계 단계)이라 되돌릴 코드는 없다.
  졸업요건 확인 페이지의 데이터 출처는 다시 미정 상태 — 팀원의 `requirement_sets`/
  `graduation_engine.py` 완성, `graduation_requirements` flat 테이블 보강, 또는
  크롤링+기준학점 override 하이브리드 중 재검토 필요. 문서:
  `docs/features/my-info-graduation-check.md`의 "졸업요건" 절 갱신

## 2026-07-09 (d0won) - 2

- 졸업요건 확인 페이지 설계 방향 결정: 학과 마스터 요건(`graduation_requirements` flat
  테이블, 팀원의 새 `requirement_sets`/`requirement_categories`/`requirement_courses`)을
  우리가 직접 학생 이수내역과 매칭하는 대신, One-Stop 졸업예정정보 페이지의
  "교과목구분별 이수구분" 표(`graduation_expected_info.py` 테이블 1,
  `subject_category_completion`)를 그대로 크롤링해서 쓰기로 함
  - 이 표는 학교가 이미 학적신청구분(주전공/복수전공/부전공) × 사정구분(전공기초/
    전공필수/...)별로 기준학점 vs 취득학점 vs 이수여부까지 계산해서 줌 — 심화전공/
    최소전공인정학점/졸업기준평점평균처럼 우리 크롤링 데이터만으론 계산 불가능한
    항목까지 포함
  - 팀원의 새 판정 엔진(`graduation_engine.py`)은 스스로 문서화한 대로 아직 미완성
    (university_default 폴백, 교직 학점 매핑, 조건그룹 판정 등 미구현)이라 지금 단계에선
    크롤링 방식이 더 정확하고 구현도 빠름
  - `graduation_requirements`는 삭제하지 않기로 함(팀원 마이그레이션 체인의 DROP 포함
    구간은 라이브 DB에 미적용 상태로 보류). 팀원의 요건 스키마는 나중에 로드맵 AI가
    과목 단위로 추천할 때 필요할 수 있어 유지
  - 크롤링 표에 학적신청구분이 이미 있어서, 새로 만들 테이블도 주전공뿐 아니라 재학 중인
    복수전공/부전공(또는 저학년의 신청 예정 상태)까지 같은 테이블에서 program_type으로
    구분해 동시에 저장하기로 함
  - 문서: `docs/features/my-info-graduation-check.md`의 "졸업요건" 절 갱신
  - 다음 세션에서 실제 테이블(`graduation_category_progress`)/정규화 함수/API 구현 예정

## 2026-07-09 (blackest21) - 4

- **flat `graduation_requirements` 전공기초 컬럼 보강**
  - 기존 live flat seed는 `graduation_requirements`에 전공기초 전용 컬럼이 없어 별표2의
    `major_foundation` 값을 보존하지 못했다. 전공선택에 합산한 것이 아니라, flat 컬럼
    구조상 빠져 있던 값이다.
  - `required_major_foundation` 컬럼을 추가하는 Alembic 리비전
    `f6a7b8c9d0e1`을 `e5f6a7b8c9d0` 바로 뒤에 추가했다.
  - `scripts/seed_live_flat_graduation_requirements.py`가 이제 별표2 `전공기초`를
    `required_major_foundation`, `전공필수`를 `required_major_required`,
    `전공선택+심화전공`을 `required_major_elective`로 분리해 넣는다.
  - Supabase live DB에도 `f6a7b8c9d0e1`까지 적용 후 125행을 재시드했다. 검증 결과
    `graduation_requirements` primary/2026 125행 중 전공기초 값이 있는 행은 119행이고,
    원본 전공기초 칸이 빈 약학/의예/의학/치의예/치의학 6행은 null로 유지된다.

## 2026-07-09 (blackest21) - 5

- **One-Stop 졸업예정정보 저장 구조 검토 PR 작성**
  - 로컬 사용자 동의 크롤링으로 확인한 졸업예정정보 table 1(교과목구분별 이수구분),
    table 3(교양선택 영역별 이수여부), table 6(비학점 졸업요건) 구조를 바탕으로,
    어떤 데이터를 저장하고 서비스에서 어떻게 활용할지 PR 본문에 검토 요청으로 정리했다.
  - 결론은 Supabase에 바로 테이블을 만들지 않고, 우선 `graduation_audits`,
    `student_graduation_category_statuses`, `student_general_education_area_statuses`
    3개 테이블 추가를 검토 대상으로 제안하는 것이다. TOPCIT/외국어/졸업과제 등 table 6
    비학점 요건 저장은 MVP 범위에서 보류한다.
  - 현재 서비스 코드는 `extract_graduation_expected_info(page)`로 졸업예정정보 7개 테이블을
    이미 크롤링하지만, DB에는 table 0(주전공/복수전공/부전공/연계전공 신청 정보)만
    저장한다는 점을 명확히 기록했다.
  - 별도 장문 md 파일은 GitHub 문서 일관성을 위해 만들지 않고, 이번 항목은 changelog 기록과
    PR 본문 검토 요청만 남긴다. Supabase 마이그레이션/API 동작 변경은 없다.

## 2026-07-09 (blackest21) - 3

- **DB seed 진행 기록을 `docs/CHANGELOG.md`로 통합**
  - 별도 `docs/progress.md` 파일과 `docs/progress/*` 폴더를 쓰지 않고, GitHub에서 바로 보이는
    이 changelog를 DB seed/졸업요건 진행상황의 단일 기록지로 사용한다.
  - 원칙: 2026 현행 학부/전공 계층은 AIS 2026 기준, `departments`는 학과/학부 단위,
    `majors`는 학부 아래 세부전공 단위, 전공을 가진 부모 학과 조회 시 `major_id IS NULL`
    조건 필수. 폐과/비학부/전문대학원 행은 별표에 졸업학점 기준이 있어도 2026 학부
    계층에 임의 추가하지 않는다.
  - 2026 계층/과목 seed 완료 상태: Supabase 기준 `schools` 1 / `colleges` 16 /
    `departments` 109 / `majors` 36 / `courses` 6,402. 재현 명령은 `cd backend` 후
    `python -m scripts.seed_school_hierarchy`, `python -m scripts.import_courses_from_ais`.
  - 주요 배치 결정: 핀테크융합전공은 경영대학 직속, 지능형헬스사이언스융합전공은
    자연과학대학 직속, EES융합전공은 학부대학 첨단융합학부 전공. 첨단융합학부 현행
    전공은 `미래에너지전공`, `나노소자첨단제조전공`, `광메카트로닉스공학전공`,
    `AI융합계산과학전공`, `EES융합전공`.
  - 별표의 `나노에너지공학과`, `나노메카트로닉스공학과`, `광메카트로닉스공학과`는
    2026 학과분류자료집에서 폐과로 확인되어 라이브 계층에 새 department로 추가하지 않았다.
  - 라이브 Supabase revision `e5f6a7b8c9d0` 기준 flat `graduation_requirements`에
    2026 주전공 졸업학점 기준 125행을 반영했다. 범위는 별표2 page 31-36 중 라이브
    계층 매칭 123행 + 별표2-2 page 38 융합전공 중 매칭 2행
    (`지능형헬스사이언스융합전공`, `핀테크융합전공`).
  - flat 컬럼 매핑: 총계 → `required_total_credits`, 전공기초 → `required_major_foundation`,
    전공필수 → `required_major_required`, 전공선택+심화전공 → `required_major_elective`,
    효원핵심교양 →
    `required_general_required`, 효원균형교양+효원창의교양 →
    `required_general_elective`, 일반선택 → `required_free_elective`.
  - 라이브 계층에 매칭하지 않은 별표 행: 폐과 학부 행
    (`나노에너지공학과`, `나노메카트로닉스공학과`, `광메카트로닉스공학과`,
    `식물생명과학과`, `동물생명자원과학과`), 전문대학원 학석사통합과정 학사과정
    (`치의학전문대학원`, `한의학전문대학원`), 라이브 계층 미존재 `미래자동차융합전공`,
    라이브 `majors` 미존재 `의생명융합공학부 첨단바이오공학전공`.
  - 재실행 명령: `cd backend` 후 page 31-36은
    `python -m scripts.seed_live_flat_graduation_requirements --replace --apply`, page 38
    융합전공은 `python -m scripts.seed_live_flat_graduation_requirements --only-annex2-2 --apply`.
    스크립트는 같은 `(program_type, curriculum_year, department_id, major_id)` 행을 먼저
    지우고 다시 넣어 중복을 만들지 않는다.
  - 새 `requirement_sets` 스키마는 flat `graduation_requirements`를 장기적으로 대체하기 위한
    작업이고 아직 라이브 DB에는 적용하지 않았다. 부전공/복수전공은
    `requirement_sets.program_type`, 교직은 primary 요건세트의
    `teacher_training_basic` / `teacher_training_pedagogy` 카테고리로 표현한다.
  - 남은 일: `의생명융합공학부 첨단바이오공학전공`을 2026 현행 계층에 포함할지 확인,
    live flat 테이블과 새 `requirement_sets` 스키마 중 PR 범위 확정, 부전공/복수전공/교직
    세부 요건 seed 완성, 새 스키마 적용 전 현재 flat 125행을 `requirement_categories`로
    이전하는 경로 마련.
- **작업폴더 단일화**
  - 별도로 남아 있던 `../planU-codex` git worktree를 제거하고, 앞으로는
    `pnuai-a-03-team-u` 하나에서만 관리한다.
  - `planU-codex`에만 있던 `outputs/` 산출물은 별도 폴더로 유지하지 않고 제거했다.
    로컬 산출물이 필요하면 새 임의 폴더를 만들지 말고 기존 raw_data 위치만 사용한다.
  - 남아 있던 보조 worktree `.worktrees/machine-eng-subtracks`도 제거해 `git worktree list`
    기준 현재 작업폴더 하나만 남겼다.
- **주전공 졸업요건 계산 API 추가**
  - `GET /me/graduation`으로 현재 사용자 주전공(primary)의 졸업요건 충족 여부를 계산한다.
  - 엔진은 `RequirementSet`/`RequirementCategory`/`RequirementCourse`와
    `StudentCourseRecord`를 대조해 총 이수학점, 남은 총학점, 카테고리별 이수/남은 학점,
    필수과목 충족 여부, 경고를 반환한다.
  - `user_academic_programs.academic_program_code`가 비어 있는 과거 데이터도
    `departments`/`majors`의 브리지 코드로 보강해 요건세트를 찾는다.
  - 부전공/복수전공/교직은 seed 우선순위에서 밀어둔 상태라 기본 계산에서 제외한다.
    필요 시 `include_non_primary=true`로 실험적으로 함께 조회할 수 있다.

## 2026-07-09 (blackest21) - 2

- **primary(주전공) 졸업요건 시드 준비 완료** (같은 브랜치, 로컬 검증까지 — Supabase 반영은 승인 대기)
  - `scripts/seed_academic_programs.py`: 프로그램 마스터 151 + 별칭 335 upsert + **계층 브리지 backfill**
    (departments 107/majors 36, school_hierarchy_mapping.csv 기반). 코드 하나가 계층 여러 행에
    걸치는 케이스 처리: 기계공학부(학부공통+세부전공 5행)는 학과 레벨 우선, 조선·해양공학과
    (`U...075;U...133` 세미콜론 이중코드)는 일반과정 코드 우선
  - `scripts/seed_graduation_requirements.py`: raw_data 후보 CSV + corrections(17,555건 검토 반영)
    → **primary 요건세트 148 / 카테고리 73 / 과목 11,321** 적재. `--program-types` 기본 primary —
    부전공/복수전공은 나중에 같은 스크립트로 확장, 교직 행은 어휘 재정리 전까지 제외.
    prune는 이번 실행 범위 세트로 한정(나중에 적재된 타 유형 행 보호)
  - 시드 CSV 4개(backend/seeds/)를 codex 브랜치에서 이관 (corrections 9.2MB 포함)
  - 로컬 검증: 두 시드 멱등(재실행 행 수 불변) / department_id 미해석은 의도된 제외 7건뿐
    (교양학부 5계열·기타모집단위·GSP) / 시드 실데이터로 엔진 스모크(핀테크융합전공 —
    학점 미달 False, 교양 영역 판정불가 None, 필수과목 10건 미이수 체크) / 골든테스트 통과
  - 반영 순서와 라이브 적용 현황은 이 changelog의 최신 DB seed 항목 참고

## 2026-07-09 (blackest21)

- **졸업요건 스키마 재설계: 부전공/복수전공/교직 표현 + codex 브랜치 main 통합**
  (브랜치 `feat/graduation-requirement-schema`, 스키마+마이그레이션까지 — 엔진 확장/시드는 다음 세션)
  - codex/graduation-academic-programs 브랜치(+stash 세션#15 정리분 커밋 `6465c12`)의
    판정 엔진·requirement_* 스키마·골든테스트를 main 계층 위로 포팅
  - 핵심 설계: ① 부전공/복수전공 = requirement_sets의 program_type 행(별도 테이블 아님),
    ② 교직 = primary 세트의 teacher_training_basic(△)/teacher_training_pedagogy(□, 8학점)
    카테고리(별도 program_type 아님), ③ 대학 공통 기본규칙 = scope='university_default' 행,
    ④ 부전공/복수전공 불가 학과 = offering_status='not_offered' 행,
    ⑤ 택N/M = requirement_condition_groups(+_courses) 2테이블 신규,
    ⑥ 계층↔요건 브리지 = departments/majors/user_academic_programs.academic_program_code,
    ⑦ flat graduation_requirements DROP
  - **`f1a2b3c4d5e6`(reset) 동결 수리**: 라이브 모델 import+create_all 구조를 도입 당시 DDL
    하드코딩으로 교체 — 빈 DB에서 `alembic upgrade head` 전체 체인 재생이 처음으로 성공
    (신규 팀원 로컬 셋업/CI 셋업 가능해짐. 기존 Supabase에는 무영향)
  - 신규 리비전 5개(`a1c3e5b7d9f2`→`e5a7c9d1f3b6`), 전부 plain DDL + downgrade 포함
  - 검증(로컬 Postgres, Supabase 미접촉): 빈 DB 전체 체인 upgrade ✓ / downgrade 왕복 ✓ /
    `alembic check` drift 0 ✓ / 골든테스트 TC01~TC10 전부 통과 ✓
  - 문서: 이 changelog의 최신 DB seed 항목(설계 근거·다음 TODO),
    `docs/features/db-schema-reference.md`(스키마 레퍼런스 갱신)

## 2026-07-09 (d0won)

- 성적 크롤링 시 `courses` 카탈로그 매칭 시도 제거 (`app/ingestion/normalizers/pnu_normalizer.py`)
  - 과거 이수 과목은 크롤링 시점 기준 예전 교육과정 소속이라, 현재 카탈로그(2026 교육과정 기준)에 이름이 아예 없는 경우가 실제로 있음(예: 개편/폐지된 "의생명융합입문")
  - 실제 계정으로 검증해보니 20과목 전부 `unmatched`로 나와서 매칭 자체가 의미 없다고 판단
  - `_link_course_catalog` 함수와 호출 제거. `StudentCourseRecord.course_id`는 항상 null, `match_status`는 모델 기본값(`unmatched`)으로 고정
  - `course_name`/`category`/`credits`는 애초에 이 매칭과 무관한 성적표 원본 스냅샷이라 로드맵 표시엔 영향 없음

## 2026-07-08 (d0won) - 4

- 성장 로드맵: `category`/`credits`를 다시 스냅샷 컬럼으로 복원 (`course_roadmap_items`)
  - 바로 전 세션(-3)에서 join 방식으로 뺐었는데, 과거 이수내역은 `course_id`가 unmatched/ambiguous인 경우가 실제로 흔해서 join만으로는 학점 자체를 못 보여주는 문제 발견
  - 성적표 원본(`StudentCourseRecord`)엔 `course_id` 매칭 여부와 무관하게 학점/이수구분이 이미 정확히 있어서, 매칭이 필요 없는 값 → 스냅샷으로 되돌려도 안전
  - `department_name`/`major_name`은 계속 join 방식 유지 (성적표 원본에 학과 정보 자체가 없음)
- 성장 로드맵: `POST /me/portal-sync` 완료 시 사용자의 모든 로드맵에 이수내역 자동 반영
  - 로드맵을 처음 만들 때만 과거 이수내역이 채워지고, 이후 크롤링해도 기존 로드맵엔 새 학기가 반영 안 되던 문제 발견·수정
  - `GET /me/roadmaps/current`는 계속 조회만 함 — 열 때마다 매번 동기화하면 체감 지연이 생겨서, 동기화는 크롤링 시점에만 하도록 분리
- 실제 계정으로 `POST /me/portal-sync` 엔드투엔드 테스트 중 버그 3건 발견·수정 (`app/api/portal_sync.py`)
  - `.env` 마지막 줄 개행 누락으로 `CREDENTIAL_ENCRYPTION_KEY`가 이전 값에 붙어버린 문제
  - `CourseRecordResponse.course_name`이 실제 컬럼명(`raw_course_name`)과 달라 검증 실패 → `Field(validation_alias=...)`로 매핑
  - `AcademicProgramResponse.major`가 오늘 리팩토링(`major` 텍스트 → `major_id` FK)을 반영 못 해서 검증 실패 → FK로 조회해 채우도록 수정
  - 함수 단위 테스트만으로는 못 잡고 실제 엔드포인트를 호출해봐야 드러나는 문제들이었음

## 2026-07-08 (d0won) - 3

- 로드맵 항목(`course_roadmap_items`) 스냅샷 필드 축소: `department_name`/`major_name`/`category`/`credits` 컬럼 제거, `course_id` 있을 때 응답 시점에 `courses`(+`departments`+`majors`) join으로 채우는 방식으로 변경
  - 실제 계정 데이터로 확인해보니 동명 과목(예: "데이터베이스"가 5개 학과에 개설)이 흔해서, 이름만으로 매칭하면 `course_id`가 자주 비거나 모호(ambiguous)함 — 이 경우 스냅샷이었으면 애초에 못 채웠을 필드들이라 join 방식이 더 안전
  - `course_name`만 예외로 스냅샷 유지 (course_id 없어도 항상 표시해야 하는 값)
  - `app/domains/planning/history.py`도 같이 단순화

## 2026-07-08 (d0won) - 2

- 성장 로드맵 작성/수정 API 추가 (`app/api/roadmaps.py`, `app/api/courses.py`)
  - "AI 자동 생성 버튼" 없이 로드맵은 항상 존재(없으면 자동 생성)하게 만들어서, 프론트는 "수정하기" 버튼 하나로만 진입 (`GET /me/roadmaps/current`)
  - `app/domains/planning/history.py`: 이미 크롤링된 이수내역(`StudentCourseRecord`)을 로드맵 항목으로 자동 변환 — 2학년 이상 학생이 처음 로드맵을 만들어도 1학년 때 들은 과목이 빈칸으로 안 보이게. 교육과정적용년도 기준으로 정규 학기만 학년(1~4) 계산, 멱등적 upsert
  - `GET /courses/search`: 과목 자동완성, 사용자 본인 학과/전공 과목 우선 정렬
  - 로드맵 항목은 반드시 실제 존재하는 `course_id`로만 생성/수정 가능 — 자유 텍스트 과목명 입력 경로 자체가 없어서 오타로 저장하는 게 구조적으로 불가능
  - `course_roadmap_items`에 `course_name`/`department_name`/`major_name`/`category`/`credits`(스냅샷), `status`, `is_confirmed` 필드, `course_roadmaps`에 `summary` 필드 추가
  - `course_plans`/`course_plan_items`(시간표 추천)는 나중에 별도 구현 예정이라 이번엔 건드리지 않음
  - TestClient로 전체 흐름(자동완성 → 로드맵 자동생성+이수내역 반영 → 항목 추가/수정 → 권한 체크 → 오타 방지) 검증 완료
## 2026-07-08 (d0won)

- 비교과 활동/자격증/어학성적 CRUD API 추가 (`app/api/profile.py`)
  - `GET/POST /me/activities`, `/me/certifications`, `/me/language-scores` + 각 `PATCH/DELETE /{id}`
  - 크롤링 대상(성적/전공)과 달리 사용자가 직접 입력/편집하는 데이터라 별도 라우터로 분리
  - `get_current_user`로 본인 데이터만 접근, 남의 데이터 요청 시 404
- DB 정리: `user_external_activities` + `user_competitions` → `user_activities`(비교과 활동)로 통합
  - "내 정보" 페이지 UI가 외부활동/공모전을 구분 없이 기관명/설명/링크만 있는 하나의 리스트로 보여줘서 나눌 이유가 없었음
  - UI에 있던 링크(`url`) 필드 신규 추가, 기존 데이터는 마이그레이션에서 이관
- TestClient로 로그인 → 생성 → 조회 → 수정 → 삭제 전체 흐름 + 인증 없음(401)/존재하지 않는 리소스(404) 케이스 검증 완료

## 2026-07-08 (blackest21)

- **Supabase에 학교 계층 + 2026 교육과정 적재 완료**: schools 1 / colleges 16 / departments 109 /
  majors 36 / courses 6,402 (전공계열 6,345 + 공통 교양 57). 소스는 전부 AIS(수강신청 시스템)
  현행 편제 — 표기·배치를 AIS 기준으로 통일했고, 팀 확인으로 특수 케이스(자율전공형·핀테크·
  지능형헬스·EES·스마트시티·약학부 385세대·치의학과 추가·한의학과 제외)를 확정.
- 시드 파일 2개(`backend/seeds/school_hierarchy_mapping.csv`, `ais_courses_2026.csv`)와
  멱등 적재 스크립트 2개(`scripts/seed_school_hierarchy.py`, `scripts/import_courses_from_ais.py`) 추가.
- 이상 데이터·전원 숙지 컨벤션(학과 조회 시 `major_id IS NULL` 필수 등)·추후 검토 목록은
  이 changelog의 최신 DB seed 항목에 통합 — **꼭 한번 읽어주세요.**
- 주의: 원본 데이터 특이사항 다수 발견 — 행정학과 PA2700143은 AIS부터 과목명 공란,
  조선·해양공학과는 AIS 동명 코드 2개(342100이 진짜), 국악학과/음악학과 동명 전공 함정 등.
  상세는 이 changelog의 최신 DB seed 항목.

## 2026-07-07 (d0won)

- `schools → colleges → departments → majors` 4단 FK 계층 신설 (`app/domains/academics/models.py`, `hierarchy.py`)
  - `courses`/`graduation_requirements`/`users`/`user_academic_programs`에 자유 텍스트로 흩어져 있던 school/college/department/major 컬럼을 `department_id`/`major_id` FK로 교체
  - `departments` 시드 데이터(수강편람 크롤링 기반)는 폐기 — 대신 `hierarchy.py`의 get-or-create 헬퍼가 크롤링/회원가입 시점에 이름이 들어올 때마다 없으면 자동 생성. 회원가입 학과 검증(`_validate_department_names`)도 같이 제거됨
  - 이유: 팀 공유 DB(Supabase)가 여러 브랜치 마이그레이션이 뒤섞여 어지러운 상태였음 — 전체 스키마를 합의된 ERD로 리셋하면서 같이 정리
- 포털 자동 로그인/동기화 API 추가 (`POST /me/portal-sync`, `PATCH /me/advisor-consulted`, `app/api/portal_sync.py`)
  - 학번/비밀번호를 받아 서버가 직접 One-Stop에 로그인, 학적부/성적/졸업예정정보를 크롤링해 DB에 매핑
  - 졸업예정정보 테이블 0(학적신청 정보)에서 복수전공/부전공 신청 여부까지 자동으로 `UserAcademicProgram`에 반영
- 성적 크롤링 정규화/버그 수정 (`pnu_normalizer.py`)
  - 이수구분 정규화: `"전공기초(학부)"` → `"전공기초"`, `"기초교양"` → `"교양선택"`(동의어), `"교직이수"` → `"교직과목"`(실제 표기 오타 수정)
  - 재수강 가능(C+ 이하) 여부 자동 판정해 `is_retake`에 반영
  - 수강편람(`courses`)과 과목명 매칭해 `course_id`/`match_status` 채움 (동명 과목 여러 개면 `ambiguous`로 남기고 오매칭 방지)
  - **버그**: "전적학교성적"(입학 전 인정 학점) 행이 과목명과 이수구분명이 같다는 이유로 소계 행으로 오판되어 걸러지던 문제 발견·수정 (실 계정 테스트 시 10건 → 정확한 14건 저장으로 확인)
- 추천활동(비교과 크롤링+임베딩+추천) 기능 제거 — 나중에 재설계해서 다시 구현할 예정
  - `activities`/`user_activity_recommendations`/`extracurricular_programs` 테이블, `app/api/activities.py`,
    `app/ai/recommendations/extracurricular_recommender.py`, `app/ai/embeddings/activity_embeddings.py`,
    `app/ai/evaluation/recommendation_eval.py`, `app/ingestion/normalizers/{activity_normalizer,dedup_activities}.py` 삭제
  - `notice_board_crawler.py`/`notice_board_sources.py`(순수 크롤링 코드), `openai_client.py`(범용 임베딩 유틸)는 재구현 시 재사용 위해 남겨둠
  - `app/core/scheduler.py`는 빈 스케줄러로 정리 (잡 없음)
- ERD 합의 후 `courses`/`graduation_requirements`/`user_academic_programs` 등 도메인 모델 전면 재구성, `planning`(수강계획/로드맵)·`content`(학사정보 안내글) 도메인 신설 ([#44](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/44), [#45](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/45))
- 실 계정으로 전체 흐름(로그인 → 크롤링 → 계층 자동생성 → 저장) 검증 완료: 부산대학교 → 정보의생명공학대학 → 의생명융합공학부 → 데이터사이언스전공까지 정확히 연결됨

## 2026-07-02 (d0won) - 12

- 프론트엔드 연동 가이드 문서 추가 (`docs/frontend-api-guide.md`) — 지금 동작하는 API(회원가입/로그인/내정보/추천)만 요청·응답·에러 예시로 정리. 팀 검토 전이라 PR 머지는 보류 중
- 문서 작성 중 버그 발견 및 수정: `GET /activities/recommendations/{user_id}`에 존재하지 않는 user_id를 넣으면 404가 아니라 처리 안 된 500이 나던 문제 — 유저 존재 여부를 먼저 확인하도록 수정

## 2026-07-02 (d0won) - 11

- `Course.department_id`/`RequirementSet.department_id`를 `departments` 테이블 FK로 추가
  - 자유 텍스트 department 컬럼은 표시용으로 유지, 검증/조인은 FK 기준
  - 부전공/복수전공 요건은 별도 테이블 없이 `RequirementSet.program_type`("minor"/"dual")으로 표현
  - FK 연결만 하고 실제 졸업요건/과목 데이터는 채우지 않음 — 정식 학사요람 출처 없이 요건 내용(학점/필수과목)을 채우면 졸업 판단을 오도할 위험이 있어 보류

## 2026-07-02 (d0won) - 10

- 회원가입 시 학과/전공 정식 명칭 검증 (`departments` 테이블)
  - `department`, `academic_programs[].major`가 DB에 없는 값이면 400으로 회원가입 거부
  - `departments` 시드 데이터(163개)는 onestop 수강편람 크롤러로 2026-1학기 개설 과목의 개설 학과명을 모아 연구소/센터 등 비학사 조직 제외해 생성 (`backend/seeds/pnu_departments.json`, `scripts/seed_departments.py`)
  - 알려진 한계: 수강편람은 과목 개설 단위(대개 세부 전공)만 노출해서 상위 학부명(정보컴퓨터공학부, 전기전자공학부 등)이 누락되는 경우가 있었음 — 발견된 것만 수동 보강, 전체 16개 단과대학 전수 대조는 안 함

## 2026-07-02 (d0won) - 9

- 회원가입에 복수전공/부전공 입력 추가 (`SignupRequest.academic_programs`)
  - User 테이블에 컬럼 추가 대신 기존 `UserAcademicProgram` 테이블(One-Stop 크롤러용으로 이미 있던)을 재사용, 유저당 여러 행으로 저장
  - program_type은 primary/dual/minor/interdisciplinary만 허용
  - 추천 로직이 이미 유저의 모든 전공을 프로필에 반영하고 있어서 별도 연동 없이 바로 추천에 반영됨
  - `GET /auth/me` 응답에 academic_programs 목록 포함

## 2026-07-02 (d0won) - 8

- 이메일/비밀번호 로그인·회원가입 구현 (`app/api/auth.py`)
  - `POST /auth/signup`, `POST /auth/login`, `GET /auth/me`, 재사용 가능한 `get_current_user` 의존성
  - JWT(`python-jose`) 발급/검증, 만료 7일
  - 비밀번호 해싱은 `passlib[bcrypt]` 대신 `bcrypt` 직접 사용 — passlib이 최신 bcrypt(4.1+)와 호환이 깨져있어서 교체 (`requirements.txt` 반영)
  - `User` 모델에 이미 email/password_hash가 있어서 마이그레이션 불필요
  - 다른 기능 API(추천 등)는 아직 `user_id` 파라미터 방식 그대로, `get_current_user` 전환은 별도 작업

## 2026-07-02 (d0won) - 7

- 추천 기준 재조정: 신청기간 만료 필터 강화 + 최신성 가중치 강화
  - 마감일이 파싱된 공지는 11%뿐이라 나머지 89%는 마감이 지나도 계속 추천되던 문제 발견
  - 마감일 없는 공지는 게시일 45일 경과 시 만료로 간주해 제외 (현재 DB 154건 해당)
  - recency_weight를 선형 감쇠(90일 0.5)에서 지수 감쇠(반감기 30일, 최소 0.1)로 변경 — 최신 공지가 순위에 더 확실히 반영되도록
  - 평가 수치는 소폭 하락(P@10 0.583→0.567)했으나, judge가 관련성만 보고 최신성은 안 보기 때문 — 최신성 강화는 의도한 요구사항이라 트레이드오프로 받아들임

## 2026-07-02 (d0won) - 6

- 시설 운영/행정성 공지 제외 필터 추가 (`_is_excluded`, `activity_normalizer.py`)
  - 도서관 개관시간 변경, 학자금대출 안내 등 "활동"이 아닌 공지가 섞여있는 걸 발견해 크롤링 단계에서 제외
  - 부수적으로 카테고리 분류 버그도 수정: "대출" 키워드가 너무 넓어서 "학자금대출"까지 "도서관" 카테고리로 잘못 분류되고 있었음 → "도서 대출/반납"으로 한정
  - 기존 DB에서 11건 정리

## 2026-07-02 (d0won) - 5

- 사용자 프로필 확장(query expansion) + 블렌딩 임베딩
  - 프로필 원문만 임베딩하면 유사도가 진로 분야보다 "채용/모집 형식"에 끌리는 문제 대응
  - gpt-4o-mini로 프로필을 분야 키워드 15~20개로 확장 후 임베딩 (프로세스 내 캐시)
  - 확장 임베딩만 쓰면 코퍼스에 해당 분야 공지가 없는 경우(화학) 순위가 노이즈化 → 원본+확장 벡터 평균(블렌딩)으로 해결
  - 평가: mean P@10 0.55 → 0.583, mean nDCG@10 0.713 → 0.733 (IT 계열 P@10 0.9 도달)

## 2026-07-02 (d0won) - 4

- 출처 간(cross-source) 중복 공지 정리
  - pusan_main이 전문 게시판(job, pnucounsel) 공지를 재게시해 추천 top-10에 같은 공지가 두 번 노출되던 문제
  - dedup 그룹핑 키를 (source, title) → title로 확장, 유지 우선순위에 "임베딩 보유" 추가(매일 밤 재임베딩 순환 방지)
  - 평가 수치: mean P@10 0.533 → 0.55, mean nDCG@10 0.711 → 0.713

## 2026-07-02 (d0won) - 3

- 추천 정확도 오프라인 평가 도입 (`app/ai/evaluation/recommendation_eval.py`)
  - 가상 페르소나 6명 × LLM-as-judge(gpt-4o-mini) 채점 → Precision@10 / nDCG@10
  - 기준선: mean P@10 = 0.533, mean nDCG@10 = 0.711 (활동 458건)
  - 발견: 출처 간 동일 공지 중복 노출, 비IT 진로에서 무관한 취업 공지 혼입

## 2026-07-02 (d0won) - 2

- docs 구조 개편: 날짜별 작업 기록 → 단일 `CHANGELOG.md` + `docs/features/` 기능별 문서
  - `docs/features/`를 기술 모듈(크롤러/추천엔진) 대신 제품 기능 4가지로 재편: 비교과 활동 추천, 내 정보 페이지(졸업요건 확인), core(로그인/회원가입, 미구현), 성장 로드맵(미구현)
  - `backend-db-infra-architecture.md` → `docs/architecture.md`로 이름 정리
- 원본에서 내려간 공지 자동 정리 (`remove_stale_activities`)
  - 기존엔 upsert만 해서 원본에서 삭제된 공지가 DB에 계속 남는 문제 발견
  - 전체 삭제 후 재삽입은 매일 전체 재임베딩 비용 + 추천 캐시(FK) 소실 문제로 배제
  - 출처별로 이번 크롤에서 안 보인 URL만 90일 lookback 안에서 부분 삭제하도록 구현

## 2026-07-02 (d0won)

- 비교과 활동 임베딩 + 추천 파이프라인 구현 ([#21](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/21))
  - OpenAI `text-embedding-3-small`로 Activity/사용자 프로필 임베딩
  - 코사인 유사도 × career_goal 가중치(1.2배) × 최신성 가중치(90일 선형 감쇠)로 추천 점수 계산
  - `GET /activities/recommendations/{user_id}` API 추가
  - 자정 크롤 → 임베딩 생성 → 중복 정리 → 추천 재계산까지 스케줄러에 연결
- 크롤러 중복 공지 자동 정리 추가
  - 제목 80% 유사도만으로는 회차별/재모집 공고(예: 다른 은행 채용설명회)까지 지워질 위험 발견
  - 같은 출처 + 제목 완전 일치 + 게시일 3일 이내인 경우만 중복으로 판단하도록 조건 강화
- `UserActivityRecommendation`에 FK(`ondelete=CASCADE`) 추가 — 유저/활동 삭제 시 추천 레코드가 고아로 남는 문제 해결
- job 게시판 빈 제목 공지 크롤링 버그 조사 → 크롤러 버그가 아니라 원본 게시글이 텍스트 없이 이미지 배너만 있는 공지였음, 크롤링 단계에서 제외 처리
- Supabase 팀 공유 DB로 전환, `alembic upgrade head`로 스키마 적용

## 2026-07-01 (d0won)

- 비교과 활동 공지사항 크롤러 구현 ([#19](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/19))
  - 7개 공개 게시판(swedu/uitc/pnucounsel/ctl/pusan_main/lib/job) 4개 엔진 타입으로 크롤링, 90일 lookback 기준 878건 수집 확인
  - `Activity`/`UserActivityRecommendation` 모델, 카테고리·마감일 자동 파싱 normalizer
  - APScheduler로 매일 00:00 KST 자동 크롤
  - `my.pusan.ac.kr` 개인화 페이지는 로그인 필수라 포기하고 로그인 없이 접근 가능한 공개 게시판으로 방향 전환
  - `lib.pusan.ac.kr`은 Angular SPA라 정적 크롤링 불가 → Playwright로 네트워크 캡처해 내부 JSON API(Pyxis) 발견 후 직접 호출

## 2026-06-30 (d0won)

- FastAPI 프로젝트 골격 구축 ([#11](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/11))
- 부산대 One-Stop 포털 크롤러 구현 ([#12](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/12)) — 학적부/성적/졸업요건 추출
- 크롤러 raw 데이터 → DB 모델 매핑 ([#13](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/13))
- 백엔드 폴더 구조를 도메인 기반(`domains`/`ingestion`/`ai`/`api`/`core`)으로 정리 ([#14](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/14))
