
from __future__ import annotations

import csv
import sys
from pathlib import Path


FINISHERS_FILE = Path("BM_export_2026_finishers.csv")
EXCEPTIONAL_FILE = Path("exceptional_runners_2026_details.csv")
OUTPUT_FILE = Path("BM_export_2026.csv")


# These fields will NEVER be written to the final merged file.
IDENTIFIABLE_COLUMNS = {
    "RunnerID",
    "Name",
    "BibNumber",
    "Club",
    "DetailUrl",
}


def clean(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        reader = csv.DictReader(f)

        if not reader.fieldnames:
            raise RuntimeError(f"No headers found in {path}")

        rows = list(reader)

    return list(reader.fieldnames), rows


def remove_identifiers(row: dict) -> dict:
    return {
        key: value
        for key, value in row.items()
        if key not in IDENTIFIABLE_COLUMNS
    }


def normalize_finisher(row: dict) -> dict:
    result = remove_identifiers(row)

    if not clean(result.get("RaceStatus")):
        result["RaceStatus"] = "Finished"

    if not clean(result.get("Status")):
        result["Status"] = "Finished"

    if not clean(result.get("LastSplit")):
        result["LastSplit"] = "Finish"

    if not clean(result.get("DistanceCompletedKm")):
        result["DistanceCompletedKm"] = "42.195"

    return result


def normalize_exceptional(row: dict) -> dict:
    result = remove_identifiers(row)

    race_status = clean(
        result.get("RaceStatus")
    )

    if not race_status:
        raise RuntimeError(
            "Exceptional record found without RaceStatus."
        )

    if not clean(result.get("Status")):
        result["Status"] = race_status

    return result


def ordered_union(*header_lists: list[str]) -> list[str]:
    output = []
    seen = set()

    for headers in header_lists:
        for header in headers:

            if header in IDENTIFIABLE_COLUMNS:
                continue

            if header not in seen:
                seen.add(header)
                output.append(header)

    required = [
        "RaceStatus",
        "Status",
        "LastSplit",
        "DistanceCompletedKm",
    ]

    for field in required:
        if field not in seen:
            output.append(field)
            seen.add(field)

    return output


def status_summary(
    rows: list[dict],
) -> dict[str, int]:

    counts = {}

    for row in rows:

        status = (
            clean(row.get("RaceStatus"))
            or "UNKNOWN"
        )

        counts[status] = (
            counts.get(status, 0) + 1
        )

    return counts


def main():

    print()
    print("=" * 68)
    print("BERLIN MARATHON 2026 PRIVACY-SAFE MERGE")
    print("=" * 68)

    (
        finish_headers,
        finish_rows,
    ) = read_csv(
        FINISHERS_FILE
    )

    (
        exceptional_headers,
        exceptional_rows,
    ) = read_csv(
        EXCEPTIONAL_FILE
    )

    print(
        f"Finisher rows:       "
        f"{len(finish_rows):,}"
    )

    print(
        f"Exceptional rows:    "
        f"{len(exceptional_rows):,}"
    )

    # --------------------------------------------------------
    # Normalize both datasets
    # --------------------------------------------------------

    finishers = [
        normalize_finisher(row)
        for row in finish_rows
    ]

    exceptional = [
        normalize_exceptional(row)
        for row in exceptional_rows
    ]

    # --------------------------------------------------------
    # Build combined header
    # --------------------------------------------------------

    headers = ordered_union(
        finish_headers,
        exceptional_headers,
    )

    # --------------------------------------------------------
    # Merge
    #
    # No RunnerID join is required because the exceptional
    # scraper only selected runners whose Finish was NOT
    # a valid time.
    # --------------------------------------------------------

    combined = (
        finishers
        + exceptional
    )

    # --------------------------------------------------------
    # Privacy validation
    # --------------------------------------------------------

    bad_headers = [
        h
        for h in headers
        if h in IDENTIFIABLE_COLUMNS
    ]

    if bad_headers:
        raise RuntimeError(
            "Privacy check failed. "
            "Identifying columns remain: "
            + ", ".join(bad_headers)
        )

    # --------------------------------------------------------
    # Write merged output
    # --------------------------------------------------------

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=headers,
            extrasaction="ignore",
        )

        writer.writeheader()

        for row in combined:

            writer.writerow(
                {
                    field:
                    row.get(field, "")
                    for field
                    in headers
                }
            )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    counts = status_summary(
        combined
    )

    total = len(combined)

    finished = counts.get(
        "Finished",
        0,
    )

    finish_rate = (
        finished
        / total
        * 100
        if total
        else 0
    )

    print()
    print("-" * 68)
    print("FINAL DATASET")
    print("-" * 68)

    print(
        f"Total rows:          "
        f"{total:,}"
    )

    print()
    print("RaceStatus:")

    for status, count in sorted(
        counts.items(),
        key=lambda item: (
            -item[1],
            item[0],
        ),
    ):

        pct = (
            count
            / total
            * 100
            if total
            else 0
        )

        print(
            f"  {status:<22}"
            f"{count:>8,}"
            f"   "
            f"{pct:>6.2f}%"
        )

    print()

    print(
        f"Finished:            "
        f"{finished:,}"
    )

    print(
        f"Non-finished:        "
        f"{total - finished:,}"
    )

    print(
        f"Dataset finish rate: "
        f"{finish_rate:.2f}%"
    )

    # --------------------------------------------------------
    # Expected-count checks
    # --------------------------------------------------------

    expected_finishers = 50063
    expected_dnf = 836
    expected_dsq = 95
    expected_no_timing = 329
    expected_total = 51323

    print()
    print("Expected-count checks:")

    checks = [
        (
            "Finished",
            counts.get("Finished", 0),
            expected_finishers,
        ),
        (
            "DNF",
            counts.get("DNF", 0),
            expected_dnf,
        ),
        (
            "DSQ",
            counts.get("DSQ", 0),
            expected_dsq,
        ),
        (
            "NO_TIMING_DATA",
            counts.get(
                "NO_TIMING_DATA",
                0,
            ),
            expected_no_timing,
        ),
        (
            "TOTAL",
            total,
            expected_total,
        ),
    ]

    all_ok = True

    for label, actual, expected in checks:

        ok = (
            actual == expected
        )

        if not ok:
            all_ok = False

        mark = (
            "OK"
            if ok
            else "CHECK"
        )

        print(
            f"  {label:<20}"
            f"{actual:>8,}"
            f" / expected "
            f"{expected:>8,}"
            f"   {mark}"
        )

    # --------------------------------------------------------
    # Final privacy check
    # --------------------------------------------------------

    print()
    print("Privacy check:")

    identifying_found = [
        col
        for col in IDENTIFIABLE_COLUMNS
        if col in headers
    ]

    if identifying_found:

        print(
            "FAILED: "
            + ", ".join(
                identifying_found
            )
        )

        sys.exit(1)

    else:

        print(
            "PASS - no RunnerID, Name, "
            "BibNumber, Club or DetailUrl "
            "columns in final file."
        )

    print()

    if all_ok:

        print(
            "All expected counts match."
        )

    else:

        print(
            "One or more counts differ. "
            "Review before using the file."
        )

    print()

    print(
        f"Created:"
    )

    print(
        f"  "
        f"{OUTPUT_FILE.resolve()}"
    )

    print("=" * 68)


if __name__ == "__main__":

    try:
        main()

    except Exception as exc:

        print()
        print(
            f"ERROR: {exc}"
        )

        sys.exit(1)