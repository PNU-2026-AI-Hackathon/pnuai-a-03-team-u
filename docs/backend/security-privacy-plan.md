# Plan-U 보안 · 개인정보 계획

작성 2026-08-12 · 백엔드 담당

Plan-U는 **부산대 재학생의 성적·이수내역·자격증·어학점수**를 다룬다. 학사 데이터는
그 자체로 민감정보이고, 학번+이름+학과 조합이면 개인이 즉시 특정된다. 게다가 이 데이터의
일부가 **외부 LLM(OpenAI)과 관측 플랫폼(Langfuse)으로 나간다**. 이 문서는 (1) 무엇을
어디에 보관·전송하는지 인벤토리로 확정하고, (2) 현재 방어선을 감사 결과로 기록하고,
(3) 남은 갭을 우선순위와 함께 실행 가능한 작업으로 정리한다.

관련 문서: `docs/backend/features/llm-privacy-audit.md` (LLM 전송 경계 상세)

---

## 1. 데이터 인벤토리

| 등급 | 데이터 | 저장 위치 | 암호화 | 외부 전송 |
|------|--------|-----------|--------|-----------|
| **S — 자격증명** | 로그인 비밀번호 | `users.password_hash` | bcrypt (단방향) | ✗ |
| | One-Stop 포털 비밀번호 | **저장 안 함** (요청 메모리만) | — | ✗ |
| | 비밀번호 재설정 토큰 | `password_reset_tokens.token_hash` | sha256 | 메일 본문(원문 링크) |
| | 서비스 시크릿 (API 키, JWT 키, Fernet 키, DB 비번) | `backend/.env`, GitHub Secrets | — | ✗ |
| **A — 직접 식별자** | 이름, 학번, 웹메일 | `users` | 평문 | ✗ (LLM·Langfuse 모두 미전송) |
| | 지도교수명 | `users.advisor_name` | 평문 | ✗ |
| **B — 학사 민감정보** | 이수내역·성적 | `student_course_records` | 평문 | LLM에 **과목명+이수구분만** (성적 등급 제외) |
| | 자격증·어학점수·비교과 | `user_certifications`, `user_language_scores`, `user_activities` | 평문 | ✗ |
| | 학적 프로그램·졸업요건 진도 | `user_academic_programs` 외 | 평문 | LLM에 전송 |
| | 진로 목표 (자유 입력) | `users.career_goal` | 평문 | LLM에 전송 |
| **C — 파생/행동** | 챗 대화 원문 | `course_roadmap_chat_messages`, `timetable_chat_messages` | 평문 | LLM + Langfuse(마스킹 적용) |
| | 로드맵·시간표 | `course_roadmap_items`, `course_plans` | 평문 | LLM에 전송 |

> **B 등급이 평문 저장인 이유**: 졸업요건 판정 엔진이 SQL 집계로 학점을 합산하므로 컬럼
> 암호화 시 판정 자체가 불가능하다. 대신 접근 통제(Supabase 프로젝트 멤버 제한)와 전송 구간
> 암호화(HTTPS)로 커버한다. 이 트레이드오프는 의도된 것이며, 재검토 트리거는 "서비스 외부
> 공개 + 실사용자 유입"이다.

## 2. 현재 방어선 (감사 결과 — 이미 되어 있는 것)

코드 실측으로 확인했다. 새로 만들 필요 없고, **깨뜨리지 않는 것**이 목표다.

| 항목 | 구현 | 위치 |
|------|------|------|
| 비밀번호 단방향 해시 | bcrypt (passlib 미사용 — 4.1+ 호환 이슈 회피) | `core/security.py:50` |
| 재설정 토큰 | 128비트 난수 + sha256 저장 + 30분 TTL + 재발급 시 기존 무효화 | `api/auth.py:275-325` |
| 사용자 열거 방지 | 가입 여부와 무관하게 동일 응답 | `api/auth.py:284` |
| 포털 비밀번호 미저장 | 매 sync마다 재입력, `portal_credentials` 저장 중단 + 퍼지 스크립트 | `api/portal_sync.py:158`, `scripts/purge_portal_credentials.py` |
| 계정 완전 삭제 | 15개 테이블 hard delete + 삭제 행 수 반환 | `api/profile.py:370` |
| IDOR 방지 | 모든 개인 리소스가 `current_user.id` 스코프 (`_get_owned_roadmap` 패턴) | `api/roadmaps.py`, `api/timetables.py` |
| LLM 식별자 미전송 | 프롬프트에 이름·학번·이메일 없음 | `roadmap_chat._build_student_context_block` |
| Langfuse 마스킹 | 이메일/휴대폰/유선/학번 4패턴 + user_id salt 해시 | `ai/llm/langfuse_masking.py` |
| 시크릿 미커밋 | `.env*` gitignore (`.env.example`만 허용), 추적 파일에 시크릿 없음 확인 | `.gitignore:11-14` |
| 크롤 실패 응답 | 스택트레이스 대신 일반 메시지, 원본은 서버 로그만 | `api/portal_sync.py:145` |

