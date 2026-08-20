# 전적대 과목 대체 등록 (편입생)

편입생이 "전적대에서 들은 이 과목이 PNU의 어느 과목을 대체했는지"를 직접 등록하는 기능.
등록하면 시간표·로드맵 추천에서 그 PNU 과목이 빠진다.

## 왜 학생이 직접 입력하는가

편입 학점 인정은 **규정으로 정해져 있지 않다.** 학과가 편입생 개개인에게 "이 과목은 인정,
저건 불인정"을 통보하는 방식이라 **학생 본인만 안다.**

데이터에도 근거가 없다. 전적대 과목은 졸업사정용성적표(menuCD 000000000000096)에서
`*I0600368 컴퓨터프로그래밍 Ⅰ` 처럼 `*I`로 시작하는 별도 코드로 들어오고 PNU 교과목번호와
연결되지 않는다. (실제로는 크롤러가 `raw_course_code`를 채우지 않아 DB에는 코드조차 없다 —
식별 신호는 성적표 학기 칸이 `입학전성적`이라는 것뿐이다.)

그래서 **자동 매핑·유사도 추천을 구현하지 않는다.** `데이터구조`와 `자료구조`가 아무리
같아 보여도 학교가 실제로 그렇게 인정했는지는 알 수 없고, 틀리면 학생이 졸업요건을 잘못
믿게 된다. 학생이 화면에서 고른 값만 저장한다.

## 무엇이 바뀌고 무엇이 안 바뀌는가

| | 대체 등록의 효과 |
|---|---|
| 이수학점 합계 | **안 바뀐다.** 전적대에서 인정받은 학점은 그 이수기록 행에 그대로 있고, 졸업요건 엔진(`graduation_progress`)은 이수구분별 합계만 대조한다. |
| 졸업요건 판정 숫자 | **안 바뀐다.** 지금 엔진은 과목 단위 매칭 자체가 없다(CLAUDE.md "알려진 한계"). 이 기능은 그 한계를 고치지 않는다. |
| 시간표 추천 | 대체된 PNU 과목이 "이미 이수함"에 들어가 후보에서 빠진다. |
| 로드맵 추천 | 위와 동일. "이번 학기 놓치면 위험한 전공필수" 경고에서도 빠지고, 로드맵에 다시 담으려 하면 막힌다. |

## 스키마

`student_course_records.substitutes_course_id` (nullable FK → `courses.id`,
마이그레이션 `70d591f9bd02`).

전적대 과목 행이 "이건 PNU ○○를 대체했다"를 가리킨다. 학점 컬럼은 손대지 않는다.

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/me/course-records` | 응답에 `is_transfer_credit` / `substitutes_course_id` / `substitutes_course_name` 포함 |
| `PATCH` | `/me/course-records/{record_id}/substitution` | `{"course_id": 123}` 지정, `{"course_id": null}` 해제. 멱등 |
| `GET` | `/courses/search?q=` | 대체 대상 PNU 과목 검색 — 기존 엔드포인트 재사용 |

`PATCH`의 검증:
- 남의 이수기록이면 404 (존재 여부를 알려주지 않는다)
- `입학전성적`/`편입인정` 행이 아니면 422 — PNU에서 직접 들은 과목엔 걸 수 없다
- 없는 `course_id`면 404

`PUT /me/course-records`(내 정보 편집 저장)는 이 컬럼을 건드리지 않는다. 단, 그 화면에서
행을 삭제하면 대체 관계도 행과 함께 사라진다.

## 화면

내 정보(`/info`) → "학기별 성적" → **입학 전 인정 학점** 그룹. 각 전적대 과목 행의 과목명
칸에 "어떤 과목을 대체했나요?" 버튼이 붙고, 누르면 PNU 과목 검색창이 열린다. 이미 지정돼
있으면 `PNU 자료구조 대체`로 표시되고 변경/해제할 수 있다 — 학과 통보를 나중에 받거나
잘못 골랐을 때 언제든 고칠 수 있어야 하기 때문이다.

성적 편집(연필 아이콘) 모드에서는 감춘다. 대체 등록은 즉시 저장이고 성적 편집은 초안 방식
이라, 한 화면에 섞으면 무엇이 저장됐는지 알 수 없다.

## 코드 위치

- 도메인 헬퍼: `backend/app/domains/academics/course_substitution.py`
- API: `backend/app/api/portal_sync.py` (`set_course_substitution`, `_course_record_responses`)
- 추천 반영(시간표): `backend/app/domains/planning/timetable.py::_completed_course_norms`
  — 시간표 챗의 모든 "이미 이수" 검사가 이 한 지점을 지난다
- 추천 반영(로드맵): `backend/app/domains/planning/roadmap_chat.py`
  — `_compute_critical_missing_required` / `_compute_missing_required_available` /
  `_compute_prereq_blocked`의 `completed_norms`, 그리고 `propose_change`의 중복 create 가드
- 회귀 테스트: `backend/tests/test_course_substitution.py`
- 프론트: `frontend/src/pages/InfoPage.tsx`, `frontend/src/api/studentInfo.ts`
