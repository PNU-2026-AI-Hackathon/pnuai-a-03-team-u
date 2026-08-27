# 로드맵 "SW융합 가능" 버튼 — 기능 스펙 (독립 세션용)

작성 2026-08-27. **이 기능은 별도 세션에서 진행한다.** 지금 진행 중인 융합전공
이수요건 데이터 수집/시딩 작업(`raw_data/manual_staging/06_interdisciplinary_majors/`)과
분리해서, 그 데이터가 DB에 반영된 뒤 착수한다.

## 사용자 요청 (원문 의도)

1. 교차 융합 가능한 학과들을 **로드맵 추천에 포함** — 성장 로드맵을 짤 때 "이 학과
   학생은 이런 융합전공/연계전공/SW융합트랙도 이수 가능하다"를 빠뜨리지 않고 제안.
2. 로드맵 화면(예: 컴퓨터공학전공) **오른편에 "SW융합 가능" 버튼** 신설.
3. 그 버튼을 누르면 해당 학과에서 갈 수 있는 **융합전공 / 연계전공 / SW융합트랙**을
   각각 **클릭 가능한 버튼**으로 나열.
4. 각 전공/연계/트랙 버튼에 **어느 학과들 수업을 들어야 하는지(참여학과)** 를 간단히 표시.

## 선행 조건 (blocker)