## 3. 확인된 갭과 조치

### P0 — 이번 스프린트 (외부 공개 전 필수)

> **상태 (2026-08-14): P0 6건 모두 구현 완료.** P0-5·P0-6은 2026-08-14 코드 감사에서
> 새로 발견한 것이다(계획서에 없던 항목). 회귀 테스트는
> `backend/tests/test_security_hardening.py`. 아래 각 항목에 실제로 어떻게 막았는지 적었다.

**P0-1. 레이트 리밋이 전혀 없다** — ✅ 구현 완료
- 확인: `requirements.txt`에 slowapi 없음, `app/main.py`에 미들웨어 없음
- 노출: ① `/auth/login` 무제한 시도 → 비밀번호 brute force ② `/auth/password-reset/request`
  무제한 → 메일 폭탄 + 토큰 남발 ③ **챗 엔드포인트 무제한 → OpenAI 요금 폭탄**
  (로그인만 하면 한 사용자가 초당 수십 회 LLM 호출 가능)
- 조치: `slowapi` 도입. 엔드포인트별 정책 —
  로그인 `5/min` (IP+이메일 조합), 재설정 요청 `3/hour` (이메일), 챗 `10/min` + `100/day` (user_id),
  portal-sync `5/hour` (user_id, Playwright라 서버 자원 소모도 큼)
- 챗은 리밋 초과 시 429 + 한국어 안내. 프론트에서 그대로 노출

  **구현**: `app/core/ratelimit.py` + 엔드포인트별 `@limiter.limit`. 적용 값은
  `settings.RATE_LIMIT_*`로 뺐다 — 로그인 `5/minute;30/hour`, 회원가입 `5/hour`,
  재설정 `3/hour;10/day`, **챗 `10/minute;100/day`**, portal-sync `5/hour`.
  키는 인증 후면 user_id, 아니면 IP다(`_user_or_ip`) — IP로만 세면 같은 학교
  네트워크·NAT 뒤 학생들이 서로의 몫을 잡아먹는다. `get_current_user`가
  `request.state.user_id`를 채워 그 전환이 일어난다.
  429는 `_rate_limit_handler`가 한국어 메시지 + `Retry-After`로 돌려준다.
  ⚠️ 저장소가 in-memory라 **워커 여러 개면 한도가 프로세스 수만큼 느슨해진다**.
  스케일아웃 시 `RATE_LIMIT_STORAGE_URI=redis://...`를 채울 것.

**P0-2. JWT를 무효화할 방법이 없다** — ✅ 구현 완료 (스키마 변경 없이)
- 확인: 페이로드가 `{sub, exp}`뿐, 만료 7일, 서버측 세션 저장소 없음 (`core/security.py:71`)
- 노출: 비밀번호 변경·계정 탈퇴·토큰 유출 후에도 **최대 7일간 기존 토큰이 유효**.
  탈퇴 API 주석의 "JWT 무효화는 프론트에서 로컬 토큰 삭제로 처리"는 공격자에겐 무의미
- **구현**: 컬럼 추가 대신 토큰에 현재 `password_hash`의 지문(`pv`)을 넣고 매 요청
  대조한다(`core/security.py: password_fingerprint`). 비밀번호가 바뀌면 해시가 바뀌어
  지문이 어긋나므로 옛 토큰이 즉시 무효다. 사용자 행은 인증 과정에서 어차피 로드하므로
  **추가 쿼리도, 마이그레이션도 없다**(공유 Supabase에 손대지 않으려는 선택이기도 하다).
  `pv` 없는 옛 토큰은 거절한다 — 통과시키면 무효화가 최대 7일간 무의미해진다.
  **배포 시 기존 로그인 세션이 한 번 끊기고 재로그인이 필요하다.**
