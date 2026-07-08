# 성장 로드맵

**미구현.** 아직 코드가 없다. 이 문서는 구현 시작 전 자리만 잡아둔 상태.

## 방향 (초안)

`docs/architecture.md`에 "roadmap guidance"로 언급된 정도만 있고 구체적인 설계는 없다.
구현을 시작하면 아래를 채운다.

- 무엇을 보여주는 기능인지 (예: 졸업까지 남은 요건 + 추천 비교과 활동을 시간순으로 엮은 개인화 로드맵)
- 어떤 데이터를 조합하는지 — [내 정보 페이지(졸업요건 확인)](./my-info-graduation-check.md) +
  비교과 활동 추천(2026-07-07 제거됨, [activity-recommendations.md](./activity-recommendations.md) 참고) 결과를
  함께 쓸 가능성이 높음
- `app/domains/planning/models.py`에 `course_plans`/`course_roadmaps` 등 테이블 스키마는
  이미 준비되어 있음 (ERD 리셋 때 추가) — 라우터/로직만 없는 상태
- API/화면 설계

## TODO

- 기능 요구사항 정리
- 데이터 모델 설계
- 구현
