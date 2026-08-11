"""portal_credentials 테이블 데이터 폐기.

프론트 회원가입 온보딩(OnboardingPage.tsx)에 "학생지원시스템 계정 정보는
저장되지 않습니다"라고 명시돼 있지만, portal_sync가 매 요청마다 학번+암호화
비밀번호를 portal_credentials 테이블에 저장하고 있었다(2026-08-11 감사).

decrypt_secret은 백엔드 어디서도 호출되지 않고 스케줄된 백그라운드 크롤도
없어서 저장된 값을 실제로 재사용하는 코드가 없다 — 데드코드 저장이었다.

이 스크립트는:
1. portal_credentials 테이블의 모든 행을 삭제
2. 테이블 자체는 남겨둔다 (스키마 리셋 대신 정책 fix로 저장 안 하는 방향)

사용법:
    (venv) $ DATABASE_URL=... python scripts/purge_portal_credentials.py --dry-run
    (venv) $ DATABASE_URL=... python scripts/purge_portal_credentials.py --commit
"""
from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine, text


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as conn:
        cnt = conn.execute(text("SELECT COUNT(*) FROM portal_credentials")).scalar_one()
        print(f"[audit] portal_credentials 저장된 행: {cnt}건")
        if cnt == 0:
            print("[skip] 삭제 대상 없음")
            return 0

        rows = conn.execute(text(
            "SELECT id, user_id, portal, login_id, LENGTH(encrypted_password), created_at "
            "FROM portal_credentials ORDER BY id"
        )).all()
        for r in rows:
            print(f"  id={r[0]} user_id={r[1]} portal={r[2]!r} login={r[3]!r} "
                  f"pw_len={r[4]} created={r[5]}")

        if args.commit:
            deleted = conn.execute(text("DELETE FROM portal_credentials")).rowcount
            print(f"\n✅ [commit] {deleted}건 삭제 완료")
        else:
            print(f"\n🔍 [dry-run] 실제 변경 안 함. 반영하려면 --commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
