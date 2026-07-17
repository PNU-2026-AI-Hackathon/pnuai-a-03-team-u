# 프론트엔드 연동 가이드

지금 백엔드에서 실제로 동작하는 API만 정리했다. 여기 없는 화면(내 정보/졸업요건,
성장 로드맵)은 아직 백엔드가 없으니 붙이지 말 것 — 상세 현황은 `docs/backend/features/`
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
4. 지금 로그인이 필요한 API는 `GET /auth/me` 하나뿐

---

## POST /auth/signup

**2026-07-14부로 로그인 식별자가 이메일 → 학번(student_id)으로 바뀌었다** — 요청/응답에
`email` 필드가 없다. `AuthPage.tsx`의 이메일 입력칸을 학번 입력칸으로 바꿔야 함.

회원가입. `academic_programs`는 선택이며, 복수전공/부전공을 여러 개 추가할 수 있다.

**요청**
```json
{
  "student_id": "202355699",
  "password": "8자이상비밀번호",
  "name": "이도원",
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

- `student_id`, `password`, `name`만 필수. 나머지는 전부 선택
- `program_type`은 `primary`/`dual`/`minor`/`interdisciplinary` 중 하나
- 학과/전공명은 자유 텍스트로 보내도 된다 — 없으면 자동 생성(get-or-create)된다.
  단, 오타가 그대로 새 학과로 만들어질 수 있으니 화면에서 드롭다운/자동완성으로
  받는 걸 추천

**성공 응답 (201)**
```json
{
  "id": 1,
  "name": "이도원",
  "student_id": "202355699",
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
| 409 | 학번 중복 | `이미 가입된 학번입니다` |
| 422 | 형식 오류 (필수 필드 누락, program_type 오타 등) | 아래 참고 |

422는 400/409와 형식이 다르다 — `detail`이 문자열이 아니라 배열이다:
```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "student_id"],
      "msg": "Field required"
    }
  ]
}
```
화면에는 `detail[0].msg`를 보여주면 된다 (여러 필드가 동시에 잘못되면 배열에 여러 개 옴).

---

## POST /auth/login

**요청**
```json
{ "student_id": "202355699", "password": "8자이상비밀번호" }
```

**성공 응답 (200)**
```json
{ "access_token": "eyJhbGciOiJIUzI1NiIs...", "token_type": "bearer" }
```

**에러**: 401 — 학번 없음 또는 비밀번호 불일치, 둘 다 같은 메시지
(`학번 또는 비밀번호가 올바르지 않습니다`)로 옴 — 어느 쪽이 틀렸는지
구분해서 알려주지 않는 게 의도된 동작(보안상 계정 존재 여부를 노출하지 않음)

---

## GET /auth/me

로그인 필요. 헤더: `Authorization: Bearer <access_token>`

**성공 응답 (200)**: signup 응답과 동일한 형식

**에러**: 401 — 토큰 없음/만료/잘못됨, 전부 `인증이 필요합니다`

---

## 아직 없는 것 (붙이지 말 것)

- **비교과 활동 추천 그리드** (`GET /activities/recommendations/{user_id}`) —
  API 자체는 동작하지만 오류가 많아 정리 중이라 지금은 프론트에서 붙이지 말 것.
  회원가입/로그인 같은 필수 기능부터 완성한 다음에 다시 추가할 예정
- "내 정보" / 졸업요건 확인 화면 — 크롤러(`app/ingestion/crawlers/pnu_session.py`
  등)는 있지만 API로 노출 안 됨
- "성장 로드맵" 화면 — 백엔드 전혀 없음

준비되면 이 문서에 다시 추가하겠음.