- 남은 것: "비밀번호 변경 없이 다른 기기 로그아웃"은 여전히 불가.
  그건 `users.token_valid_after` 컬럼이 필요하고 공유 DB 마이그레이션이라 별도 승인 후.

**P0-3. 포털 비밀번호가 요청 본문으로 들어오는 구간의 잔여 노출** — ✅ 구현 완료
- 저장은 안 하지만 ① Pydantic 검증 실패 시 422 응답에 입력값이 echo될 수 있고
  ② 예외 로깅·APM 연동 시 본문이 딸려갈 수 있다
- **구현**: `PortalSyncRequest.password`를 `SecretStr`로 바꿔 로그·repr에 `**********`으로
  찍히게 하고(실제 값은 `.get_secret_value()`로만 꺼냄), `app/main.py`에
  `_validation_handler`를 붙여 422 응답에서 `input`/`ctx`를 제거했다. 어디가 왜 틀렸는지
  (`loc`, `msg`, `type`)는 남겨서 프론트 안내는 그대로 된다.

**P0-4. SMTP 미설정 시 재설정 링크가 로그에 평문 출력** — ✅ 구현 완료
- 확인: `core/mailer.py:31` — 로컬 개발 편의 기능이지만 운영에서 `SMTP_HOST`가 비면
  로그 접근자가 임의 계정을 탈취할 수 있다
- **구현**: `core/mailer.py`가 `settings.ENV == "local"`일 때만 본문을 로그에 남긴다.
  그 외 환경에서는 수신자·제목만 error 로그로 남기고 **본문(=재설정 링크)은 찍지 않는다**.

**P0-5. 승인 반영이 `change.item_id`를 재검증하지 않았다** — ✅ 구현 완료 (2026-08-14 감사에서 발견)
- `apply_pending_changes`(`roadmap_chat.py`)는 change 자체는 `change.roadmap_id != roadmap.id`로
  거르지만, **`change.item_id`는 그 검사에 포함되지 않았다.** update/delete가 그 id를 그대로
  `db.get(CourseRoadmapItem, ...)`에 넣어 수정·삭제했다.
- **당시 실제로 악용 가능하지는 않았다** — 제안을 만드는 `propose_change`가 항목 소유권을
  확인해서 남의 item_id가 담긴 행이 생기지 않는다. 즉 상위 한 겹에만 의존하는 구조였다.
- 그래도 고친 이유: 승인은 **남의 로드맵 항목을 수정·삭제하는 경로**다. 상위 가드가
  리팩터링으로 바뀌거나 새 제안 경로가 추가되면 조용한 데이터 훼손이 된다. 학사 계획은
  사용자가 직접 쌓은 개인정보라 조용한 손상이 특히 나쁘다.
- **구현**: 반영 직전 `_owned_item()`으로 `item.roadmap_id == roadmap.id`를 다시 확인한다
  (defense in depth). 회귀 테스트 `ApplyPendingChangeItemOwnershipTest` 2건 —
  **수정 전 코드에서 실제로 실패하는 것까지 확인**했다.
- 함께 감사한 결과 **IDOR은 그 외에 없었다**: id를 경로로 받는 엔드포인트 22개 전부와
  중첩 리소스(`_get_owned_item`은 부모 소유권 + `item.roadmap_id` 일치 둘 다 검사),
  pending change 승인/거절 경로 모두 스코프가 걸려 있다.

**P0-6. ENV 기반 보안 가드가 fail-open이었다** — ✅ 구현 완료 (2026-08-14 감사에서 발견)
- P0-4(재설정 링크 로그)와 P1-4(크롤러 폴백)는 둘 다 `settings.ENV`가 local/dev일 때만
  개발 편의 기능을 연다. 그런데 **`ENV` 기본값이 `"local"`이었고, 배포 설정 어디에서도
  ENV를 지정하지 않았다**(`infra/`, CI, Dockerfile 전부 없음). 즉 운영에서도 local로
  평가돼 **두 가드가 전부 열린 채**였다 — 각 항목을 "구현 완료"로 적어놨지만 실제
  운영에서는 동작하지 않았다.
