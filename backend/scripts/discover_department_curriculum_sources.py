from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.ingestion.crawlers.department_curriculum_source_crawler import (
    PNU_COLLEGES_URL,
    create_session,
    discover_pnu_homepages,
    discover_source_candidates,
    download_candidates,
    load_targets,
    match_homepages,
    review_rows,
    write_csv,
    write_json,
)


HOMEPAGE_COLUMNS = [
    "college_name",
    "academic_program_code",
    "program_name",
    "listed_college_name",
    "listed_program_name",
    "homepage_url",
    "pnu_college_page_url",
    "match_status",
    "match_method",
]
CANDIDATE_COLUMNS = [
    "college_name",
    "academic_program_code",
    "program_name",
    "homepage_url",
    "candidate_url",
    "candidate_title",
    "candidate_kind",
    "file_ext",
    "score",
    "has_curriculum_keyword",
    "has_undergraduate_keyword",
    "has_minor_keyword",
    "has_dual_major_keyword",
    "source_page_url",
    "downloaded_path",
]
REVIEW_COLUMNS = [
    "college_name",
    "academic_program_code",
    "program_name",
    "homepage_url",
    "homepage_match_status",
    "candidate_count",
    "undergraduate_candidate_count",
    "minor_candidate_count",
    "dual_major_candidate_count",
    "downloadable_candidate_count",
    "needs_review",
    "review_reason",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover department curriculum pages/files from official PNU college links."
    )
    parser.add_argument(
        "--targets",
        type=Path,
        default=Path("../raw_data/manual_staging/01_graduation_requirements/by_department/_collection_targets_index.csv"),
    )
    parser.add_argument("--pnu-colleges-url", default=PNU_COLLEGES_URL)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("../raw_data/parsed_experiments/department_curriculum_source_discovery"),
    )
    parser.add_argument(
        "--download-root",
        type=Path,
        default=Path("../raw_data/manual_staging/01_graduation_requirements/by_department"),
    )
    parser.add_argument("--max-departments", type=int, default=0)
    parser.add_argument("--max-pages-per-site", type=int, default=40)
    parser.add_argument("--max-downloads-per-department", type=int, default=12)
    parser.add_argument("--delay-seconds", type=float, default=0.15)
    parser.add_argument("--download", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    targets = load_targets(args.targets.resolve())
    if args.max_departments:
        targets = targets[: args.max_departments]

    session = create_session()
    homepages = discover_pnu_homepages(session, args.pnu_colleges_url, args.delay_seconds)
    homepage_rows = match_homepages(targets, homepages)

    all_candidates = []
    homepage_by_code = {row["academic_program_code"]: row for row in homepage_rows}
    for index, target in enumerate(targets, start=1):
        homepage_url = homepage_by_code.get(target.academic_program_code, {}).get("homepage_url", "")
        candidates = discover_source_candidates(
            session,
            target,
            homepage_url,
            max_pages=args.max_pages_per_site,
            delay_seconds=args.delay_seconds,
        )
        if args.download:
            downloaded = download_candidates(
                session,
                candidates,
                target,
                args.download_root.resolve(),
                max_downloads=args.max_downloads_per_department,
            )
            downloaded_by_url = {item.candidate_url: item for item in downloaded}
            candidates = [downloaded_by_url.get(item.candidate_url, item) for item in candidates]
        all_candidates.extend(candidates)
        print(f"[{index}/{len(targets)}] {target.program_name}: {len(candidates)} candidates", flush=True)

    candidate_rows = [asdict(candidate) for candidate in all_candidates]
    review = review_rows(targets, homepage_rows, all_candidates)

    write_csv(output_dir / "pnu_department_homepages.csv", HOMEPAGE_COLUMNS, homepage_rows)
    write_csv(output_dir / "department_curriculum_source_candidates.csv", CANDIDATE_COLUMNS, candidate_rows)
    write_csv(output_dir / "departments_needing_review.csv", REVIEW_COLUMNS, review)
    write_json(
        output_dir / "summary.json",
        {
            "target_departments": len(targets),
            "pnu_homepage_links": len(homepages),
            "matched_homepages": sum(1 for row in homepage_rows if row["match_status"] == "matched"),
            "ambiguous_homepages": sum(1 for row in homepage_rows if row["match_status"] == "ambiguous"),
            "unmatched_homepages": sum(1 for row in homepage_rows if row["match_status"] == "unmatched"),
            "source_candidates": len(candidate_rows),
            "departments_needing_review": sum(1 for row in review if row["needs_review"] == "Y"),
            "download_enabled": args.download,
            "output_files": {
                "homepages": str(output_dir / "pnu_department_homepages.csv"),
                "candidates": str(output_dir / "department_curriculum_source_candidates.csv"),
                "review": str(output_dir / "departments_needing_review.csv"),
                "summary": str(output_dir / "summary.json"),
            },
        },
    )
    print(output_dir)


if __name__ == "__main__":
    main()
