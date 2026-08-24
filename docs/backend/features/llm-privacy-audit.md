# LLM 개인정보 경계 감사

`backend/app/ai/llm/langfuse_masking.py`가 참조하는 정책 문서. 외부로 나가는 두 경로
(**LLM 프로바이더**, **Langfuse**)에 무엇을 보내고 무엇을 보내지 않는지 확정한다.

작성: 2026-08-12 / 근거: 코드 실측 (아래 "검증 방법" 참고)
갱신: 2026-08-24 — Langfuse를 Cloud에서 **팀 자체 호스팅**(`https://langfuse-planu.xyz`)으로
전환. 제3자 관리형 서비스가 아니라 우리가 통제하는 서버로 나간다는 점에서 privacy
관점으로는 개선이지만, 접근 통제 근거가 "Cloud seat 제한"에서 "이 호스트 자체의
로그인/네트워크 노출"로 바뀌었으므로 아래 3절을 다시 확인할 것.

---

## 1. 외부 전송 경로는 두 개뿐이다

| 경로 | 대상 | 전송 시점 | 전송 주체 |
|------|------|-----------|-----------|
| LLM 추론 | OpenAI (`ROADMAP_AGENT_MODEL`) | 챗 요청마다 | `roadmap_chat._build_llm()`, `timetable_chat._build_llm()` |
| 관측 trace | Langfuse (팀 자체 호스팅, `langfuse-planu.xyz`) | 챗 요청마다 (비동기 배치) | `langfuse_callback.observe_agent_call()` |

임베딩(`app/ai/embeddings/openai_client.py`)은 **교육과정 카탈로그 텍스트만** 임베딩한다.
학생 데이터는 임베딩하지 않는다.

## 2. LLM에 보내는 것 / 안 보내는 것

시스템 프롬프트 = `_CORE_PROMPT` + 조건부 규칙 + `_build_student_context_block()`.

**보낸다 (학사 판단에 필수)**
- 학적 프로그램: 학과명·전공명·program_type·교육과정연도
- 진로 목표(`users.career_goal`) — 자유 입력 필드
- 이수기록: 과목명 + 이수구분 (성적 등급 자체는 컨텍스트 블록에 없음)
- 균형교양 세부영역별 이수 요약
- 도구 응답: 남은 학점, 로드맵 항목, 검색된 교육과정

**안 보낸다 (코드로 확인)**
- 이름(`users.name`), 학번(`users.student_id`), 이메일 — 컨텍스트 블록·도구 응답 어디에도 없음
- One-Stop 포털 비밀번호 — 애초에 저장하지 않고, 챗 경로와 무관
- `user_id`는 내부 PK만. `timetable_chat.py:407` 주석대로 필드명을 `student_id`로 두지 않는다
  (LLM이 학번으로 오해해 답변에 노출하는 걸 방지)

> **원칙**: 학생을 특정할 수 있는 직접 식별자는 프롬프트에 넣지 않는다. 학과·과목·학점 같은
> quasi-identifier는 서비스 기능상 필수라 보내되, 그 자체로는 개인을 특정하지 못한다.

## 3. Langfuse 마스킹 4패턴

`mask_data`가 Langfuse client `mask=` 훅으로 걸려 있어 trace input/output의 모든 문자열
리프에 재귀 적용된다. **원본 LLM 호출에는 영향 없다** (Langfuse로 나가는 페이로드만 변형).

| 패턴 | 정규식 앵커 | 치환 |
|------|------------|------|
| 이메일 | 표준 로컬@도메인 | `<EMAIL>` |
| 휴대전화 | `01X-XXXX-XXXX` (하이픈 선택) | `<PHONE>` |
| 유선전화 | `02`/`031~064` 대역 | `<PHONE>` |
| 학번 | 연도 앵커 `(19|20)\d{2}` + 4~6자리 | `<STUDENT_ID>` |

**설계 결정 2개**
1. `\b` 대신 `(?<!\d)`/`(?!\d)` — 파이썬 `\w`가 한글을 포함해서 "202112345인데요"처럼
   한글이 붙으면 `\b`가 깨진다.
