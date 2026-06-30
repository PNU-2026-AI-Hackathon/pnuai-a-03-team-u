"""Extract user-scoped PNU One-Stop graduation expected information.

This crawler is intentionally different from public/common crawlers such as the
course catalog crawler. The page contains personal academic data and should only
be collected from an authenticated page after explicit user consent.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from app.ingestion.crawlers import menu_codes
from app.ingestion.crawlers.pnu_session import goto_menu, pnu_session


SOURCE_SYSTEM = "pnu_onestop"
SOURCE_MENU_CODE = menu_codes.GRADUATION_EXPECTED_INFO
SOURCE_URL = "https://onestop.pusan.ac.kr/page?menuCD=000000000000089"

EXPECTED_TABLE_NAMES = {
    0: "major_application_info",
    1: "subject_category_completion",
    2: "required_course_completion",
    3: "general_education_area_completion",
    4: "general_required_course_completion",
    5: "major_course_completion",
    6: "graduation_requirement_completion",
}

_EXTRACT_GRADUATION_EXPECTED_INFO_JS = """
() => {
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const tables = [...document.querySelectorAll('main table, .content table, table')].map(
    (table, tableIndex) => ({
      tableIndex,
      caption: clean(table.caption?.innerText || ''),
      visible: Boolean(table.offsetWidth || table.offsetHeight || table.getClientRects().length),
      rowCount: table.rows.length,
      columnCount: Math.max(0, ...[...table.rows].map((row) => row.cells.length)),
      html: table.outerHTML,
      rows: [...table.rows].map((row, rowIndex) => ({
        rowIndex,
        cells: [...row.cells].map((cell, cellIndex) => ({
          cellIndex,
          tag: cell.tagName.toLowerCase(),
          text: clean(cell.innerText),
          rowSpan: cell.rowSpan || 1,
          colSpan: cell.colSpan || 1,
          className: cell.className || '',
        })),
      })),
    })
  );
  return {
    sourceUrl: location.href,
    pageTitle: document.title,
    extractedAt: new Date().toISOString(),
    tabs: [...document.querySelectorAll('[role=tab]')].map((tab, tabIndex) => ({
      tabIndex,
      text: clean(tab.innerText),
      selected: tab.getAttribute('aria-selected') || '',
    })),
    tables,
  };
}
"""


def extract_graduation_expected_info(page: Page) -> dict[str, Any]:
    """Extract raw graduation expected information from an authenticated page.

    The caller owns authentication and consent. This function only navigates to
    the One-Stop menu and extracts table DOM data.
    """
    goto_menu(page, SOURCE_MENU_CODE)
    payload = page.evaluate(_EXTRACT_GRADUATION_EXPECTED_INFO_JS)
    payload["sourceSystem"] = SOURCE_SYSTEM
    payload["sourceMenuCode"] = SOURCE_MENU_CODE
    payload["tableNames"] = EXPECTED_TABLE_NAMES
    return payload


def write_user_scoped_raw_output(
    output_root: Path,
    user_scope: str,
    payload: dict[str, Any],
) -> Path:
    """Write raw personal data below a user-scoped ignored directory."""
    extracted_at = payload.get("extractedAt") or datetime.now(UTC).isoformat()
    safe_timestamp = (
        extracted_at.replace(":", "").replace("-", "").replace(".", "").replace("+", "Z")
    )
    output_dir = output_root / user_scope / safe_timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "graduation_expected_info_raw.json"
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract user-scoped PNU One-Stop graduation expected information"
    )
    parser.add_argument(
        "--user-scope",
        required=True,
        help="Opaque local user scope, such as user_123 or sample_transfer_student.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("raw_data/user_data/onestop_graduation_expected_info"),
        help="Ignored root directory for personal raw outputs.",
    )
    parser.add_argument(
        "--login-id",
        default=None,
        help="Local experiment only. Prefer user-consented browser sessions in production.",
    )
    parser.add_argument(
        "--login-pw",
        default=None,
        help="Local experiment only. Prefer user-consented browser sessions in production.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with pnu_session(login_id=args.login_id, login_pw=args.login_pw) as page:
        payload = extract_graduation_expected_info(page)
    output_path = write_user_scoped_raw_output(
        output_root=args.output_root,
        user_scope=args.user_scope,
        payload=payload,
    )
    print(
        json.dumps(
            {
                "source_system": SOURCE_SYSTEM,
                "source_menu_code": SOURCE_MENU_CODE,
                "table_count": len(payload.get("tables", [])),
                "output_path": str(output_path),
                "privacy_note": "personal user data; do not commit raw outputs",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
