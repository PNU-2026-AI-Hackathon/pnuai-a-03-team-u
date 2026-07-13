"""Build curriculum/graduation RAG chunks.

Examples:
    python -m scripts.build_rag_chunks --curriculum-year 2026
    python -m scripts.build_rag_chunks --curriculum-year 2026 --skip-embeddings
"""

from __future__ import annotations

import argparse

from app.ai.rag.curriculum_ingestion import CurriculumRagIngestionService
from app.core.db import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curriculum-year", default="2026")
    parser.add_argument("--skip-embeddings", action="store_true")
    parser.add_argument(
        "--target",
        choices=["all", "curriculum", "graduation-requirements"],
        default="all",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        service = CurriculumRagIngestionService(db)
        options = {
            "curriculum_year": args.curriculum_year,
            "with_embeddings": not args.skip_embeddings,
        }
        if args.target == "curriculum":
            result = service.ingest_curriculum(**options)
        elif args.target == "graduation-requirements":
            result = service.ingest_graduation_requirements(**options)
        else:
            result = service.rebuild_all(**options)
    finally:
        db.close()

    print(result)


if __name__ == "__main__":
    main()
