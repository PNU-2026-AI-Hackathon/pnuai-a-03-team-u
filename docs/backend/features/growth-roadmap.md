# 성장 로드맵

사용자가 1~4학년 전체 학사 계획을 직접 짜고 수정하는 기능. "AI 자동 생성 버튼"은
따로 두지 않기로 했다 — 대신 로드맵은 항상 존재(없으면 자동 생성)하고, 사용자는
"수정하기" 버튼 하나로 항상 편집할 수 있다. AI 채팅으로 로드맵을 짜거나 고치는
기능은 이 CRUD 위에 human-in-the-loop 방식으로 얹었다 — 아래 "AI 로드맵 상담" 절 참고.

## 스키마 (`app/domains/planning/models.py`)

```text
course_roadmaps
- id, user_id, title, start_year, target_graduation_year
- status (draft/active/archived)
- summary          # 로드맵 전체에 대한 AI/사용자의 요약 설명

course_roadmap_items
- id, roadmap_id, course_id (null 가능 — course_id가 없거나 모호(동명 과목이
  여러 학과에 걸쳐 있는 경우가 실제로 흔함)한 경우가 있어서)
- planned_grade, planned_year, planned_semester
- course_name, category, credits
  # "쓰는 시점"에 확정된 값을 스냅샷으로 저장한다. 과거 이력은
  # StudentCourseRecord(성적표 원본)에서, 신규/수정 항목은 선택한
  # course_id에서 그대로 복사한다.
- status (planned/completed/dropped)
- is_confirmed     # source="ai" 제안을 사용자가 실제로 받아들였는지
- reason, source (manual/ai)
```

`department_name`/`major_name`만 컬럼으로 저장하지 않고, API 응답을 만들 때
`course_id`가 있으면 그때그때 `courses`(+`departments`+`majors`)를 join해서 채운다.

`category`/`credits`는 원래 이것도 join 방식으로 뺐었는데, 실제 계정으로 검증하다가
문제를 발견해 다시 스냅샷으로 되돌렸다: 과거 이수내역은 동명 과목(예: "데이터베이스"가
5개 학과에 개설)이 흔해서 `course_id`가 자주 비거나(unmatched) 모호(ambiguous)한데,
이 경우 join으로는 학점 자체를 못 보여준다. 반면 학점/이수구분은 성적표 원본에
`course_id` 매칭 여부와 무관하게 이미 정확한 값으로 있어서, 매칭이 필요 없는
값들이다 — 그래서 스냅샷으로 남겨도 어긋날 일이 없다. `department_name`/`major_name`은
성적표 원본에 아예 없는 정보라(학과 소속은 매칭된 `course_id`를 통해서만 알 수 있음)
계속 join 방식을 쓴다.

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
- **언제 실행되는가**: 로드맵을 처음 만들 때(`GET /me/roadmaps/current`가 로드맵이
  없어서 새로 만드는 순간)와, `POST /me/portal-sync`(포털 크롤링) 완료 직후,
  두 시점에만 실행된다. `GET /me/roadmaps/current`는 로드맵이 이미 있으면 조회만
  하고 동기화는 하지 않는다 — 로드맵 페이지를 열 때마다 이 동기화가 다시 돌면
  체감 지연이 생기고, 애초에 새 이수내역이 생기는 시점은 "크롤링했을 때"뿐이라
  거기서만 하면 충분하다. 크롤링 시점엔 사용자의 로드맵을 전부(보통 1개) 갱신한다

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
| `POST /me/roadmaps/{id}/items` | 항목 추가. `course_id` 필수 — 서버가 courses에서 조회해 course_name/category/credits를 채움, 존재하지 않는 course_id면 404 |
| `PATCH /me/roadmaps/{id}/items/{item_id}` | 항목 수정(과목 교체 포함) |
| `DELETE /me/roadmaps/{id}/items/{item_id}` | 항목 삭제 |

모든 엔드포인트가 `get_current_user`로 본인 로드맵만 접근 가능 — 남의 로드맵/항목
요청 시 404.

## AI 로드맵 상담 (`app/domains/planning/roadmap_chat.py`, `app/api/roadmap_agent.py`)

OpenAI(`gpt-4o`) tool-calling으로 로드맵 변경을 "제안"받는 채팅 기능(원래
Anthropic Messages API로 설계했으나 `.env`에 `ANTHROPIC_API_KEY`가 없어 실제
테스트를 위해 OpenAI로 구현 — `ANTHROPIC_API_KEY`가 채워지면 다시 바꿔도 된다.
tool 스키마/`_ToolContext` 로직은 SDK 무관하게 재사용 가능, client 호출부만
다르다). **Agent는 `course_roadmap_items`를 절대 직접 쓰지 않는다** — 항상
`pending_roadmap_changes`에 제안만 쌓고, 사용자가 승인한 항목만 실제로
반영된다(human-in-the-loop). 최초 로드맵 생성이든 기존 항목 수정/삭제든 전부
같은 절차를 거친다.

