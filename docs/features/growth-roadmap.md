# 성장 로드맵

사용자가 1~4학년 전체 학사 계획을 직접 짜고 수정하는 기능. "AI 자동 생성 버튼"은
따로 두지 않기로 했다 — 대신 로드맵은 항상 존재(없으면 자동 생성)하고, 사용자는
"수정하기" 버튼 하나로 항상 편집할 수 있다. AI 채팅으로 로드맵을 짜거나 고치는
기능은 이 CRUD 위에 나중에 얹을 예정 (아직 미구현).

## 스키마 (`app/domains/planning/models.py`)

```text
course_roadmaps
- id, user_id, title, start_year, target_graduation_year
- status (draft/active/archived)
- summary          # 로드맵 전체에 대한 AI/사용자의 요약 설명

course_roadmap_items
- id, roadmap_id, course_id (null 가능 — 자리표시 항목 대응)
- planned_grade, planned_year, planned_semester
- course_name, department_name, major_name, category, credits
  # course_id join 없이 바로 표시 가능하게 스냅샷으로 저장.
  # major_name은 "OO과"처럼 세부 전공이 없으면 null.
- status (planned/completed/dropped)
- is_confirmed     # source="ai" 제안을 사용자가 실제로 받아들였는지
- reason, source (manual/ai)
```

`course_plans`/`course_plan_items`(시간표 추천, F-03)와는 별개다 — 로드맵은
`course_id`만 들고 있는 "큰 그림"이고, 플랜은 `offering_id`(실제 분반)까지
확정하는 "이번 학기 실행 계획"이다. 시간표 추천은 아직 손대지 않았다.

## 이미 이수한 과목 자동 반영 (`app/domains/planning/history.py`)

2학년 이상인 학생이 로드맵을 처음 만들면 1학년 때 들은 과목이 하나도 안 보이는
문제가 있어서, `sync_completed_courses_to_roadmap()`이 One-Stop에서 크롤링된
`StudentCourseRecord`를 로드맵 항목(`status="completed"`)으로 변환해 채워준다.

- `UserAcademicProgram.curriculum_year`(입학년도) 기준으로 정규 학기(1학기/2학기)만
  `planned_grade`(1~4)를 계산한다. "입학전성적"(전적학교성적/편입 인정 학점),
  계절수업처럼 특정 학년에 안 떨어지는 기록은 `planned_grade`를 비워둔다
- (roadmap_id, course_name, planned_year, planned_semester) 기준으로 upsert —
  같은 로드맵에 여러 번 실행해도 중복 생성 안 됨(멱등)
- 실제 계정(3학년, 5학기차)으로 검증: 3학년 1학기 과목은 정확히 `planned_grade=3`으로
  계산됨, 전적학교성적/계절수업은 학년 없이 별도로 표시됨

## API

### 과목 검색/자동완성 (`app/api/courses.py`)

| 메서드/경로 | 설명 |
| --- | --- |
| `GET /courses/search?q=` | 과목명으로 검색. 사용자 본인 `department_id`/`major_id`와 일치하는 과목을 먼저 정렬해서 보여줌 |

로드맵 항목을 자유 텍스트로 입력받지 않고, 반드시 이 검색 결과에서 고른
`course_id`로만 저장하게 만들어서 오타/존재하지 않는 과목명을 원천 차단한다.

### 로드맵 (`app/api/roadmaps.py`)

| 메서드/경로 | 설명 |
| --- | --- |
| `GET /me/roadmaps/current` | 로드맵이 없으면 자동 생성(이수내역 자동 반영 포함) 후 반환, 있으면 가장 최근 것을 그대로 반환. 프론트는 이 엔드포인트 하나만 호출하고 "수정하기" 버튼만 두면 됨 |
| `GET /me/roadmaps` | 로드맵 목록 |
| `POST /me/roadmaps` | 로드맵 새로 생성(수동) |
| `GET /me/roadmaps/{id}` | 단건 조회(항목 포함) |
| `PATCH /me/roadmaps/{id}` | 제목/상태/요약 수정 |
| `DELETE /me/roadmaps/{id}` | 삭제 |
| `POST /me/roadmaps/{id}/items` | 항목 추가. `course_id` 필수 — 서버가 courses/departments/majors를 조회해 스냅샷을 채움, 존재하지 않는 course_id면 404 |
| `PATCH /me/roadmaps/{id}/items/{item_id}` | 항목 수정(과목 교체 포함) |
| `DELETE /me/roadmaps/{id}/items/{item_id}` | 항목 삭제 |

모든 엔드포인트가 `get_current_user`로 본인 로드맵만 접근 가능 — 남의 로드맵/항목
요청 시 404.

## 알려진 한계 / TODO

- AI가 로드맵을 짜거나 채팅으로 수정하는 기능 미구현 (지금은 순수 수동 CRUD만)
- `graduation_requirements`가 비어있어서, AI가 짤 때든 사용자가 직접 짤 때든
  "졸업까지 몇 학점 남았는지" 기준으로 안내할 방법이 없음
- 시간표 추천(`course_plans`/`course_plan_items`, F-03)과의 연결 로직 미구현 —
  로드맵 항목을 실제 개설 분반(`course_offerings`)으로 구체화하는 흐름 필요
