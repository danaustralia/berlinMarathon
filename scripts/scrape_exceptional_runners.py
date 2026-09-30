#py -m pip install requests beautifulsoup4

#sample
#py .\scrape_exceptional_runners.py --max-pages 5 --delay 1

#Start
#py .\scrape_exceptional_runners.py --delay 1

#resume
#py .\scrape_exceptional_runners.py --delay 1 --resume

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://berlin.r.mikatiming.com/2026/"

EVENT_ID = "BML_HCH3C0OH37C"

TIME_RE = re.compile(
    r"^\d{1,2}:\d{2}:\d{2}$"
)

COUNTRY_RE = re.compile(
    r"\(([A-Z0-9]{3})\)\s*$"
)

CHECKPOINT_SUFFIX = ".checkpoint.json"


# ============================================================
# Helpers
# ============================================================

def clean_text(value: str | None) -> str:
    if not value:
        return ""

    value = (
        value
        .replace("\xa0", " ")
        .replace("–", "-")
        .strip()
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value


def normalize_dash(value: str) -> str:
    value = clean_text(value)

    if value in {
        "",
        "-",
        "—",
        "–",
    }:
        return ""

    return value


def is_finish_time(value: str) -> bool:
    """
    Return True only for a normal marathon finish time.
    """

    value = normalize_dash(value)

    return bool(
        TIME_RE.fullmatch(value)
    )


def classify_finish(
    finish_value: str,
) -> str:
    """
    Classify summary-page finish values.

    HH:MM:SS -> FINISHED
    DSQ      -> DSQ
    blank/-  -> NO_FINISH
    anything else -> OTHER
    """

    value = normalize_dash(
        finish_value
    )

    if is_finish_time(value):
        return "FINISHED"

    if value.upper() == "DSQ":
        return "DSQ"

    if not value:
        return "NO_FINISH"

    return "OTHER"


# ============================================================
# HTTP
# ============================================================

def create_session() -> requests.Session:
    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0.0.0 "
                "Safari/537.36"
            ),
            "Accept": (
                "text/html,"
                "application/xhtml+xml,"
                "application/xml;q=0.9,"
                "*/*;q=0.8"
            ),
            "Accept-Language": (
                "en-US,en;q=0.9"
            ),
        }
    )

    return session


def build_page_url(
    page_number: int,
) -> str:
    return (
        f"{BASE_URL}"
        f"?page={page_number}"
        f"&event={EVENT_ID}"
        f"&pid=search"
        f"&pidp=start"
    )


def fetch_page(
    session: requests.Session,
    page_number: int,
    timeout: float,
) -> str:

    url = build_page_url(
        page_number
    )

    response = session.get(
        url,
        timeout=timeout,
        allow_redirects=True,
    )

    if response.status_code == 403:
        raise PermissionError(
            "HTTP 403 Forbidden"
        )

    response.raise_for_status()

    if not response.text:
        raise RuntimeError(
            f"Page {page_number}: "
            f"empty response"
        )

    return response.text


# ============================================================
# HTML parsing
# ============================================================

def get_value_without_label(
    element,
) -> str:
    """
    MikaTiming mobile markup puts a label inside
    the same div as the value.

    Example:
        <div class="list-field type-time">
          <div class="list-label">Finish</div>
          03:32:15
        </div>

    This removes the nested label first.
    """

    if element is None:
        return ""

    clone = BeautifulSoup(
        str(element),
        "html.parser",
    )

    for label in clone.select(
        ".list-label"
    ):
        label.decompose()

    return normalize_dash(
        clone.get_text(
            " ",
            strip=True,
        )
    )


def get_labeled_field(
    row,
    label_name: str,
) -> str:

    for label in row.select(
        ".list-label"
    ):

        if (
            clean_text(label.get_text())
            .lower()
            == label_name.lower()
        ):

            parent = label.parent

            return (
                get_value_without_label(
                    parent
                )
            )

    return ""


def extract_country_code(
    displayed_name: str,
) -> str:

    match = COUNTRY_RE.search(
        displayed_name
    )

    if not match:
        return ""

    return match.group(1)


