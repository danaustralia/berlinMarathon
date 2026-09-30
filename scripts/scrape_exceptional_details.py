
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://berlin.r.mikatiming.com/2026/"
EVENT_ID = "BML_HCH3C0OH37C"

# Split order matters for LastSplit.
SPLITS = [
    ("5km", 5.0),
    ("10km", 10.0),
    ("15km", 15.0),
    ("20km", 20.0),
    ("Halb", 21.0975),
    ("25km", 25.0),
    ("30km", 30.0),
    ("35km", 35.0),
    ("40km", 40.0),
    ("Finish", 42.195),
]

CHECKPOINT_SUFFIX = ".checkpoint.json"


# ============================================================
# Basic helpers
# ============================================================

def clean_text(value: str | None) -> str:
    if not value:
        return ""

    value = (
        value
        .replace("\xa0", " ")
        .replace("–", "-")
        .replace("—", "-")
        .strip()
    )

    return re.sub(
        r"\s+",
        " ",
        value,
    )


def normalize_empty(value: str | None) -> str:
    value = clean_text(value)

    if value in {
        "",
        "-",
    }:
        return ""

    return value


def build_detail_url(
    runner_id: str,
) -> str:

    return (
        f"{BASE_URL}"
        f"?content=detail"
        f"&fpid=search"
        f"&pid=search"
        f"&idp={runner_id}"
        f"&lang=EN_CAP"
        f"&event={EVENT_ID}"
        f"&pidp=start"
        f"&search_event={EVENT_ID}"
    )


# ============================================================
# HTTP session
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
            "Connection": "keep-alive",
        }
    )

    return session


# ============================================================
# Fetch detail page
# ============================================================

def fetch_detail(
    session: requests.Session,
    runner_id: str,
    timeout: float,
    max_retries: int,
) -> str:

    url = build_detail_url(
        runner_id
    )

    last_error = None

    for attempt in range(
        1,
        max_retries + 1,
    ):

        try:

            response = session.get(
                url,
                timeout=timeout,
                allow_redirects=True,
                headers={
                    "Referer": BASE_URL,
                },
            )

            if response.status_code == 403:

                raise PermissionError(
                    "HTTP 403 Forbidden"
                )

            if response.status_code == 200:

                if not response.text:
                    raise RuntimeError(
                        "Empty response"
                    )

                return response.text

            if response.status_code in {
                408,
                425,
                429,
                500,
                502,
                503,
                504,
            }:

                last_error = (
                    f"HTTP "
                    f"{response.status_code}"
                )

                if attempt < max_retries:

                    wait_seconds = min(
                        30,
                        (2 ** (attempt - 1))
                        + random.uniform(
                            0,
                            0.5,
                        ),
                    )

                    time.sleep(
                        wait_seconds
                    )

                    continue

            raise RuntimeError(
                f"HTTP "
                f"{response.status_code}"
            )

        except PermissionError:
            raise

        except (
            requests.Timeout,
            requests.ConnectionError,
        ) as exc:

            last_error = str(exc)

            if attempt >= max_retries:
                break

            wait_seconds = min(
                30,
                (2 ** (attempt - 1))
                + random.uniform(
                    0,
                    0.5,
                ),
            )

            time.sleep(
                wait_seconds
            )

    raise RuntimeError(
        f"Request failed after "
        f"{max_retries} attempts: "
        f"{last_error}"
    )


# ============================================================
# HTML helpers
# ============================================================

def node_text(
    soup: BeautifulSoup,
    selector: str,
) -> str:

    node = soup.select_one(
        selector
    )

    if node is None:
        return ""

    return normalize_empty(
        node.get_text(
            " ",
            strip=True,
        )
    )


def parse_split_table(
    soup: BeautifulSoup,
) -> dict[str, str]:

    result = {}

    rows = soup.select(
        '#detail-box-splits '
        'table tbody tr'
    )

    for row in rows:

        cells = row.select(
            ":scope > th, :scope > td"
        )

        values = [
            normalize_empty(
                cell.get_text(
                    " ",
                    strip=True,
                )
            )
            for cell in cells
        ]

        if len(values) < 6:
            continue

        split_name = (
            values[0]
            .replace(" ", "")
        )

        # Normalize possible variations.
        split_lookup = {
            "5km": "5km",
            "10km": "10km",
            "15km": "15km",
            "20km": "20km",
            "Half": "Halb",
            "Halb": "Halb",
            "HM": "Halb",
            "25km": "25km",
            "30km": "30km",
            "35km": "35km",
            "40km": "40km",
            "Finish": "Finish",
        }

        canonical = split_lookup.get(
            split_name,
            split_name,
        )

        result[
            f"{canonical}TimeOfDay"
        ] = values[1]

        result[
            f"{canonical}Time"
        ] = values[2]

        result[
            f"{canonical}Diff"
        ] = values[3]

        result[
            f"{canonical}MinPerKm"
        ] = values[4]

        result[
            f"{canonical}KmPerHour"
        ] = values[5]

    return result


