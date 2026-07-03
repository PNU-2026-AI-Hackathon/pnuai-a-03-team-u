# 프론트엔드 연동 가이드

지금 백엔드에서 실제로 동작하는 API만 정리했다. 여기 없는 화면(내 정보/졸업요건,
성장 로드맵)은 아직 백엔드가 없으니 붙이지 말 것 — 상세 현황은 `docs/features/`
참고.

## 실행 방법

```bash
cd backend
uvicorn app.main:app --reload
```

기본으로 `http://localhost:8000`에서 뜬다. `http://localhost:8000/docs`에 가면
Swagger UI로 모든 엔드포인트를 직접 눌러볼 수 있다 — 아래 문서보다 이게 더
최신 상태를 반영하니 헷갈리면 거기서 확인.

## 인증 흐름

1. `POST /auth/signup`으로 회원가입
2. `POST /auth/login`으로 로그인 → `access_token` 받음
3. `access_token`을 저장해뒀다가 (예: `localStorage`), 로그인이 필요한 요청에
   `Authorization: Bearer <access_token>` 헤더로 실어 보냄
4. 지금 로그인이 필요한 API는 `GET /auth/me` 하나뿐 — 나머지(추천 API 등)는
   아직 로그인 연동 전이라 `user_id`를 그냥 파라미터로 받는다 (아래 참고)

---

## POST /auth/signup

회원가입. `academic_programs`는 선택이며, 복수전공/부전공을 여러 개 추가할 수 있다.

**요청**
```json
{
  "email": "dowon@school.ac.kr",
  "password": "8자이상비밀번호",
  "name": "이도원",
  "student_id": "202355699",
  "school": "부산대학교",
  "department": "정보컴퓨터공학부",
  "career_goal": "백엔드 개발자",
  "academic_programs": [
    { "major": "컴퓨터공학전공", "program_type": "primary" },
    { "major": "경영학과", "program_type": "dual" },
    { "major": "심리학과", "program_type": "minor" }
  ]
}
```

- `email`, `password`, `name`만 필수. 나머지는 전부 선택
- `program_type`은 `primary`/`dual`/`minor`/`interdisciplinary` 중 하나
- `department`, `academic_programs[].major`는 **부산대 정식 학과/학부/전공명이어야
  한다.** 목록에 없는 이름이면 400 에러 (예: 오타, 아직 시드에 없는 학과)
- 화면에서 학과/전공을 자유 텍스트 입력이 아니라 **드롭다운/자동완성으로
  받는 걸 강력 추천** — 그래야 이 에러를 안 만남. 전체 목록이 필요하면 백엔드에
  요청

**성공 응답 (201)**
```json
{
  "id": 1,
  "email": "dowon@school.ac.kr",
  "name": "이도원",
  "student_id": "202355699",
  "school": "부산대학교",
  "department": "정보컴퓨터공학부",
  "career_goal": "백엔드 개발자",
  "academic_programs": [
    { "major": "컴퓨터공학전공", "program_type": "primary" },
    { "major": "경영학과", "program_type": "dual" },
    { "major": "심리학과", "program_type": "minor" }
  ]
}
```

**에러**
| 상태 코드 | 상황 | detail 예시 |
| --- | --- | --- |
| 400 | 비밀번호 8자 미만 | `비밀번호는 8자 이상이어야 합니다` |
| 400 | 등록 안 된 학과/전공 | `등록되지 않은 학과/전공입니다: 정보컴공학과` |
| 409 | 이메일 중복 | `이미 가입된 이메일입니다` |
| 422 | 형식 오류 (이메일 형식, 필수 필드 누락, program_type 오타 등) | 아래 참고 |

422는 400/409와 형식이 다르다 — `detail`이 문자열이 아니라 배열이다:
```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "email"],
      "msg": "value is not a valid email address: An email address must have an @-sign.",
      "input": "not-an-email"
    }
  ]
}
```
화면에는 `detail[0].msg`를 보여주면 된다 (여러 필드가 동시에 잘못되면 배열에 여러 개 옴).

---

## POST /auth/login

**요청**
```json
{ "email": "dowon@school.ac.kr", "password": "8자이상비밀번호" }
```

**성공 응답 (200)**
```json
{ "access_token": "eyJhbGciOiJIUzI1NiIs...", "token_type": "bearer" }
```

**에러**: 401 — 이메일 없음 또는 비밀번호 불일치, 둘 다 같은 메시지
(`이메일 또는 비밀번호가 올바르지 않습니다`)로 옴 — 어느 쪽이 틀렸는지
구분해서 알려주지 않는 게 의도된 동작(보안상 계정 존재 여부를 노출하지 않음)

---

## GET /auth/me

로그인 필요. 헤더: `Authorization: Bearer <access_token>`

**성공 응답 (200)**: signup 응답과 동일한 형식

**에러**: 401 — 토큰 없음/만료/잘못됨, 전부 `인증이 필요합니다`

---

## GET /activities/recommendations/{user_id}

비교과 활동 추천 그리드. **아직 로그인 연동 안 됨** — `user_id`를 URL에 그대로 넣는다
(숫자, signup 응답의 `id`). 나중에 `Authorization` 헤더 기반으로 바뀔 수 있음.

쿼리 파라미터: `limit` (기본 20)

**요청 예시**: `GET /activities/recommendations/1?limit=20`

**성공 응답 (200)**
```json
[
  {
    "activity_id": 42,
    "title": "2026 AI 해커톤 참가자 모집",
    "category": "공모전",
    "source": "swedu",
    "source_url": "https://swedu.pusan.ac.kr/...",
    "posted_date": "2026-06-28",
    "deadline": "2026-07-15",
    "d_day": 13,
    "recommendation_score": 87.3
  }
]
```

- `d_day`: 마감일까지 남은 일수. 마감일 파싱이 안 된 공지는 `null`일 수 있음 —
  화면에서 "마감일 미정" 같은 걸로 처리 필요
- `category`도 `null`일 수 있음 (자동 분류 실패)
- `recommendation_score`: 0~100 사이 값, 높을수록 추천도 높음. 정렬은 서버가
  이미 점수 내림차순으로 해서 줌
- 첫 요청 시(해당 유저 추천이 캐시에 없으면) 서버에서 즉석으로 계산해서
  **응답이 몇 초 걸릴 수 있다** — 로딩 스피너 필요

**에러**
| 상태 코드 | 상황 |
| --- | --- |
| 404 | `user_id`가 존재하지 않는 유저 |
| 404 | 유저는 있지만 추천 결과를 만들 수 없음 (예: 활동 데이터가 없거나 학과/진로 정보가 비어있음) |

---

## 아직 없는 것 (붙이지 말 것)

- "내 정보" / 졸업요건 확인 화면 — 크롤러(`app/ingestion/crawlers/pnu_session.py`
  등)는 있지만 API로 노출 안 됨
- "성장 로드맵" 화면 — 백엔드 전혀 없음

두 개 다 준비되면 이 문서에 추가하겠음.