def extract_runner_id(
    href: str,
) -> str:

    if not href:
        return ""

    decoded = html.unescape(
        href
    )

    parsed = urlparse(
        decoded
    )

    query = parse_qs(
        parsed.query
    )

    return (
        query.get(
            "idp",
            [""],
        )[0]
    )


def parse_runner_row(
    row,
) -> dict | None:

    name_link = row.select_one(
        "h4.type-fullname a"
    )

    if name_link is None:
        return None

    href = (
        name_link.get(
            "href",
            "",
        )
    )

    runner_id = extract_runner_id(
        href
    )

    if not runner_id:
        return None

    displayed_name = clean_text(
        name_link.get_text(
            " ",
            strip=True,
        )
    )

    country_code = (
        extract_country_code(
            displayed_name
        )
    )

    # --------------------------------------------------------
    # Place fields
    # --------------------------------------------------------

    place_fields = row.select(
        ".type-place"
    )

    place_total = ""

    place_age = ""

    if len(place_fields) >= 1:
        place_total = normalize_dash(
            place_fields[0]
            .get_text(
                " ",
                strip=True,
            )
        )

    if len(place_fields) >= 2:
        place_age = normalize_dash(
            place_fields[1]
            .get_text(
                " ",
                strip=True,
            )
        )

    # --------------------------------------------------------
    # Labeled fields
    # --------------------------------------------------------

    bib_number = get_labeled_field(
        row,
        "Bib Number",
    )

    age_group = get_labeled_field(
        row,
        "Age Group",
    )

    club = get_labeled_field(
        row,
        "Club",
    )

    gun_time = get_labeled_field(
        row,
        "Gun time",
    )

    finish = get_labeled_field(
        row,
        "Finish",
    )

    status = classify_finish(
        finish
    )

    detail_url = urljoin(
        BASE_URL,
        html.unescape(href),
    )

    return {
        "RunnerID": runner_id,
        "BibNumber": bib_number,
        "CountryCode": country_code,
        "AgeGroup": age_group,
        "Club": club,
        "Place": place_total,
        "PlaceAgeGroup": place_age,
        "GunTime": gun_time,
        "Finish": finish,
        "SummaryStatus": status,
        "DetailUrl": detail_url,
    }


def parse_page(
    html_text: str,
) -> list[dict]:

    soup = BeautifulSoup(
        html_text,
        "html.parser",
    )

    rows = []

    for row in soup.select(
        "ul.list-group-multicolumn "
        "> li.list-group-item"
    ):

        # Skip table header
        if "list-group-header" in (
            row.get(
                "class",
                []
            )
        ):
            continue

        parsed = parse_runner_row(
            row
        )

        if parsed:
            rows.append(
                parsed
            )

    return rows


# ============================================================
# Pagination
# ============================================================

def decode_data_silver(
    value: str,
) -> str:
    """
    MikaTiming stores pagination targets in
    comma-separated ASCII values.

    Example:
        63,112,97,103,101,61,50,...

    becomes:
        ?page=2&...
    """

    if not value:
        return ""

    try:

        numbers = [
            int(part)
            for part
            in value.split(",")
            if part.strip()
        ]

        return "".join(
            chr(n)
            for n in numbers
        )

    except Exception:
        return ""


def detect_last_page(
    html_text: str,
) -> int:

    soup = BeautifulSoup(
        html_text,
        "html.parser",
    )

    page_numbers = set()

    for link in soup.select(
        "ul.pagination a"
    ):

        text_value = clean_text(
            link.get_text()
        )

        if text_value.isdigit():
            page_numbers.add(
                int(text_value)
            )

        silver = link.get(
            "data-silver",
            "",
        )

        decoded = decode_data_silver(
            silver
        )

        match = re.search(
            r"[?&]page=(\d+)",
            decoded,
        )

        if match:
            page_numbers.add(
                int(
                    match.group(1)
                )
            )

    if not page_numbers:
        return 1

    return max(
        page_numbers
    )


# ============================================================
# Checkpoint
# ============================================================

def checkpoint_path_for(
    output_csv: Path,
) -> Path:

    return Path(
        str(output_csv)
        + CHECKPOINT_SUFFIX
    )