# ============================================================
# Detail page parsing
# ============================================================

def parse_detail_page(
    runner_id: str,
    html_text: str,
) -> dict[str, str]:

    soup = BeautifulSoup(
        html_text,
        "html.parser",
    )

    record = {
        "RunnerID": runner_id,

        "Name": node_text(
            soup,
            'td.f-__fullname'
        ),

        "Club": node_text(
            soup,
            'td.f-club'
        ),

        "BibNumber": node_text(
            soup,
            'td.f-start_no_text'
        ),

        "AgeGroup": node_text(
            soup,
            'td.f-age_class_desc'
        ),

        "PlaceMWD": node_text(
            soup,
            'td.f-place_all'
        ),

        "PlaceG": node_text(
            soup,
            'td.f-place_age'
        ),

        "PlaceTotal": node_text(
            soup,
            'td.f-place_nosex'
        ),

        "TimeTotal": node_text(
            soup,
            'td.f-time_finish_netto'
        ),

        "FinishGun": node_text(
            soup,
            'td.f-time_finish_brutto'
        ),
    }

    split_data = parse_split_table(
        soup
    )

    record.update(
        split_data
    )

    return record


# ============================================================
# Status inference
# ============================================================

def has_valid_split(
    record: dict,
    split_name: str,
) -> bool:

    value = normalize_empty(
        record.get(
            f"{split_name}Time",
            ""
        )
    )

    if not value:
        return False

    if value.upper() in {
        "DSQ",
        "DNS",
        "DNF",
    }:
        return False

    return True


def derive_last_split(
    record: dict,
) -> tuple[str, float | None]:

    last_split = ""
    distance = None

    for split_name, km in SPLITS:

        if has_valid_split(
            record,
            split_name,
        ):

            last_split = split_name
            distance = km

    return (
        last_split,
        distance,
    )


def infer_status(
    summary_status: str,
    record: dict,
) -> tuple[
    str,
    str,
    str,
    float | None,
]:

    summary_status = (
        normalize_empty(
            summary_status
        )
        .upper()
    )

    # DSQ came directly from the official summary page.
    if summary_status == "DSQ":

        return (
            "DSQ",
            "DSQ",
            "",
            None,
        )

    last_split, distance = (
        derive_last_split(
            record
        )
    )

    finish_time = normalize_empty(
        record.get(
            "FinishTime",
            ""
        )
    )

    time_total = normalize_empty(
        record.get(
            "TimeTotal",
            ""
        )
    )

    # Unexpected case: detail page actually has a finish.
    if (
        finish_time
        or re.fullmatch(
            r"\d{1,2}:\d{2}:\d{2}",
            time_total,
        )
    ):

        return (
            "Finished",
            "Finished",
            "Finish",
            42.195,
        )

    # Any actual checkpoint proves the runner
    # had timing activity during the race.
    if last_split:

        return (
            "DNF",
            "DNF",
            last_split,
            distance,
        )

    # No timing evidence.
    #
    # Do not call this DNS automatically,
    # because absence of timing data alone
    # is not enough to prove DNS.
    return (
        "NO_TIMING_DATA",
        "DNS_CANDIDATE",
        "",
        0.0,
    )


# ============================================================
# Input
# ============================================================

def read_exceptional_file(
    path: Path,
) -> list[dict]:

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:

        reader = csv.DictReader(
            file
        )

        if not reader.fieldnames:

            raise RuntimeError(
                "Input CSV has no headers."
            )

        required = {
            "RunnerID",
            "SummaryStatus",
        }

        missing = (
            required
            - set(reader.fieldnames)
        )

        if missing:

            raise RuntimeError(
                "Missing required columns: "
                + ", ".join(
                    sorted(missing)
                )
            )

        return list(
            reader
        )


# ============================================================
# Checkpoint / existing output
# ============================================================

def load_existing(
    output_path: Path,
) -> dict[str, dict]:

    records = {}

    if not output_path.exists():
        return records

    with output_path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:

        reader = csv.DictReader(
            file
        )

        for row in reader:

            runner_id = normalize_empty(
                row.get(
                    "RunnerID",
                    ""
                )
            )

            if runner_id:

                records[
                    runner_id
                ] = row

    return records


