#!/usr/bin/env python3
"""Cross-check generated holiday data against Apple's official cn_zh calendar.

Apple's calendar marks holiday first-days with （休） and makeup workdays with
（班）. Assertions (per checked year, default: current year):
  1. workday sets are identical
  2. Apple's off-day set is a subset of ours (Apple omits non-first days)

Exit code 1 on any mismatch - this is a publish gate.
"""

import argparse
import datetime as dt
import gzip
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from paths import workspace_path  # noqa: E402

APPLE_URL = "https://calendars.icloud.com/holidays/cn_zh.ics"


def fetch_apple_ics() -> str:
    req = urllib.request.Request(APPLE_URL, headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8")


def parse_events(text: str):
    """Return {date: summary} from an ICS text, unfolding folded lines."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    unfolded = []
    for line in text.split("\n"):
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    events = {}
    date = None
    summary = ""
    for line in unfolded:
        if line == "BEGIN:VEVENT":
            date, summary = None, ""
        elif line.startswith("DTSTART"):
            value = line.split(":", 1)[-1].strip()
            m = re.match(r"(\d{4})(\d{2})(\d{2})", value)
            if m:
                date = "-".join(m.groups())
        elif line.startswith("SUMMARY"):
            summary = line.split(":", 1)[-1].strip()
        elif line == "END:VEVENT" and date:
            events[date] = summary
    return events


def classify(summary: str):
    if "（休）" in summary or "(休)" in summary:
        return "off"
    if "（班）" in summary or "(班)" in summary:
        return "work"
    return None


def load_our_days() -> dict:
    ours = {}
    data_dir = workspace_path("data")
    for name in sorted(os.listdir(data_dir)):
        if not re.match(r"\d{4}\.json$", name):
            continue
        with open(os.path.join(data_dir, name), encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("days", []):
            ours.setdefault(item["date"], item)
    return ours


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=None)
    args = parser.parse_args()
    year = args.year or dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).year

    apple = {
        date: classify(summary)
        for date, summary in parse_events(fetch_apple_ics()).items()
        if date.startswith(str(year))
    }
    apple_off = {d for d, k in apple.items() if k == "off"}
    apple_work = {d for d, k in apple.items() if k == "work"}

    ours = {
        date: item
        for date, item in load_our_days().items()
        if date.startswith(str(year))
    }
    our_off = {d for d, i in ours.items() if i["isOffDay"]}
    our_work = {d for d, i in ours.items() if not i["isOffDay"]}

    print(f"cross-check year {year}:")
    print(f"  apple: off={len(apple_off)} work={sorted(apple_work)}")
    print(f"  ours : off={len(our_off)} work={sorted(our_work)}")

    if not apple_off and not apple_work:
        print("  SKIP: Apple calendar has no marked days for this year yet")
        return 0

    errors = []
    if apple_work != our_work:
        errors.append(
            f"workday mismatch: apple-only={sorted(apple_work - our_work)} "
            f"ours-only={sorted(our_work - apple_work)}"
        )
    missing = apple_off - our_off
    if missing:
        errors.append(f"offdays missing in ours: {sorted(missing)}")

    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        return 1
    print("  PASS: workdays identical, offdays superset OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