def load_checkpoint(
    path: Path,
) -> int:

    if not path.exists():
        return 0

    try:

        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        return int(
            data.get(
                "last_completed_page",
                0,
            )
        )

    except Exception:
        return 0


def save_checkpoint(
    path: Path,
    page_number: int,
):

    path.write_text(
        json.dumps(
            {
                "last_completed_page":
                    page_number
            },
            indent=2,
        ),
        encoding="utf-8",
    )


# ============================================================
# CSV output
# ============================================================

OUTPUT_COLUMNS = [
    "RunnerID",
    "BibNumber",
    "CountryCode",
    "AgeGroup",
    "Club",
    "Place",
    "PlaceAgeGroup",
    "GunTime",
    "Finish",
    "SummaryStatus",
    "DetailUrl",
]


def existing_runner_ids(
    output_csv: Path,
) -> set[str]:

    if not output_csv.exists():
        return set()

    ids = set()

    with output_csv.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:

        reader = csv.DictReader(
            file
        )

        for row in reader:

            runner_id = clean_text(
                row.get(
                    "RunnerID",
                    ""
                )
            )

            if runner_id:
                ids.add(
                    runner_id
                )

    return ids


def append_rows(
    output_csv: Path,
    rows: list[dict],
    seen_ids: set[str],
) -> int:

    new_rows = []

    for row in rows:

        runner_id = row[
            "RunnerID"
        ]

        if runner_id in seen_ids:
            continue

        new_rows.append(
            row
        )

        seen_ids.add(
            runner_id
        )

    if not new_rows:
        return 0

    file_exists = (
        output_csv.exists()
        and output_csv.stat().st_size > 0
    )

    with output_csv.open(
        "a",
        encoding="utf-8-sig",
        newline="",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=OUTPUT_COLUMNS,
        )

        if not file_exists:
            writer.writeheader()

        writer.writerows(
            new_rows
        )

    return len(
        new_rows
    )


# ============================================================
# Main scraper
# ============================================================

