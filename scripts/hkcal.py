#!/usr/bin/env python3
"""香港公众假期 ICS 生成：读取 data/hk/*.json，产出简繁两版。

- reddays-hk.ics：简体标题与描述（reddays-hk-tc.ics 为繁体标题与描述）
两版 UID 不同，可同时订阅；每版的文字整体保持同一种语言。
"""

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

# variant -> (文件名, 日历名, 标题字段, 来源说明)
VARIANTS = {
    "sc": ("reddays-hk.ics", "香港公众假期", "name", "依据香港特区政府公布的公众假期名单（1823）"),
    "tc": (
        "reddays-hk-tc.ics",
        "香港公眾假期",
        "name_zh_hk",
        "依據香港特區政府公布的公眾假期名單（1823）",
    ),
}


def load_days() -> list[dict]:
    days = []
    for year in load_years():
        with open(workspace_path("data", "hk", f"{year}.json"), encoding="utf-8") as f:
            days.extend(json.load(f)["days"])
    days.sort(key=lambda d: d["date"])
    return days


def build_events(days, variant: str):
    _, _, title_field, source_note = VARIANTS[variant]
    events = []
    for day in days:
        date = dt.date.fromisoformat(day["date"])
        events.append(
            (
                date,
                f"{date.strftime('%Y%m%d')}-off-hk-{variant}@{UID_DOMAIN}",
                day[title_field],
                source_note,
            )
        )
    return events


def render(events, calname: str) -> str:
    writer = CalendarWriter(calname=calname, tz="Asia/Hong_Kong", color="#7BA7D9")
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


def write_all(out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    days = load_days()
    outputs = []
    for variant, (filename, calname, _, _) in VARIANTS.items():
        path = os.path.join(out_dir, filename)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(render(build_events(days, variant), calname))
        outputs.append(path)
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=workspace_path("dist"))
    args = parser.parse_args()
    for path in write_all(args.out):
        print(f"generated: {path}")


if __name__ == "__main__":
    main()
