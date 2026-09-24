#!/usr/bin/env python3
"""香港公众假期 ICS 生成：读取 data/hk/*.json，产出 reddays-hk.ics。"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from paths import workspace_path  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from hkholiday import load_years  # noqa: E402
from generate import CalendarWriter, UID_DOMAIN  # noqa: E402


def load_days() -> list[dict]:
    days = []
    for year in load_years():
        with open(workspace_path("data", "hk", f"{year}.json"), encoding="utf-8") as f:
            days.extend(json.load(f)["days"])
    days.sort(key=lambda d: d["date"])
    return days


def build_events(days):
    events = []
    for day in days:
        date = dt.date.fromisoformat(day["date"])
        desc_lines = [f"官方繁体：{day['name_zh_hk']}" if day["name_zh_hk"] != day["name"] else ""]
        desc_lines.append("依据香港特区政府公布的公众假期名单（1823）")
        desc = "\n".join(x for x in desc_lines if x)
        events.append((date, f"{date.strftime('%Y%m%d')}-off-hk@{UID_DOMAIN}",
                       day["name"], desc))
    return events


def render(events) -> str:
    writer = CalendarWriter(calname="香港公众假期", tz="Asia/Hong_Kong", color="#7BA7D9")
    for date, uid, summary, desc in events:
        nxt = (date + dt.timedelta(days=1)).strftime("%Y%m%d")
        writer.lines.append("BEGIN:VEVENT")
        writer.add(f"UID:{uid}")
        writer.add(f"DTSTAMP:{date.strftime('%Y%m%d')}T000000Z")
        writer.add("SEQUENCE:0")
        writer.add(f"DTSTART;VALUE=DATE:{date.strftime('%Y%m%d')}")
        writer.add(f"DTEND;VALUE=DATE:{nxt}")
        writer.add("TRANSP:TRANSPARENT")
        writer.add(f"SUMMARY:{summary}")
        if desc:
            writer.add(f"DESCRIPTION:{desc}")
        writer.lines.append("END:VEVENT")
    return writer.render()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=workspace_path("dist"))
    args = parser.parse_args()
    events = build_events(load_days())
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, "reddays-hk.ics")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(render(events))
    print(f"generated: {path}")


if __name__ == "__main__":
    main()