- `.env.example`에 `ENV` 항목 자체가 없어서 팀원이 존재를 알 방법도 없었다.
- **구현**: 기본값을 `"production"`으로 뒤집었다(fail-closed). 설정을 빠뜨리면 로컬에서
  눈에 띄게 실패하지, 운영이 조용히 노출되지 않는다. `.env.example`에 `ENV=local`을
  설명과 함께 추가. 회귀 테스트 `EnvDefaultFailsClosedTest` 2건.
- **교훈**: 환경 스위치에 보안을 걸 때는 **그 스위치가 실제 배포에서 세팅되는지**까지
  확인해야 한다. 안 그러면 문서에는 완료로 남고 운영은 열려 있다.

### P1 — 다음 스프린트

**P1-1. 계정 삭제 목록이 수동 관리라 새 테이블 추가 시 누락된다** — ✅ 구현 완료
- **감사 결과 현재 누락은 없다.** 매핑된 28개 테이블 중 직접 소유 10개 + 자식 6개 =
  16개가 전부 `_ACCOUNT_DELETE_STEPS`에 있다. 즉 **수정이 아니라 회귀 가드**다.
- **구현**: `AccountDeleteCoverageTest` — SQLAlchemy 메타데이터에서 `user_id` 컬럼이나
  users FK를 가진 테이블을 뽑고, FK를 따라 자식까지 전이 폐포를 구해 삭제 목록과 대조.
  메타데이터가 불완전하면 검사가 조용히 통과하므로 `app/**/models.py` 전부가 import되는지도
  함께 검증한다. 테이블명 오타도 잡는다 — `profile.py`가 `information_schema`에 없는
  이름을 조용히 건너뛰어서, 오타 하나면 데이터가 남은 채 200이 나간다.
- 변이 테스트로 공허하지 않음을 확인: 테이블명에 오타를 넣으면 3건이 실패한다.
- 참고: 옛 마이그레이션의 `graduation_audits` 등 user 스코프 테이블 3개는 삭제 목록에
  없지만, 현재 head 체인의 후속 마이그레이션이 전부 drop한다(마이그레이션 DAG로만 확인,
  공유 Supabase 조회 안 함).

**P1-2. 탈퇴 후 Langfuse trace가 남는다**
- DB는 지워지지만 Langfuse의 해시 user_id trace + 마스킹된 대화 원문은 남는다
- 조치: `hash_user_id(user_id)`로 필터해 trace를 삭제하는 스크립트
  (`scripts/purge_langfuse_user.py`) + 탈퇴 API가 그 해시를 응답에 포함.
  보존기간 정책(예: 90일 자동 만료)을 Langfuse 프로젝트 설정에 적용

**P1-3. 의존성 버전 핀 없음 + 스캔 없음** — ✅ 구현 완료 (2026-08-15)
- `requirements.txt`에 `==` 핀이 하나도 없다 → 빌드 재현 불가, 공급망 침해에 무방비
- 조치: `pip freeze > constraints.txt` 방식으로 핀 고정(직접 의존성은 `requirements.txt`에
  범위, 전이 의존성은 constraints), CI에 `pip-audit` + `gitleaks` 워크플로 추가
- **구현**: `backend/constraints.txt`(113개 패키지) 신설. 설치는 항상
  `pip install -r requirements.txt -c constraints.txt`. golden-eval 워크플로 2개도
  이 방식으로 바꿨다.
  - 버전은 "오늘 최신"이 아니라 **챗 골든 스윕 72/78을 실제로 낸 개발 환경 버전**으로
    고정했다. 핀 없이 새로 설치하면 `openai` 2.44→**3.1**(메이저), `cryptography`
    49→50, `wrapt` 1.17→2.3, `langchain-core` 1.4.8→1.5.5가 깔린다 —
    즉 **주간 golden-eval CI가 로컬 검증본과 다른 스택 위에서 회귀를 재고 있었다.**
    LLM 회귀 감시가 라이브러리 버전 때문에 흔들리면 감시 자체가 무의미하다.
  - 검증: CI와 같은 Python 3.12에서 이 버전 집합이 설치되는 것을 확인.