`graduation_requirements` / `program_courses`에 융합전공 데이터가 있어야 한다. 현재:
- ✅ SW연계전공 5개(gr#281~285)·SW융합트랙 14개(gr#268~280·287)는 이미 시딩됨
  (`seed_sw_convergence_programs.py`). 참여학과 정보는 `TRACK_COURSES`/`LINKED_*`에.
- ⏳ 나머지 융합전공(반도체·DX·그린바이오·미래자동차·EES·이차전지·지식재산 등)은
  `seed_interdisciplinary_majors_2026_08.py` + `import_courses_from_ais`로 반영 예정
  (이번 세션 5단계, `raw_data/manual_staging/06_interdisciplinary_majors/README.md` 참고).

이 스펙 착수 전에 위 시딩이 Supabase에 반영됐는지 확인할 것.

## 데이터: 학과 → 융합/연계/트랙 → 참여학과

이미 수집돼 있는 소스:
- **SW융합트랙 14개**: 각 host 학과 1곳(사회학과→소셜데이터사이언스 등). majors.name
  접미사 "(SW융합트랙)", `seed_sw_convergence_programs.py` TRACK_COURSES에 학과전공+SW공통.
- **SW연계전공 5개**: 빅데이터(산업공학과)·산업수학SW(수학과)·에너지IoT/임베디드SW
  (전기전자공학부)·산업AI(산업공학과). 참여학과는 `LINKED_HOST_DEPARTMENTS`.
- **반도체융합전공**: 주관 반도체공학전공 + 참여학과 다수(전자·전기·재료·고분자·
  유기소재·기계·화공생명·첨단융합학부·컴공·인공지능·물리) —
  `raw_data/.../06_interdisciplinary_majors/dept_151_반도체융합전공.md` "전공 구성" 절.
- **미래자동차 융합전공**: 기계공학부(AC 코드) 기반. `dept_140_미래자동차융합전공.md`.
- **핀테크융합전공**: 경영학과 + 컴퓨터공학전공 교차인정 (`seed_fintech_cross_listed_courses.py`).
- 나머지(EES/이차전지/지식재산/DX/그린바이오): 대부분 자체 개설 — 참여학과 개념 약함.

→ 백엔드에서 "참여학과"를 도출하는 방법: 해당 프로그램의 `program_courses`에 걸린
`course_id`들의 `courses.department_id`를 distinct 집계하면 "이 프로그램을 이수하려면
어느 학과 수업을 듣게 되는지"가 자연스럽게 나온다. 별도 참여학과 테이블 불필요.

## 백엔드 설계 스케치

`GET /me/roadmap/fusion-options` (또는 `/academics/fusion-options?department_id=&major_id=`)

- 입력: 현재 로그인 사용자의 주전공 department_id/major_id (또는 쿼리 파라미터)
- 출력: 이수 가능한 프로그램 목록. 각 항목:
  ```json
  {
    "program_type": "interdisciplinary" | "linked" | "track" | "minor" | "dual",
    "label": "빅데이터 연계전공",
    "department_id": 40, "major_id": 77,
    "required_total_credits": 48,
    "participating_departments": ["산업공학과", "통계학과", "정보컴퓨터공학부"],
    "summary": "산업공학·통계·컴퓨터공학 과목을 48학점 이수"
  }
  ```
- "이수 가능" 판정: 지금은 전 학과 공통으로 열려 있는 것(SW융합트랙은 host 학과
  학생만? 연계전공은 별도 지원)이라 규칙이 프로그램 유형별로 다르다 —
  `docs/architecture.md` 판정 경계 지키고, 규칙 기반으로만. 애매하면 "지원 자격은
  학과 문의" 문구로 처리하고 전부 노출하는 쪽이 안전.
- `graduation_progress.py`는 건드리지 않는다(판정 엔진). 이건 조회 전용 신규 라우터.

## 프론트 설계 스케치

- 로드맵 화면(`frontend/.../Roadmap*` 컴포넌트) 우측 사이드/헤더에 "SW융합 가능" 버튼.
  주전공이 융합 대상일 때만 노출(응답이 비어있으면 숨김).
- 클릭 → 패널/드로어. 프로그램별 버튼 목록. 각 버튼 안에 label + 참여학과 칩 + 총학점.
- 프로그램 버튼 클릭 → (1단계) 상세(과목 구분별 목록, `program_courses` 조회) 또는
  (간단) 그 프로그램 과목을 로드맵 후보 검색에 넣기.
- 타입체크: `npm run build` (memory: `tsc --noEmit -p tsconfig.json`은 0개 검사).

## 로드맵 추천 반영 (요청 1)

`app/domains/planning/roadmap_chat.py` 프롬프트/컨텍스트에 "주전공이 융합 대상이면
이수 가능한 융합전공/연계/트랙을 후보로 언급" 추가. LLM 행동 변경이므로 골든 eval
동일 시나리오 3회 이상 재검증(memory: 1회 통과로 '됐다' 금지). 범위 분리해서 별 PR로.

## 패널에서 "저장"(이수 계획 등록) — PR #4

**결정 (2026-08-27):** 패널 카드를 클릭하면 `confirm("… 저장하시겠습니까?")` →
그 프로그램을 학생의 이수 계획으로 등록한다. 별도 flag 컬럼을 만들지 않는다 —
**`user_academic_programs` 행 자체가 그 플래그**이고, 졸업요건 엔진
(`graduation_progress.compute_graduation_progress`)과 로드맵 챗 컨텍스트
(`_build_student_context_block`)가 이미 그 테이블을 훑는다. `User`에 boolean을
새로 만들면 두 엔진에 읽는 코드를 새로 넣어야 해서 오히려 배선이 는다.

- **백엔드**: `POST /me/fusion-programs/enroll {program_id}` +
  `DELETE /me/fusion-programs/{user_academic_program_id}`. `enroll_track`/`cancel_track`
  (`app/api/tracks.py`) 패턴 그대로.
  - `program_id`(= `graduation_requirements.id`)의 `(department_id, major_id, program_type)`으로
    `UserAcademicProgram(user_id, …, program_type=<minor|dual>, status="active")` upsert.
  - 취소는 `status="cancelled"` soft delete.
  - 패널이 minor/dual 카드를 이미 분리 표시하므로 "누른 카드 = 부전공/복수전공" 자동 결정.
- **자동으로 되는 것 (코드 변경 0)**:
  - 졸업요건: `compute_graduation_progress`가 새 UAP 행 열거 → 그 GR(#283 시딩분) 평가.
    `GET /me/graduation` 카드에 등장.
  - 로드맵 챗: `[학적 프로그램]` 컨텍스트 블록에 "반도체융합전공 복수전공 — 요구 48학점"
    자동 등장 ("부·복수전공 있으면 요구 학점도 안내" 지시 이미 있음).
  - 회원가입 다중전공도 정식 신청 전에 UAP 행을 만들어 요건에 반영하므로 일관됨.
- **프론트**: 카드 클릭 → confirm → `enrollFusionProgram` → 목록 새로고침.
  이미 등록한 카드는 "이수 중" 배지 + 클릭 시 취소 확인.
- **LLM이 *먼저* 제안**하게 하는 건 별개(아래 로드맵 챗 PR) — 골든 eval 3회 재검증.

## 착수 순서

1. 융합전공 시딩이 Supabase에 반영됐는지 확인
2. 백엔드 조회 라우터 `GET /me/fusion-programs/available` + 테스트 — **PR #281 (완료)**
3. 프론트 버튼/패널 + AI융합교육원 연락처 — **PR #282 (완료)**
4. 시드 스크립트 + AIS CSV — **PR #283 (완료)**
5. 패널 "저장" → `user_academic_programs` enroll/cancel + 클릭→confirm UI — **PR #4 (예정)**
6. 로드맵 챗 프롬프트 반영 (별 PR, 골든 eval 3회 재검증)