2. 학번을 연도 앵커로 좁힌 이유 — `course_id`, `department_id` 같은 랜덤 정수를 학번으로
   오탐해서 지워버리면 디버깅이 불가능해진다.

**마스킹하지 않는 것**: 학과명·과목명·이수구분·학점. 개선 분석에 필수이고, 접근 통제로
커버한다. (2026-08-24 이전엔 Langfuse Cloud 프로젝트 seat 제한이 접근 통제였다. 지금은
자체 호스팅 인스턴스 자체의 로그인 계정이 그 역할을 한다 — 이 인스턴스는
`langfuse-planu.xyz`로 공개 도메인에 노출돼 있지만, 계정 발급은 팀원으로만 제한돼
있는 것으로 확인됐다. 상세는 아래 4절 "알려진 한계" 참고.)

`user_id`는 `hash_user_id()`로 salt+sha256 앞 12자만 보낸다. `LANGFUSE_USER_ID_SALT`가
비면 경고 로그를 남기고 salt=""로 폴백한다 — 이 상태는 rainbow 공격에 취약하니 배포
환경에서는 반드시 채운다.

## 4. 알려진 한계

- **마스킹은 trace에만 적용된다.** LLM 프로바이더로 가는 원본에는 적용되지 않는다 —
  애초에 프롬프트에 식별자를 넣지 않는 것(2절)이 1차 방어선이고, 마스킹은 사용자가 채팅
  창에 직접 "제 학번 202412345인데요"라고 입력한 경우를 잡는 2차 방어선이다.
- **자유 입력 필드**(`career_goal`, 채팅 메시지)는 사용자가 무엇이든 넣을 수 있다.
  4패턴에 안 걸리는 식별정보(주소, 생년월일 등)는 통과한다. 위험 대비 빈도가 낮다고
  판단해 현재는 수용한다 — 재검토 트리거는 실사용 trace 샘플링 감사.
- **탈퇴 후 trace 잔존**: 계정 삭제(`DELETE /me/account`)는 DB만 지운다. Langfuse에
  남은 해시 user_id trace는 별도 삭제 절차가 필요하다 (보안 계획 P1-4 참고).
- **자체 호스팅 인스턴스의 공개 노출**: `langfuse-planu.xyz`가 공인 도메인으로 열려
  있어 URL만 알면 로그인 화면까지는 누구나 접근 가능하다(API 키 없이는 데이터 조회
  불가하지만, UI 로그인 자체가 뚫리면 팀 전체 대화 trace가 노출된다). Langfuse Cloud
  때는 이 계층이 벤더 책임이었는데 자체 호스팅으로 오면서 우리 책임이 됐다.
  **계정 발급 범위(2026-08-24, 인스턴스 소유자 확인)**: 인스턴스 소유자(owner
  권한)가 나머지 팀원을 각자 admin으로 개별 초대하는 방식으로 운영 중이라고
  확인받았다 — 불특정 다수가 자유롭게 가입해 들어오는 구조는 아니다.
  `/auth/sign-up` 페이지 자체는 공개 도메인이라 로드는 되지만(이전 세션에서
  HTTP 200 확인), 실제 가입 성사 여부를 코드/API로 독립 검증하진 못했고 소유자
  확인에 의존한다. TLS/방화벽 등 나머지 인프라 설정은 여전히 이 문서 밖이라 별도
  확인 대상.

## 5. 검증 방법

```bash
cd backend
# 프롬프트에 이름/학번이 들어가는지 — 결과가 비어야 정상
grep -n "user\.name\|user\.student_id" app/domains/planning/roadmap_chat.py \
                                        app/domains/planning/timetable_chat.py

# 마스킹 동작 확인
python -c "
from app.ai.llm.langfuse_masking import redact_text
print(redact_text('저 202412345이고 a@pusan.ac.kr, 010-1234-5678이에요'))
"
# → 저 <STUDENT_ID>이고 <EMAIL>, <PHONE>이에요
```

## 관련 문서

- `docs/backend/security-privacy-plan.md` — 전체 보안·개인정보 계획
- `backend/app/ai/llm/langfuse_masking.py` — 구현
- `backend/app/ai/llm/langfuse_callback.py` — `mask=` 훅 연결부
