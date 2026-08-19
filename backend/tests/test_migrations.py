"""alembic 리비전 그래프 정합성 테스트.

2026-08-16(PR #149)에 추가된 마이그레이션이 **이미 쓰이던 revision id**(`c3d4e5f6a7b8`,
2026-07-09 PR #51)를 재사용했다. 같은 id를 가진 파일이 둘이 되면서 alembic이 한 노드에
서로 다른 부모를 붙였고, 리비전 그래프에 19개짜리 사이클이 생겨
`alembic current` / `heads` / `upgrade` 가 전부 `CycleDetected`로 죽었다.

**3일 동안 아무도 몰랐다.** 마이그레이션을 안 돌리면 티가 안 나기 때문이다. 파이썬
import도 통과하고, 테스트도 통과하고, 앱도 뜬다 — `alembic`을 실행할 때만 터진다.

그래서 여기서 그래프 자체를 검사한다. ScriptDirectory가 파일을 전부 읽어 그래프를
만들므로, 중복 id·사이클·다중 head가 있으면 이 테스트가 먼저 잡는다.
"""

import collections
import pathlib
import re
import unittest


_MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _declared_revisions() -> dict[str, list[str]]:
    """파일에 선언된 revision id → 그 id를 선언한 파일명 목록.

    ScriptDirectory는 중복 id를 만나면 나중 것으로 덮어써서 "중복이 있었다"는 사실
    자체가 사라진다. 그래서 중복 검사만은 파일을 직접 읽어서 한다.
    """
    by_revision: dict[str, list[str]] = collections.defaultdict(list)
    for path in sorted(_MIGRATIONS_DIR.glob("*.py")):
        match = re.search(
            r'^revision(?::\s*str)?\s*=\s*["\']([^"\']+)["\']',
            path.read_text(encoding="utf-8"),
            re.M,
        )
        if match:
            by_revision[match.group(1)].append(path.name)
    return by_revision


class MigrationGraphTest(unittest.TestCase):
    def test_revision_ids_are_unique(self):
        duplicates = {
            revision: files
            for revision, files in _declared_revisions().items()
            if len(files) > 1
        }
        self.assertEqual(
            {}, duplicates,
            msg=("같은 revision id를 선언한 파일이 둘 이상이다. alembic 그래프가 깨진다 "
                 "— 새 마이그레이션은 id를 손으로 짓지 말고 `alembic revision -m ...`이 "
                 f"발급하게 할 것: {duplicates}"),
        )

    def test_graph_builds_and_has_single_head(self):
        """ScriptDirectory 생성 = 그래프 빌드. 사이클이 있으면 여기서 CycleDetected."""
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(_MIGRATIONS_DIR.parents[1] / "alembic.ini"))
        script = ScriptDirectory.from_config(config)

        heads = script.get_heads()
        self.assertEqual(
            1, len(heads),
            msg=(f"head가 {len(heads)}개다({heads}). 여러 head가 있으면 "
                 "`alembic upgrade head`가 'Multiple head revisions' 로 실패한다 — "
                 "merge 리비전을 만들거나 down_revision을 이어붙여야 한다."),
        )
        # 그래프를 실제로 끝까지 순회해 본다 (사이클이면 여기서 터진다).
        self.assertGreater(len(list(script.walk_revisions())), 1)


if __name__ == "__main__":
    unittest.main()