- **신규 워크플로 `.github/workflows/security-scan.yml`** (PR·main push·주간 cron)
  - `gitleaks` — **실패 시 머지 차단.** 시크릿은 푸시되면 키 폐기 말고 되돌릴 방법이 없다.
    공식 `gitleaks-action@v2`는 조직 소유 레포에서 `GITLEAKS_LICENSE`를 요구하므로
    바이너리(8.30.0)를 직접 받아 쓴다.
  - `pip-audit` — **보고만 하고 막지 않는다.** 남의 라이브러리 CVE는 즉시 못 고치는데
    막으면 무관한 PR이 전부 멈춘다. 결과는 Job Summary에 남긴다.
- **`.gitleaks.toml`**: 기본 룰 + 프로젝트 전용 룰 3개. 무작위 값으로 심어서 확인해보니
  **기본 룰셋은 이 프로젝트가 실제로 쓰는 시크릿 3종(OpenAI `sk-proj-`, Anthropic
  `sk-ant-`, 비밀번호 포함 Postgres URI)을 전부 못 잡았다** — 기본만 믿었으면 통과
  도장짜리 게이트가 될 뻔했다. 오탐 허용은 확인된 것만 좁게(문서의 잘린 JWT 예시,
  `.env.example`의 빈 값 줄, 로컬 docker `postgres:postgres@localhost`).
  - 검증: 히스토리 422커밋 전수 스캔 = 실제 시크릿 0건(유일한 검출은 API 문서의
    잘린 JWT 예시로 오탐 확인). 심어둔 실키 형태 6종은 6/6 검출.