# ============================================================
# Output headers
# ============================================================

BASE_OUTPUT_COLUMNS = [
    "RunnerID",
    "SummaryStatus",
    "RaceStatus",
    "Status",
    "LastSplit",
    "DistanceCompletedKm",

    "BibNumber",
    "AgeGroup",
    "CountryCode",
    "Club",

    "Place",
    "PlaceAgeGroup",

    "GunTime",
    "Finish",

    "DetailUrl",

    "PlaceMWD",
    "PlaceG",
    "PlaceTotal",

    "TimeTotal",
    "FinishGun",
]


SPLIT_OUTPUT_COLUMNS = []

for split_name, _ in SPLITS:

    SPLIT_OUTPUT_COLUMNS.extend(
        [
            f"{split_name}TimeOfDay",
            f"{split_name}Time",
            f"{split_name}Diff",
            f"{split_name}MinPerKm",
            f"{split_name}KmPerHour",
        ]
    )


OUTPUT_COLUMNS = (
    BASE_OUTPUT_COLUMNS
    + SPLIT_OUTPUT_COLUMNS
    + [
        "Error",
    ]
)


# ============================================================
# Write one row immediately
# ============================================================

def append_output(
    output_path: Path,
    record: dict,
):

    exists = (
        output_path.exists()
        and output_path.stat().st_size > 0
    )

    with output_path.open(
        "a",
        encoding="utf-8-sig",
        newline="",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=OUTPUT_COLUMNS,
            extrasaction="ignore",
        )

        if not exists:

            writer.writeheader()

        writer.writerow(
            record
        )


# ============================================================
# Build DSQ output without detail request
# ============================================================

def build_dsq_record(
    source: dict,
) -> dict:

    record = {
        key: source.get(
            key,
            ""
        )
        for key in OUTPUT_COLUMNS
    }

    record["RaceStatus"] = "DSQ"
    record["Status"] = "DSQ"
    record["LastSplit"] = ""
    record["DistanceCompletedKm"] = ""

    return record


# ============================================================
# Merge source + detail data
# ============================================================

def build_detail_record(
    source: dict,
    detail: dict,
) -> dict:

    record = {
        key: ""
        for key in OUTPUT_COLUMNS
    }

    # First copy source summary data.
    for key, value in source.items():

        if key in record:

            record[key] = value

    # Then enrich from detail page.
    for key, value in detail.items():

        if (
            key in record
            and value not in {
                "",
                None,
            }
        ):

            record[key] = value

    (
        race_status,
        status,
        last_split,
        distance,
    ) = infer_status(
        source.get(
            "SummaryStatus",
            ""
        ),
        detail,
    )

    record["RaceStatus"] = (
        race_status
    )

    record["Status"] = (
        status
    )

    record["LastSplit"] = (
        last_split
    )

    record[
        "DistanceCompletedKm"
    ] = (
        ""
        if distance is None
        else distance
    )

    return record


# ============================================================
# Main
# ============================================================

