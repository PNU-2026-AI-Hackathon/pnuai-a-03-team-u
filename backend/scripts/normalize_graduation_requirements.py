from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.ingestion.normalizers.graduation_requirement_normalizer import (
    GraduationRequirementNormalizer,
    RequirementNormalizerContext,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize department graduation requirement source files."
    )
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--college")
    parser.add_argument("--department-code")
    parser.add_argument("--department-name")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_dir = args.source_dir.resolve()
    if not source_dir.exists():
        raise SystemExit(f"source_dir does not exist: {source_dir}")

    context = RequirementNormalizerContext(
        college=args.college,
        department_code=args.department_code,
        department_name=args.department_name,
    )
    normalizer = GraduationRequirementNormalizer()
    normalized = normalizer.normalize_directory(source_dir, context)

    output = args.output
    if output is None:
        output = source_dir.parent / "01_normalized" / "graduation_requirements.normalized.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(normalizer.dumps(normalized), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
