# 2026-07-29 후속 작업 백로그

이번 낮 세션(PR #94) 이후 저녁 세션에서 이어갈 만한 것들을 우선순위별로 정리.
새로 반영한 4개 주제(휴학 fix / 추천 후보 확장 / 대화 세션 / 시간표 AI)에 대해
사용자가 요구할 만한 후속을 함께 검토.

## A. 배포 전 반드시 처리 (선행 조건)

이걸 안 하면 시간표 AI·대화 세션이 실행 자체가 안 됨.

1. **로컬 Docker 환경 검증** — CLAUDE.md 원칙대로 Supabase 직행 금지.
   ```
   docker compose -f infra/docker/compose.local.yml up -d
   DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/planu \
     ./backend/.venv/bin/python -m alembic upgrade head
   ```
   - 마이그레이션 `e1f2a3b4c5d6`가 backfill을 포함하므로, 기존 chat_messages가 있는 상태에서 실행되는지 최소 시나리오 확인.
   - 확인 포인트: 로드맵당 "기본 대화" 세션이 하나씩 생기고 session_id가 모든 메시지에 채워짐, session_id NOT NULL 승격 성공.

2. **Onestop 수강편람 적재** — 시간표 AI가 실제로 동작하려면 필요.
   ```
   DATABASE_URL=... ./backend/.venv/bin/python -m scripts.import_course_offerings \
     --csv raw_data/crawled_data/onestop_course_catalog/2026_2/2026_2_course_catalog.csv
   ```
   - 우선 dry-run으로 `stats.skipped_unmatched_course` 값 확인. 매칭률이 낮으면 courses 테이블에 2026 신규 과목이 안 들어와 있을 수 있음 → `import_courses_from_ais.py` 최신화 필요.
   - 매칭률이 만족스러우면 `--commit`으로 반영.

3. **Supabase 반영** — 로컬에서 위 두 개 통과한 뒤 한 번에.
   - alembic upgrade → import_course_offerings 순서로 실행. 도중 실패 시 로컬 재검증.

---

## B. 프론트엔드 통합 (별도 PR 후보 — 백엔드 계약이 이미 명확)

### B-1. 대화 세션 사이드바
- 목록 API: `GET /me/roadmaps/{id}/agent/sessions` → 세션 id, title, message_count, updated_at
- "새 대화" 버튼: `POST /me/roadmaps/{id}/agent/sessions`
- 세션 삭제: `DELETE /me/roadmaps/{id}/agent/sessions/{sid}`
- 세션 클릭 시 채팅 화면이 그 session_id를 유지하도록 상태 관리
- 기존 "화면 대화 초기화" 버튼은 `POST /agent/reset`(모든 세션 지움) — UX 문구 변경 필요할 수 있음

### B-2. 시간표 화면
- 응답 구조: `feasible_schedules[]` / `partial_schedules[]` / `over_cap_schedules[]` / `unavailable_courses[]` / `problematic_courses[]` / `replacement_suggestions[]`
- MVP UI:
  - `feasible_schedules[0]`을 기본 화면(월~금 격자에 sections 배치)
  - 다른 조합은 "다른 조합 보기" 탭
  - `unavailable_courses`가 있으면 상단에 "이 과목들은 이번 학기에 열리지 않아요. 로드맵 상담으로 대체를 논의해보세요" 배너 + 로드맵 챗 열기 버튼
  - `over_cap_schedules`는 학점 초과 경고와 함께 별도 섹션
- 세션 사이드바의 존재를 알리는 배너에 시간표 AI 결과 링크도 함께 노출하면 도입률이 올라갈 것

### B-3. "이 조합 확정" 액션 (스코프 정해야 함)
- 지금 응답은 조합만 돌려주고 사용자가 실제로 어떤 분반을 신청했는지는 저장하지 않음
- 사용자 요구가 나올 만한 것: "이 조합으로 잡은 걸 다음번에 다시 열어보고 싶다"
- 필요 시: `roadmap_item.offering_id`를 채우거나 별도 `student_timetable` 테이블 신설
- 이번 저녁엔 스코프 밖. 사용자가 명시적으로 요구할 때 착수.

---

## C. 이번 세션 반영분에서 사용자가 요구할 가능성 있는 것들

### C-1. 휴학 fix — 재동기화 스크립트
- 이번 fix는 `sync_completed_courses_to_roadmap` 재실행 시에만 새 계산이 반영됨.
- 이미 저장돼 있는 학생 로드맵의 잘못된 planned_grade는 그대로 남아있음.
- **필요 시 액션**: 전체 사용자에 대해 `sync_completed_courses_to_roadmap`을 강제 재실행하는 batch 스크립트.
- 판단: 학생이 다음번에 로그인·성적 재동기화 트리거만 눌러도 자동 반영되면 batch 불필요. 지금 `POST /me/portal-sync`가 이 함수를 부르는지 확인 필요.
  - `portal_sync.py` 확인 결과: import 됨 (line 22, 180). 사용자가 portal-sync만 다시 태우면 반영.
- 사용자 액션 안내만 필요, 별도 스크립트는 요구가 나오면 그때.

### C-2. 대화 세션 UX 확장
사용자가 "쓰다 보니 이런 것도 필요하다"고 할 만한 것들:
- **세션 이름 수정** (`PATCH /agent/sessions/{sid}`) — 지금은 자동 title만
- **첫 응답 요약으로 title 승격** — 지금은 첫 메시지 앞 20자만
- **세션 검색** (제목/본문) — 세션이 많이 쌓이면
- **오래된 세션 자동 정리** — 저장 부담 커질 때

우선순위: 세션 이름 수정 > 나머지. MVP 사용해보고 정말 필요할 때 착수.

### C-3. 시간표 AI — 사용자 요구가 나올 만한 것

**사용자 선호 반영**
- "오전 수업 싫어" / "월요일 회피" / "공강 없는 걸로" 같은 요청 → 랭킹에 사용자 선호 축 추가.
- 저장 위치: `User.preferences JSON` 필드 신설 or 세션별 임시.
- 지금 랭킹은 요일 수 → 공백 → 학점 순으로 하드코딩.

**"이 대체 후보 넣어줘" 원클릭**
- 현재는 대체 후보 나열만 하고 로드맵 변경은 별도 챗으로 delegate. 사용자가 "이걸로 바로 바꿔줘"를 원할 수 있음.
- 후보를 pending_roadmap_changes로 바로 만들어 confirm 화면으로 유도하는 액션 추가.
- 스키마·엔드포인트 이미 있음: `PendingRoadmapChange` + `POST /agent/confirm`. 뷰만 만들면 됨.

**교수/시간대 제외**
- "홍길동 교수 빼고 짜줘" 같은 요청. 검색 파라미터 확장.

우선순위: 대체 후보 원클릭 > 사용자 선호 > 교수 제외.

### C-4. 로드맵 추천 후보 확장 — 프롬프트 회귀 확인
- 이번에 프롬프트를 상당히 수정했음. 다음 사용자 케이스에서 회귀가 없는지 확인 필요:
  - 편입생(earliest_recorded_grade=3): 1·2학년 과목이 제안되지 않아야 함
  - 신입생: 1학년 과목이 정상 제안돼야 함
  - 균형교양 세분류 요청: `category='효원균형교양'`으로 정확히 필터되는지
- 실측 방법: 실제 학생 계정 하나로 몇 개 시나리오 시연.

---

## D. 오늘 논의만 하고 미착수 — 데이터 수집 선행 필요

### D-1. 융합트랙 추천 (Task #new)
낮 세션 마지막에 논의됨. 착수 전 3가지 결정 필요:

1. **데이터 원본**: 부산대 융합전공학부? 학과별 홈페이지? 담당자 수기 시트?
2. **파일럿 범위**: 정컴 관여 트랙(들)만 vs 전체
3. **"전선 겹침" 회계 방식**: 양쪽 다 카운트인지, 한쪽만인지

착수 시 스케치:
- 스키마: `convergence_tracks`, `convergence_track_hosting_departments`, `convergence_track_courses`
- 로드맵 에이전트 확장: `_build_student_context_block`에 해당 트랙 정보 붙임, 프롬프트에 규칙 추가

### D-2. 복수·부·융합전공 DB 시드 (Task #4)
- 우선 대형 학과 + 팀 학과 범위
- `raw_data/manual_staging/` 컨벤션 따라 학과별 교육과정 수집 선행
- Task #4 → #5 순서

### D-3. 교양 세분화 (분과별)
- 균형교양 하위: 인문/사회/자연/예술체육 분과
- 핵심교양: 학생 계열별 필수 매핑
- 원본은 교양교육원 사이트 or 학과 졸업요건 문서 조합. 조사 선행.

---

## E. 저녁 세션 착수 순서 (권장)

1. **[블로킹]** Docker 켜기 → 로컬 마이그레이션 · importer 검증 → Supabase 반영 (A-1, A-2, A-3)
2. **[백엔드 후속]** C-1의 portal-sync 자동 반영 확인만 하고 넘어감(스크립트 불필요 확인)
3. **[프론트]** B-1 세션 사이드바 → B-2 시간표 화면 (스코프가 명확)
4. **[검증]** C-4의 실계정 회귀 시연
5. **[논의 정리]** D-1 융합트랙 데이터 원본 확정 (담당자 연락) — 코드 착수는 정보 확보 후

## 참고 — 이번 세션 완료 항목

- Task #1 휴학 학기 planned_grade fix — merged in PR #94
- Task #2 로드맵 추천 후보 확장 — merged in PR #94
- Task #3 AI 대화 세션 API — merged in PR #94
- Task #6 시간표 추천 AI — merged in PR #94 (백엔드만, 프론트 남음)

미착수:
- Task #4 복수·부·융합전공 DB 시드 (데이터 수집 선행)
- Task #5 다중전공 반영 로드맵 추천 (Task #4 후)