LangGraph 같은 그래프 오케스트레이션은 쓰지 않는다 — tool 호출 루프 한 번 →
제안 저장 → (별도 API 호출로) 확인 대기 → 반영, 순서가 고정된 단순 파이프라인이라
그래프 엔진 없이 SDK의 tool loop만으로 충분하다.

### 실계정 E2E 테스트에서 발견한 신뢰성 문제와 수정 (2026-07-13)

첫 구현은 매 턴 `tool_choice="auto"`로 뒀는데, `gpt-4o`가 `get_graduation_progress`/
`get_roadmap_items`까지는 호출해놓고 `search_courses`/`propose_change` 없이
**그냥 일반 텍스트로 과목 목록을 나열하고 끝내버리는 경우**가 실계정 테스트에서
재현됐다. 이러면 답변엔 과목명이 있는데 `pending_changes`는 비어있어서, 사용자가
"네"라고 해도 반영할 게 아무것도 없는 상태가 된다.

고친 방법: 매 턴 `tool_choice="required"`를 강제하고, 사용자에게 보이는 답변도
`finish_response(message=...)`라는 별도 도구 호출로만 내보내게 만들었다 —
"일반 텍스트로 바로 답하기"라는 탈출구 자체를 없앤 것. 시스템 프롬프트에도
"finish_response에 과목명을 언급하려면 그 전에 반드시 그 과목을 propose_change로
제안했어야 한다"고 명시했다. 실계정으로 반복 테스트해서 매번 `propose_change`가
호출되고 `pending_changes`가 비어있지 않은 걸 확인했다.

### 스키마

```text
course_roadmap_chat_messages
- id, roadmap_id, role(user/assistant), content
  # 로드맵당 하나의 연속 대화로 취급. 클라이언트가 매번 히스토리를 다시 보내는
  # 대신 서버가 이 테이블에서 복원해 매 요청마다 LLM에 다시 넘긴다.

pending_roadmap_changes
- id, roadmap_id, item_id(update/delete 대상, null 가능)
- action (create/update/delete)
- course_id, planned_year, planned_semester, planned_grade  # create/update용
- before_snapshot (JSON)  # update/delete 전 값 — 대화창에 "뭐가 바뀌는지" 보여주기용
- reason
- status (pending/approved/rejected)
```

### Agent 도구

- `get_graduation_progress` — `GET /me/graduation`과 같은 로직(`graduation_progress.py`)
  으로 남은 이수구분별 학점을 조회
- `get_roadmap_items` — 현재 로드맵 항목 전체 조회(중복 추천 방지용)
- `search_courses` — RAG 담당자가 만든 `CurriculumRetriever`(`app/ai/rag/curriculum_retriever.py`)
  로 학생 학과·교육과정연도에 맞는 과목을 검색. course_id를 얻는 유일한 방법
- `propose_change` — 로드맵 변경 제안. `pending_roadmap_changes`에 1건을
  만들 뿐, `course_roadmap_items`는 건드리지 않는다
- `finish_response` — 사용자에게 답변을 전달하는 유일한 방법(위 "신뢰성 문제" 참고).
  일반 텍스트 응답은 무시되고, 이 도구를 통해 나온 `message`만 저장/반환된다

### API

| 메서드/경로 | 설명 |
| --- | --- |
| `POST /me/roadmaps/{id}/agent/chat` | 메시지를 보내면 AI 답변 + 이번 턴에 생긴 `pending_changes` 목록을 반환. **이 호출만으로는 아무것도 저장되지 않는다** |
| `POST /me/roadmaps/{id}/agent/confirm` | `{"approved": [...], "rejected": [...]}`로 pending change id를 승인/거절. 승인된 것만 `course_roadmap_items`에 반영(`source="ai"`, `is_confirmed=true`), 거절된 것은 `status="rejected"`로 남기고 버림 |

## 알려진 한계 / TODO

- `ANTHROPIC_API_KEY`가 채워지면 OpenAI → Anthropic Messages API로 다시 바꿀지
  결정 필요 (tool 스키마 형식이 SDK마다 달라 client 호출부 재작성 필요)
- `tool_choice="required"`를 매 턴 강제해서 왕복 횟수가 늘어나(항상 최소 1개 이상
  tool call) 응답 지연이 커졌다 — 필요하면 `MAX_TOOL_ITERATIONS`나 프롬프트로 더
  튜닝할 여지 있음
- 대화형 부분 수정("전공필수 먼저", "4학년은 가볍게" 등)은 시스템 프롬프트로만
  유도 — 실제 정확도는 검증 전
- 시간표 추천(`course_plans`/`course_plan_items`, F-03)과의 연결 로직 미구현 —
  로드맵 항목을 실제 개설 분반(`course_offerings`)으로 구체화하는 흐름 필요