def run(args):

    input_path = Path(
        args.input
    )

    output_path = Path(
        args.output
    )

    if not input_path.exists():

        raise RuntimeError(
            f"Input file not found: "
            f"{input_path}"
        )

    source_rows = (
        read_exceptional_file(
            input_path
        )
    )

    existing = load_existing(
        output_path
    )

    print()
    print(
        f"Exceptional runners: "
        f"{len(source_rows):,}"
    )

    print(
        f"Already processed:   "
        f"{len(existing):,}"
    )

    remaining = [
        row
        for row in source_rows
        if normalize_empty(
            row.get(
                "RunnerID",
                ""
            )
        )
        not in existing
    ]

    print(
        f"Remaining:           "
        f"{len(remaining):,}"
    )

    if not remaining:

        print(
            "Nothing left to process."
        )

        return

    session = create_session()

    counters = {
        "DSQ": 0,
        "DNF": 0,
        "NO_TIMING_DATA": 0,
        "Finished": 0,
        "Error": 0,
    }

    requests_made = 0

    started = time.monotonic()

    for index, source in enumerate(
        remaining,
        start=1,
    ):

        runner_id = normalize_empty(
            source.get(
                "RunnerID",
                ""
            )
        )

        summary_status = (
            normalize_empty(
                source.get(
                    "SummaryStatus",
                    ""
                )
            )
            .upper()
        )

        if not runner_id:

            continue

        # ----------------------------------------------------
        # DSQ: summary page is already authoritative
        # ----------------------------------------------------

        if summary_status == "DSQ":

            record = build_dsq_record(
                source
            )

            append_output(
                output_path,
                record,
            )

            counters["DSQ"] += 1

        else:

            try:

                detail_html = fetch_detail(
                    session,
                    runner_id,
                    args.timeout,
                    args.max_retries,
                )

                requests_made += 1

                detail = parse_detail_page(
                    runner_id,
                    detail_html,
                )

                record = build_detail_record(
                    source,
                    detail,
                )

                append_output(
                    output_path,
                    record,
                )

                status = record[
                    "RaceStatus"
                ]

                if status in counters:
                    counters[status] += 1
                else:
                    counters[
                        "NO_TIMING_DATA"
                    ] += 1

            except PermissionError:

                print()
                print(
                    "=" * 68
                )

                print(
                    f"HTTP 403 on runner "
                    f"{runner_id}."
                )

                print(
                    "Stopping immediately."
                )

                print(
                    "All previous runners "
                    "are already saved."
                )

                print(
                    "Run the same command "
                    "again later to resume."
                )

                print(
                    "=" * 68
                )

                return

            except Exception as exc:

                record = {
                    key: source.get(
                        key,
                        ""
                    )
                    for key
                    in OUTPUT_COLUMNS
                }

                record["Error"] = str(
                    exc
                )

                append_output(
                    output_path,
                    record,
                )

                counters["Error"] += 1

        # ----------------------------------------------------
        # Progress
        # ----------------------------------------------------

        processed = index

        elapsed = (
            time.monotonic()
            - started
        )

        rate = (
            processed / elapsed
            if elapsed > 0
            else 0
        )

        left = (
            len(remaining)
            - processed
        )

        eta = (
            left / rate / 60
            if rate > 0
            else 0
        )

        if (
            processed % 25 == 0
            or processed
            == len(remaining)
        ):

            print(
                f"{processed:,}/"
                f"{len(remaining):,}"
                f" | requests "
                f"{requests_made:,}"
                f" | DSQ "
                f"{counters['DSQ']:,}"
                f" | DNF "
                f"{counters['DNF']:,}"
                f" | no timing "
                f"{counters['NO_TIMING_DATA']:,}"
                f" | errors "
                f"{counters['Error']:,}"
                f" | ETA "
                f"{eta:.1f} min"
            )

        # No delay is needed for DSQ because
        # no HTTP request was made.
        if (
            summary_status != "DSQ"
            and index
            < len(remaining)
        ):

            time.sleep(
                args.delay
            )

    print()
    print(
        "=" * 68
    )

    print(
        "EXCEPTIONAL DETAIL "
        "SCRAPE COMPLETE"
    )

    print(
        "=" * 68
    )

    print(
        f"DSQ:             "
        f"{counters['DSQ']:,}"
    )

    print(
        f"DNF:             "
        f"{counters['DNF']:,}"
    )

    print(
        f"No timing data:  "
        f"{counters['NO_TIMING_DATA']:,}"
    )

    print(
        f"Unexpected finish:"
        f" {counters['Finished']:,}"
    )

    print(
        f"Errors:          "
        f"{counters['Error']:,}"
    )

    print(
        f"Detail requests: "
        f"{requests_made:,}"
    )

    print()
    print(
        f"Output:"
    )

    print(
        f"  "
        f"{output_path.resolve()}"
    )

    print(
        "=" * 68
    )


# ============================================================
# CLI
# ============================================================

def build_parser():

    parser = argparse.ArgumentParser(
        description=(
            "Fetch detail pages only for "
            "Berlin Marathon 2026 exceptional "
            "runners."
        )
    )

    parser.add_argument(
        "--input",
        default=(
            "exceptional_runners_2026.csv"
        ),
        help=(
            "Input exceptional runner CSV."
        ),
    )

    parser.add_argument(
        "--output",
        default=(
            "exceptional_runners_2026_details.csv"
        ),
        help=(
            "Output detail CSV."
        ),
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help=(
            "Seconds between detail requests. "
            "Default: 1.0"
        ),
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=60,
        help=(
            "Request timeout. Default: 60"
        ),
    )

    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help=(
            "Retries for transient errors. "
            "Default: 3"
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

    if args.max_retries < 1:
        parser.error(
            "--max-retries must be >= 1"
        )

    try:

        run(args)

    except KeyboardInterrupt:

        print()
        print(
            "Interrupted."
        )

        print(
            "Completed runners have already "
            "been written to the output CSV."
        )

        print(
            "Run the same command again "
            "to resume automatically."
        )


if __name__ == "__main__":
    main()