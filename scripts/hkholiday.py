#!/usr/bin/env python3
"""香港公众假期：官方数据抓取、落地 data/hk/、生成 reddays-hk.ics。

数据源是香港特区政府 1823 官方 JSON（简体 sc.json 与繁体 tc.json，
覆盖当年前后共三年，每年更新）。标题用简体，官方繁体原名写进事件描述。
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from paths import workspace_path  # noqa: E402

SC_JSON = "https://www.1823.gov.hk/common/ical/sc.json"
TC_JSON = "https://www.1823.gov.hk/common/ical/tc.json"
SOURCE = SC_JSON


def fetch_hk_days():
    """抓取官方简繁两份 JSON，按年份合并为 {year: [day, ...]}。

    每条 day: {"date": "YYYY-MM-DD", "name": 简体, "name_zh_hk": 繁体}。
    """
    import requests

    out = {}
    for key, url in (("name", SC_JSON), ("name_zh_hk", TC_JSON)):
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        payload = json.loads(resp.content.decode("utf-8-sig"))
        for vevent in payload["vcalendar"][0]["vevent"]:
            raw = vevent["dtstart"][0]
            date = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
            year = int(date[:4])
            name = vevent["summary"]
            days = out.setdefault(year, [])
            item = next((d for d in days if d["date"] == date), None)
            if item is None:
                item = {"date": date, "name": "", "name_zh_hk": ""}
                days.append(item)
            item[key] = name
    for days in out.values():
        days.sort(key=lambda d: d["date"])
    return out


def write_year_files(per_year) -> list[int]:
    """把抓取结果写入 data/hk/YYYY.json，返回涉及的年份。"""
    os.makedirs(workspace_path("data", "hk"), exist_ok=True)
    written = []
    for year in sorted(per_year):
        payload = {
            "$id": f"https://raw.githubusercontent.com/ygnstudio/RedDays/"
            f"master/data/hk/{year}.json",
            "year": year,
            "source": SOURCE,
            "days": per_year[year],
        }
        path = workspace_path("data", "hk", f"{year}.json")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
        written.append(year)
    return written


def load_years() -> list[int]:
    """data/hk/ 下已落地的年份。"""
    hk_dir = workspace_path("data", "hk")
    if not os.path.isdir(hk_dir):
        return []
    years = []
    for fname in os.listdir(hk_dir):
        if fname.endswith(".json") and fname[:4].isdigit():
            years.append(int(fname[:4]))
    return sorted(years)


def main():
    per_year = fetch_hk_days()
    written = write_year_files(per_year)
    for year in written:
        print(f"hk: {year}.json ({len(per_year[year])} days)")


if __name__ == "__main__":
    main()
