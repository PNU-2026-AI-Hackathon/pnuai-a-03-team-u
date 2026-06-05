# Contributing Guide

## 브랜치 전략

```
main       ← 최종 제출본 (PR + 승인 필수)
develop    ← 통합 개발 브랜치 (PR 필수)
feature/*  ← 기능 개발 (예: feature/login)
fix/*      ← 버그 수정 (예: fix/auth-error)
docs/*     ← 문서 작성 (예: docs/readme-update)
```

## 브랜치 규칙

- `main`, `develop`에 직접 push 금지 — **PR 필수**
- `feature/*` → `develop` → `main` 순서로 merge
- 본인 PR은 본인이 merge 불가 (최소 1명 리뷰 후 merge)

## 커밋 메시지 컨벤션

```
feat:     새로운 기능 추가
fix:      버그 수정
docs:     문서 수정
style:    코드 포맷팅 (기능 변경 없음)
refactor: 코드 리팩토링
test:     테스트 코드
chore:    빌드 설정, 패키지 수정
```

**예시**
```
feat: 사용자 로그인 기능 구현
fix: 토큰 만료 오류 수정
docs: README 설치 방법 추가
```

## PR 규칙

- PR 제목: `[feat] 로그인 기능 구현` 형태
- PR 본문에 **변경사항 / 테스트 방법** 포함
- 리뷰어 최소 1명 지정

## Issue 라벨

| 라벨 | 용도 |
|------|------|
| `bug` | 버그 신고 |
| `feature` | 기능 요청 |
| `docs` | 문서 관련 |
| `in progress` | 작업 중 |
