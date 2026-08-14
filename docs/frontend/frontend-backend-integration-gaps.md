# 프론트–백엔드 연결 감사 · 작업 계획

작성 2026-08-14 · 백엔드 담당

FastAPI 라우트 테이블(`app.main:app`에서 실제로 등록된 라우트를 순회)과 `frontend/src`의
모든 HTTP 호출부를 1:1로 대조한 결과다. 문서(`frontend-api-guide.md`)는 낡아서 근거로
쓰지 않았다.

- **백엔드**: 14개 라우터 69개 라우트 + `/health`
- **프론트**: HTTP 계층은 `frontend/src/api/client.ts`(axios) 하나뿐. 7개 파일 55개
  호출부 → 서로 다른 method+path 54개. `fetch`/`EventSource`/`WebSocket`/하드코딩
  호스트는 없다.

> ⚠️ FastAPI 최신 버전은 include된 라우터를 감싸므로 `app.routes`를 단순 순회하면 5개만
> 보인다. `_IncludedRouter.original_router.routes`까지 들어가야 전체가 나온다.

---

## 요약

| 분류 | 건수 | 상태 |
|------|------|------|
| 프론트만 호출(=404) | **0** | 문제 없음 |
| 백엔드만 존재(프론트 미호출) | 17 | 대부분 미구현 기능, 1건은 보안 이슈 |
| 스키마/사용 불일치 | 6 | **M1 수정 완료**, M2·M3 미해결 |

---

## 1. 프론트만 호출하는 경로 — **없음**

54개 호출이 전부 등록된 라우트에 대응한다. 템플릿 리터럴로 만든 경로
(`/me/roadmaps/${id}/agent/sessions/${sid}` 등)까지 전부 확인했다. 죽은 호출은 없다.

## 2. 불일치

### M1 — 온보딩 미리보기가 빈 카드로 뜨던 문제 ✅ **수정 완료**

`student_record`는 백엔드가 **크롤러가 읽은 그대로** 넘긴다(`portal_sync.py:231`). 키는
One-Stop 학적부 화면의 한글 라벨(`성명`·`학번`·`소속학과`·`학년`·`학적상태`)이다.
근거: `pnu_normalizer.py:79-102`가 그 키로 읽는다.

그런데 `portal.ts`의 `summarizePortalSync`가 `record.name`·`record.student_id`·
`record.department` 같은 **영문 키**를 읽고 있었다 → 항상 `null`.

**사용자에게 보이던 증상**: 회원가입 STEP 2 "불러온 정보 미리보기"에서 이름·학번 줄과
학적상태 줄이 빈 문자열이라 렌더에서 걸러지고, `N학점 · M과목` 한 줄만 남았다.
**포털 비밀번호를 막 넘긴 직후 화면**이라 "동기화가 안 됐다"로 읽힌다.

**조치**: `summarizePortalSync`가 한글 키를 읽도록 수정(목 데이터의 `이름`도 함께 허용).
`소속학과` 원문은 "대학 학부 전공"이 이미 한 문자열에 들어 있어, 기존처럼 `major`를
덧붙이면 전공이 두 번 나오므로 원문이 있으면 그것만 쓴다.

> **왜 개발 중에 안 잡혔나**: 목 데이터(`studentInfo.ts:94-99`)가 `이름/학번/학부/전공`을
> 쓰는데 실제 크롤러는 `성명/학번/소속학과`를 낸다. 목이 실제와 다른 모양이라 목 경로에서는
> 정상으로 보였다. **목을 실제 키로 맞추는 게 후속 작업(P1)에 포함돼 있다.**

### M2 — my.pusan 동기화 실패가 사용자에게 안 보인다 ❌ 미해결

`PortalSyncResponse`는 `my_pusan_sso_ok`와 비교과/자격증/어학 카운터 6개를 돌려주는데
(`portal_sync.py:89-95`), **프론트 타입에 아예 없고 아무도 안 읽는다**(직접 grep 확인).

백엔드는 my.pusan 크롤 실패를 의도적으로 삼키고 200을 돌려준다
(`portal_sync.py:146-153`, `212-216`). 그래서 **"동기화 성공"이라고 안내하면서 비교과·
자격증·어학은 하나도 안 들어온 상태**가 된다.

### M3 — InfoPage가 sync 응답을 통째로 버린다 ❌ 미해결

`InfoPage.tsx:356-363`은 목 모드가 아니면 `result`를 버리고 `refreshUser()` +
`window.location.reload()`만 한다. 결과:
- M2를 여기서도 못 알린다
- `studentRecord`는 목 모드에서 sessionStorage로만 채워져서, `studentRecord["전공"]`
  (`InfoPage.tsx:328-330`)는 **운영에서 영구 죽은 분기**다
- 상태 갱신으로 될 일을 전체 페이지 리로드로 처리한다

### M4 — 실패 메시지 문구가 엉뚱함 (경미)

`InfoPage.tsx:107-114` `getErrorMessage`의 폴백이 "교과 활동을 불러오지 못했습니다"인데
포털 동기화 실패(366행)에도 쓰인다. 백엔드가 401/502/429에 `detail`을 주므로 잘 안
뜨지만, 네트워크 끊김에는 무관한 문구가 나온다. (`OnboardingPage`는 올바르게
`getApiErrorMessage`를 쓴다.)

### M5 — 타입 좁힘 (정상, **고치지 말 것**)

프론트 타입이 백엔드 응답의 부분집합인 곳들. TS상 유효하고 런타임 영향 없다:
`TimetableApplyResult.applied`, agent reset 응답의 `deleted_sessions`,
`GraduationProgram`의 `department_id`/`major_id`, `PortalSyncResult.courses`.