def run(
    args,
):

    output_csv = Path(
        args.output
    )

    checkpoint_path = (
        checkpoint_path_for(
            output_csv
        )
    )

    seen_ids = existing_runner_ids(
        output_csv
    )

    last_checkpoint = (
        load_checkpoint(
            checkpoint_path
        )
        if args.resume
        else 0
    )

    session = create_session()

    print(
        "Fetching page 1 "
        "to detect pagination..."
    )

    first_html = fetch_page(
        session,
        1,
        args.timeout,
    )

    detected_last_page = (
        detect_last_page(
            first_html
        )
    )

    if args.max_pages:
        last_page = min(
            detected_last_page,
            args.max_pages,
        )
    else:
        last_page = (
            detected_last_page
        )

    start_page = max(
        1,
        last_checkpoint + 1,
    )

    print()
    print(
        f"Detected last page: "
        f"{detected_last_page:,}"
    )

    print(
        f"Starting page:      "
        f"{start_page:,}"
    )

    print(
        f"Ending page:        "
        f"{last_page:,}"
    )

    print(
        f"Delay:              "
        f"{args.delay:.2f} sec/page"
    )

    print()

    total_rows_seen = 0
    total_finished = 0
    total_dsq = 0
    total_no_finish = 0
    total_other = 0
    total_saved = 0

    started = time.monotonic()

    for page_number in range(
        start_page,
        last_page + 1,
    ):

        try:

            if page_number == 1:
                page_html = first_html
            else:
                page_html = fetch_page(
                    session,
                    page_number,
                    args.timeout,
                )

        except PermissionError:

            print()
            print(
                "=" * 65
            )

            print(
                f"HTTP 403 received "
                f"on page {page_number:,}."
            )

            print(
                "Stopping immediately."
            )

            print(
                "The last successfully "
                "completed page is saved "
                "in the checkpoint."
            )

            print(
                "=" * 65
            )

            return

        except requests.RequestException as exc:

            print()
            print(
                f"Request error on "
                f"page {page_number}: "
                f"{exc}"
            )

            print(
                "Stopping. Run again "
                "with --resume to continue."
            )

            return

        parsed_rows = parse_page(
            page_html
        )

        total_rows_seen += len(
            parsed_rows
        )

        exceptional_rows = []

        for row in parsed_rows:

            status = row[
                "SummaryStatus"
            ]

            if status == "FINISHED":

                total_finished += 1

                # Normal finisher:
                # intentionally not written.
                continue

            if status == "DSQ":
                total_dsq += 1

            elif status == "NO_FINISH":
                total_no_finish += 1

            else:
                total_other += 1

            exceptional_rows.append(
                row
            )

        saved = append_rows(
            output_csv,
            exceptional_rows,
            seen_ids,
        )

        total_saved += saved

        save_checkpoint(
            checkpoint_path,
            page_number,
        )

        elapsed = (
            time.monotonic()
            - started
        )

        processed_pages = (
            page_number
            - start_page
            + 1
        )

        rate = (
            processed_pages / elapsed
            if elapsed > 0
            else 0
        )

        pages_left = (
            last_page
            - page_number
        )

        eta_minutes = (
            pages_left / rate / 60
            if rate > 0
            else 0
        )

        print(
            f"Page "
            f"{page_number:,}/"
            f"{last_page:,}"
            f" | rows {total_rows_seen:,}"
            f" | finished skipped "
            f"{total_finished:,}"
            f" | DSQ {total_dsq:,}"
            f" | no finish "
            f"{total_no_finish:,}"
            f" | other {total_other:,}"
            f" | saved {total_saved:,}"
            f" | ETA "
            f"{eta_minutes:.1f} min"
        )

        if (
            page_number
            < last_page
        ):

            time.sleep(
                args.delay
            )

    print()
    print(
        "=" * 65
    )

    print(
        "SUMMARY SCRAPE COMPLETE"
    )

    print(
        "=" * 65
    )

    print(
        f"Rows inspected:     "
        f"{total_rows_seen:,}"
    )

    print(
        f"Finishers skipped:  "
        f"{total_finished:,}"
    )

    print(
        f"DSQ found:          "
        f"{total_dsq:,}"
    )

    print(
        f"No finish found:    "
        f"{total_no_finish:,}"
    )

    print(
        f"Other statuses:     "
        f"{total_other:,}"
    )

    print(
        f"Exceptional saved:  "
        f"{len(seen_ids):,}"
    )

    print()
    print(
        f"Output:"
    )

    print(
        f"  "
        f"{output_csv.resolve()}"
    )

    print()
    print(
        "Next step:"
    )

    print(
        "  Run detail-page extraction "
        "only for SummaryStatus=NO_FINISH "
        "or OTHER."
    )

    print(
        "=" * 65
    )


# ============================================================
# CLI
# ============================================================

def build_parser():

    parser = argparse.ArgumentParser(
        description=(
            "Scan Berlin Marathon 2026 "
            "summary result pages and "
            "save only exceptional runners "
            "(DSQ/no finish/other)."
        )
    )

    parser.add_argument(
        "--output",
        default=(
            "exceptional_runners_2026.csv"
        ),
        help=(
            "Output CSV. Default: "
            "exceptional_runners_2026.csv"
        ),
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help=(
            "Seconds between summary-page "
            "requests. Default: 1.0"
        ),
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=60,
        help=(
            "HTTP timeout in seconds. "
            "Default: 60"
        ),
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help=(
            "Optional page limit for testing."
        ),
    )

    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Resume from the saved "
            "page checkpoint."
        ),
    )

    return parser


def main():

    parser = build_parser()

    args = parser.parse_args()

    if args.delay < 0:
        parser.error(
            "--delay cannot be negative"
        )

    if args.timeout <= 0:
        parser.error(
            "--timeout must be positive"
        )

    if (
        args.max_pages is not None
        and args.max_pages < 1
    ):
        parser.error(
            "--max-pages must be >= 1"
        )

    try:

        run(args)

    except KeyboardInterrupt:

        print()
        print(
            "Interrupted."
        )

        print(
            "Your completed-page "
            "checkpoint has been retained."
        )

        print(
            "Run again with --resume "
            "to continue."
        )


if __name__ == "__main__":
    main()