- **첫 실행 성과**: `pip-audit`가 취약점 9건(4개 패키지)을 즉시 찾았다 —
  `aiohttp` 3.14.1(WebSocket 업그레이드 경유 request smuggling 등 3건, 3.14.3에서 수정),
  `pyasn1` 0.6.3(ASN.1 디코더 DoS 3건, 0.6.4에서 수정),
  `cryptography` 49.0.0(PKCS#7 Bleichenbacher 오라클, 50.0.0에서 수정),
  `ecdsa` 0.19.2(Minerva 타이밍 공격, **업스트림 수정 계획 없음**).
  - `ecdsa`는 `python-jose[cryptography]`가 끌고 오는데, 우리 JWT는
    `JWT_ALGORITHM="HS256"`(HMAC)이라 서명에 ECDSA를 쓰지 않는다 → 인증 경로와 무관.
  - `cryptography`의 취약 API(`pkcs7_decrypt_*`)도 우리 코드에서 쓰지 않는다. 메이저
    업그레이드는 `python-jose` 호환 확인이 필요해 별도 작업으로 분리한다.
  - **조치**: 수정본이 있는 `aiohttp` 3.14.1→**3.14.3**, `pyasn1` 0.6.3→**0.6.4**로
    올렸다(패치 릴리스). 상향 후 Python 3.12 설치 재확인 + 재감사 결과
    **9건 → 2건**.
  - **남은 2건은 수용**한다(위 근거대로 우리 경로에서 도달 불가). 다음에 다시 볼 조건:
    ① `python-jose`를 걷어내거나 `cryptography` 50 호환이 확인되면 상향,
    ② PKCS#7 복호화나 ECDSA 서명을 쓰기 시작하면 즉시 재평가.

**P1-4. 개발자 개인 학교 계정이 크롤러 기본값으로 폴백된다** — ✅ 구현 완료
- `crawlers/pnu_session.py:103` — 인자 없으면 `settings.PNU_LOGIN_ID/PW` 사용.
  `.env`가 팀 채널로 공유되면 개인 부산대 계정이 그대로 노출된다
- **구현**: `_resolve_credentials()`가 **아이디·비밀번호 둘 다 안 넘어왔을 때만**
  `.env` 폴백을 적용하고, 그것도 `ENV`가 local/dev일 때만이다. 한쪽만 넘기면 어느
  환경에서도 거절한다 — 예전 `login_id or settings.PNU_LOGIN_ID` 방식은 "호출자 아이디 +
  **개발자 비밀번호**" 조합을 조용히 만들 수 있었다. 검증은 `browser.new_context()`
  **전에** 하므로 거절된 호출은 원격 사이트에 아무 요청도 보내지 않는다.
- 운영 경로 영향 없음: `api/portal_sync.py`는 항상 사용자가 입력한 두 값을 넘긴다.
- ⚠️ 이 가드는 `ENV`에 의존한다 — 실제로 동작하려면 **P0-6**이 함께 있어야 한다.

**P1-5. CORS 설정 완화 여지** — ✅ `allow_credentials=False` 적용
- `allow_credentials=True`인데 인증은 Authorization 헤더(localStorage 토큰)로 하고 쿠키를
  쓰지 않는다 → `False`로 낮춰도 동작에 영향 없고 공격면만 줄어든다
- **검증 후 적용**: 백엔드 전체에 `set_cookie`/`request.cookies`/`SessionMiddleware`/
  `Cookie(...)` 사용 0건, 프론트에 `withCredentials`/`document.cookie`/`credentials:
  'include'` 0건을 확인하고 나서 `main.py`를 `allow_credentials=False`로 바꿨다.
  회귀 테스트가 응답에 `access-control-allow-credentials`가 없고 `Set-Cookie`도
  안 나가는 걸 검사한다. 쿠키 세션을 도입하면 CSRF 대책과 함께 다시 켜야 한다.
- `CORS_ORIGIN_REGEX`가 Vercel preview 전체(`...-*.vercel.app`)를 허용한다.
  현재는 수용하되, 운영 도메인 확정 후 프로덕션 백엔드에서는 preview 패턴 제거

**P1-6. 프론트 토큰이 localStorage에 있다**
- XSS 하나면 토큰이 통째로 나간다. httpOnly 쿠키 전환은 CSRF 대책까지 따라와서 이번
  일정에는 과하다
- 대신 최소 조치: 응답에 CSP 헤더 추가(인라인 스크립트 차단), `rememberLogin=false`일 때
  sessionStorage를 쓰는 현재 동작 유지, 의존성에 알려진 XSS 취약점 없는지 `npm audit`


### P2 — 서비스 공개 전

- **개인정보처리방침 + 수집 동의** — 미착수 (외부 공개 시점의 선행 조건)
  수집 항목·보유기간·파기 절차 명시. 특히 **OpenAI·Langfuse로 학사정보가 나가는 것은
  "처리위탁"**이라 고지가 필요하다. 온보딩에 "학생지원시스템 계정 정보는 저장하지
  않습니다" 문구는 이미 있으니, 같은 자리에 LLM 위탁 고지를 추가.
  **지금 착수하지 않는 이유**: 해커톤 기간에는 OpenAI·Langfuse로 실제 대화를 보내야
  LLM 품질 검증(골든 데이터셋·트레이싱)이 돌아간다. 위탁 범위가 확정되는 배포 시점에
  방침을 쓰는 것이 맞다 — 지금 쓰면 검증 과정에서 바뀔 내용을 미리 박아두는 셈이다.
- **보존기간 정책** — ✅ 파기 도구 구현 완료 (2026-08-21), 자동 스케줄은 보류
  - `users.last_login_at` 추가 + 로그인 시 스탬프. `updated_at`은 프로필 수정에만
    반응하고 로그인(조회)에는 안 움직여서 미접속 판단에 쓸 수 없다.
  - `scripts/purge_inactive_accounts.py` — 기본 24개월, 삭제 순서는 회원 탈퇴 API의
    `_ACCOUNT_DELETE_STEPS`를 재사용(목록을 두 벌 두면 새 테이블이 한쪽에만 빠진다).
  - **기본이 dry-run이고 `--commit`을 명시해야 지운다. 자동 배치로 걸지 않았다** —
    아래 "DB 백업 + 복구 리허설"이 끝나기 전에 자동 삭제를 켜는 건 순서가 뒤바뀐
    것이고, 팀 공유 DB 하나를 5명이 쓰는 상황에서 날짜 계산이 하루만 어긋나도
    복구할 수 없다. 전체의 50%를 넘겨 지우려 하면 스크립트가 스스로 멈춘다.
  - **남은 것**: 백업·복구 리허설 후 APScheduler 월 1회 등록 + 파기 예정 안내 메일
- **접근 감사 로그**: 팀원 5명이 Supabase에 직접 접근한다. 최소한 누가 언제 프로덕션 DB에
  붙었는지 기록 (Supabase 로그 보존 설정)
- **DB 백업 + 복구 리허설**: 백업 존재 여부와 복호화 절차를 실제로 한 번 돌려본다

## 4. LLM 특화 위협

| 위협 | 현재 상태 | 조치 |
|------|-----------|------|
| 프롬프트 인젝션으로 타인 데이터 조회 | **불가** — 모든 도구가 `_ToolContext(db, user, roadmap)`에 바인딩돼 user_id를 인자로 받지 않는다 | 유지. 도구에 user_id/roadmap_id 파라미터를 추가하는 변경은 금지 |
| 인젝션으로 무단 DB 변경 | **불가** — `propose_change`는 제안만 만들고, 실제 반영은 사용자 승인 API(`apply_pending_changes`)에서만 | 유지 |
| 시스템 프롬프트 유출 | 가능 (프롬프트 자체는 비밀 아님) | 수용 |
| 판정을 LLM이 하게 되는 경계 붕괴 | 규칙 엔진이 판정, LLM은 설명만 (`CLAUDE.md` 절대 원칙 1) | 골든 데이터셋 assertion으로 회귀 감시 |
| 대화 원문의 자유 입력 PII | 4패턴 마스킹 후 Langfuse 전송, LLM 원본에는 그대로 | `llm-privacy-audit.md` 4절 한계 참고 |
| 비용 남용 | ✅ 챗 `10/minute;100/day` 리밋 적용 | user_id 기준. 스케일아웃 시 redis 저장소 필요 |

## 5. 실행 순서

```
✅ 완료  P0-1 레이트 리밋 · P0-2 JWT 무효화 · P0-3 SecretStr+422 · P0-4 메일 로그 가드
        (2026-08-13, 회귀 테스트 tests/test_security_hardening.py)

남은 것
2주차  P0-2 후속: users.token_valid_after (비번 변경 없이 기기 로그아웃) — DB 마이그레이션 승인 필요
      P1-1 계정 삭제 커버리지 테스트
3주차  P1-3 의존성 핀 + gitleaks/pip-audit CI
      P1-2 Langfuse 퍼지 스크립트 · P1-4 크롤러 폴백 제한
이후   P1-5/6, P2 (공개 일정에 맞춰)
```

## 6. PR 리뷰 체크리스트

새 코드가 개인정보를 만지면 아래를 확인한다.

- [ ] 새 엔드포인트가 개인 리소스를 다루면 `Depends(get_current_user)` + `user_id` 스코프 필터가 있는가 (경로 파라미터 id만 믿지 않는가)
- [ ] 새로 만든 테이블에 `user_id`가 있으면 `_ACCOUNT_DELETE_STEPS`에 추가했는가
- [ ] LLM 프롬프트·도구 응답에 이름/학번/이메일을 넣지 않았는가
- [ ] 도구 함수 시그니처에 `user_id`/`roadmap_id` 같은 스코프 파라미터를 추가하지 않았는가
- [ ] 로그에 비밀번호·토큰·재설정 링크가 찍히지 않는가
- [ ] 새 시크릿은 `.env.example`에 **이름만** 추가하고 값은 팀 채널로 공유했는가
- [ ] 새 LLM 호출 경로가 생겼으면 `observe_agent_call`로 감싸 마스킹이 적용되는가

## 7. 사고 대응 — 키가 유출됐을 때

| 키 | 재발급 | 여파 |
|----|--------|------|
| `OPENAI_API_KEY` | OpenAI 대시보드에서 폐기·재발급 | 요금. 즉시 폐기 |
| `JWT_SECRET_KEY` | 새로 생성 | **모든 사용자 강제 로그아웃** (기존 토큰 전부 무효 — 의도된 동작) |
| `CREDENTIAL_ENCRYPTION_KEY` | 새로 생성 | 현재 이 키로 암호화된 실사용 데이터 없음(포털 비번 저장 중단). 교체 자유 |
| `DATABASE_URL` 비번 | Supabase에서 회전 | 전원 `.env` 갱신 필요 |
| `LANGFUSE_*` | Langfuse 프로젝트에서 재발급 | 관측 데이터 노출. `USER_ID_SALT`도 함께 회전 |

공통: 유출 경로가 git 커밋이면 키 폐기가 우선이고 히스토리 정리는 그 다음이다
(커밋을 지워도 이미 노출된 키는 되돌아오지 않는다).