### M6 — 목 데이터가 실제 모양과 다름

M1의 근본 원인. `studentInfo.ts:94-99`가 `이름/학번/학부/전공`을 쓴다.

## 3. 백엔드에만 있는 것 (프론트 미호출 17건)

**보안/비용** — `POST /rag/ingest` ✅ **리밋 적용 완료**: 전체 RAG 재구축 + OpenAI 임베딩
호출인데 인증만 통과하면 학생 누구나 부를 수 있었고 리밋이 없었다. 아무도 호출하지 않는
운영 작업이라 순수 공격면이었다. `RATE_LIMIT_RAG_INGEST="2/hour;5/day"` 적용.
검색 2건(`/rag/curriculum/search`, `/rag/graduation-requirements/search`)도 미호출이다.

**미구현 기능 (버그 아님, 제품 결정 필요)**
- 로드맵 다중 CRUD 5건 — 프론트는 `/me/roadmaps/current`만 쓴다. 로드맵 이름 변경·삭제·
  복수 보유가 불가능하다
- AI융합트랙 4건 전체 — UI 없음
- `DELETE /me/account` — **회원탈퇴가 구현돼 있는데 UI가 없다**(`frontend/src`에 "탈퇴"
  문자열 0건). 개인정보 계획의 약속인데 사용자가 도달할 수 없다 → 팀에 가장 먼저 제기할 것
- `DELETE /me/graduation/override` — 저장은 되는데 되돌리기 경로가 없다
- `GET /me/roadmaps/{id}/timetable/recommend`, `POST .../agent/reset` — 프론트 래퍼는
  있는데 아무 페이지도 import 안 함

**파라미터 단위로 죽은 것**: `GET /me/graduation?include_non_primary=true`. 프론트가 안
보내고, 소비처 3곳 모두 `program_type === "primary"`만 고른다 →
**부전공·복수전공 졸업요건 진행률은 계산되지만 화면에 절대 안 나온다.**

## 4. 포털 sync 판정: **전 구간 연결돼 있고 동작한다**

1. **수집** — 로그인 → 학적부/성적/졸업요건/졸업예정정보/상담상태/비교과 6종
   (`portal_sync.py:133-153`). 크롤러 반환 키와 노멀라이저 소비 키 일치 확인
2. **정규화·저장** — `map_student_record`/`map_grades`/`map_academic_program_registrations`
   + `_refine_liberal_area_categories`. 2026-08-13 균형교양 학점 소실 회귀를 막는
   `BALANCED_LIBERAL_AREAS` 가드가 `portal_sync.py:318-332`에 살아 있다. 커밋 1회
3. **API** — 인증 필수, `5/hour` 리밋, 비밀번호 `SecretStr`, 401/502 분리, 스택트레이스
   서버 보관
4. **트리거** — 온보딩·InfoPage 두 화면
5. **에러 처리** — `client.ts:25-30`이 `/me/portal-sync`를 전역 401→로그아웃
   인터셉터에서 **명시적으로 제외**한다. 포털 비밀번호를 틀려도 Plan-U에서 로그아웃되지
   않는다(올바른 동작). 429 한국어 메시지, 422 비밀번호 미노출 확인

**결함은 소비 쪽에만 있다** — M1(수정 완료)과 M2·M3(부분 실패가 안 보임).

---

## 5. 남은 작업 계획

| 우선순위 | 작업 | 파일 | 예상 |
|---|---|---|---|
| **P1** | 부분 실패 노출: `my_pusan_sso_ok`·카운터 6종을 프론트 타입에 추가하고, `false`면 "비교과·자격증·어학은 가져오지 못했습니다" 경고 렌더. 겸사겸사 `window.location.reload()`를 상태 갱신으로 교체 | `portal.ts`, `studentInfo.ts`, `InfoPage.tsx:356` | ~2h |
| **P1** | 목 데이터를 실제 키(`성명`/`소속학과`)로 교체. M1 같은 버그가 개발 중에 잡히게 | `studentInfo.ts:94-99` + `InfoPage.tsx:328-330` 목 분기 | ~1h |
| **P2** | 졸업요건 override 되돌리기 버튼 (`DELETE /me/graduation/override`). 지금은 잘못 저장하면 학과를 바꾸지 않는 한 갇힌다 | `InfoPage` 졸업요건 편집기 | ~1h |
| **P3** | 부전공·복수전공 진행률 노출 여부 결정. `include_non_primary=true`를 보내고 렌더하거나, 주전공 전용임을 명시. **부전공 이름만 띄우고 진행률이 없는 지금이 가장 나쁘다** (부전공은 필수과목이 핵심이라 더욱) | `studentInfo.ts:118` + 3개 화면 | ~3-4h |
| **P4** | 회원탈퇴 UI. 백엔드는 완성돼 있고 개인정보 약속인데 도달 불가 — **제품 결정 필요, 팀에 제기** | 신규 | 결정 후 |
| **P5** | 정리: 죽은 래퍼 2개(`recommendTimetable`, `resetRoadmapAgentSession`) 연결 또는 삭제, `getErrorMessage` 폴백 문구, `frontend-api-guide.md` 갱신 | 다수 | ~1h |

**계획에서 뺀 것**: 로드맵 다중 CRUD·AI융합트랙. 깨진 게 아니라 안 만든 기능이고
(`/me/roadmaps/current`가 자동 생성해서 단일 로드맵 흐름은 정상), UI 작업 전에 제품
결정이 먼저다.

**참고**: `ActivitiesPage.tsx`는 100% 하드코딩(`src/data/recommendedActivities.ts`)이고
20행에 이름 폴백 `"이도원"`이 박혀 있다. 양쪽 다 API가 없다.
