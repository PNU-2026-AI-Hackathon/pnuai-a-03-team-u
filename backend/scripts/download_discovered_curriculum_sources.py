from __future__ import annotations

import argparse
import csv
import mimetypes
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.ingestion.crawlers.department_curriculum_source_crawler import (  # noqa: E402
    DOWNLOAD_EXTENSIONS,
    create_session,
    file_extension,
    safe_filename,
    write_csv,
)


OUTPUT_COLUMNS = [
    "college_name",
    "academic_program_code",
    "program_name",
    "candidate_url",
    "candidate_title",
    "candidate_kind",
    "file_ext",
    "score",
    "source_page_url",
    "download_status",
    "downloaded_path",
    "error",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download file/page candidates from curriculum source discovery CSV.")
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path(
            "../raw_data/parsed_experiments/department_curriculum_source_discovery/department_curriculum_source_candidates.csv"
        ),
    )
    parser.add_argument(
        "--download-root",
        type=Path,
        default=Path("../raw_data/manual_staging/01_graduation_requirements/by_department"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "../raw_data/parsed_experiments/department_curriculum_source_discovery/downloaded_curriculum_sources.csv"
        ),
    )
    parser.add_argument("--max-files-per-department", type=int, default=8)
    parser.add_argument("--max-pages-per-department", type=int, default=4)
    parser.add_argument("--min-score", type=int, default=4)
    parser.add_argument(
        "--include-pages",
        action="store_true",
        help="Also save high-scoring HTML page candidates, not only downloadable files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candidates = read_csv(args.candidates.resolve())
    grouped_files = defaultdict(list)
    grouped_pages = defaultdict(list)
    for row in candidates:
        if int(row.get("score") or 0) < args.min_score:
            continue
        if row.get("candidate_kind") == "file":
            grouped_files[row["academic_program_code"]].append(row)
        elif args.include_pages and row.get("candidate_kind") == "page":
            grouped_pages[row["academic_program_code"]].append(row)

    session = create_session()
    output_rows = []
    codes = sorted(set(grouped_files) | set(grouped_pages))
    for code in codes:
        rows = grouped_files.get(code, [])
        rows = sorted(rows, key=lambda item: (-int(item.get("score") or 0), item["candidate_url"]))
        for row in rows[: args.max_files_per_department]:
            result = download_one(session, row, args.download_root.resolve())
            output_rows.append(result)
            print(
                f"{result['program_name']} {result['download_status']}: {result['candidate_title']}",
                flush=True,
            )
        page_rows = grouped_pages.get(code, [])
        page_rows = sorted(page_rows, key=lambda item: (-int(item.get("score") or 0), item["candidate_url"]))
        for row in page_rows[: args.max_pages_per_department]:
            result = download_one(session, row, args.download_root.resolve())
            output_rows.append(result)
            print(
                f"{result['program_name']} {result['download_status']}: {result['candidate_title']}",
                flush=True,
            )

    write_csv(args.output.resolve(), OUTPUT_COLUMNS, output_rows)
    print(args.output.resolve())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def download_one(session, row: dict[str, str], root: Path) -> dict[str, str]:
    output_dir = (
        root
        / row["college_name"]
        / f"{row['academic_program_code']}__{row['program_name']}"
        / "00_sources_discovered"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    result = {column: row.get(column, "") for column in OUTPUT_COLUMNS}
    result["downloaded_path"] = ""
    result["error"] = ""
    try:
        response = session.get(row["candidate_url"], timeout=(4, 10))
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - report and continue per-source.
        result["download_status"] = "failed"
        result["error"] = str(exc)
        return result

    content_type = response.headers.get("content-type", "")
    ext = normalized_extension(
        row.get("file_ext", ""),
        row.get("candidate_title", ""),
        row.get("candidate_kind", ""),
        row.get("candidate_url", ""),
        content_type,
    )
    filename = safe_filename(row.get("candidate_title", "") or row["candidate_url"], ext)
    path = unique_path(output_dir / filename)
    path.write_bytes(response.content)
    result["download_status"] = "downloaded"
    result["downloaded_path"] = str(path)
    return result


def normalized_extension(
    ext: str,
    title: str,
    candidate_kind: str = "",
    url: str = "",
    content_type: str = "",
) -> str:
    detected_ext = ext or file_extension(url, title)
    if detected_ext in DOWNLOAD_EXTENSIONS:
        return detected_ext
    guessed_ext = mimetypes.guess_extension(content_type.split(";", 1)[0].strip().lower()) if content_type else ""
    if guessed_ext in DOWNLOAD_EXTENSIONS:
        return guessed_ext
    if candidate_kind == "page":
        return ".html"
    if ext in DOWNLOAD_EXTENSIONS:
        return ext
    match = re.search(r"(\.[a-z0-9]+)(?:\s|$)", title.lower())
    if match:
        return match.group(1)
    return ".bin"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not allocate unique filename for {path}")


if __name__ == "__main__":
    main()
