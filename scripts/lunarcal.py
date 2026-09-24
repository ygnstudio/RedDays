#!/usr/bin/env python3
"""节气农历版与每日黄历版生成（lunar_python 本地计算，无外部数据源）。

产出两个 ICS：
- reddays-lunar.ics：二十四节气（含精确交节时刻）+ 每月朔望，农历日期入标题
- reddays-almanac.ics：每日一条黄历（宜忌、冲煞、彭祖百忌、胎神、吉凶神）

节气与农历由天文算法推算，年份窗口随运行日期滚动，无需人工放行。
"""

import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from paths import workspace_path  # noqa: E402

sys.path.insert(0, workspace_path())
from config import CONFIG  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from generate import CalendarWriter, UID_DOMAIN  # noqa: E402

from lunar_python import Solar  # noqa: E402

LUNAR_YEARS_BACK = 1  # 节气农历版：保留过去 1 年、预生成未来 2 年
ALMANAC_YEARS = 2  # 黄历版体积大，只保留当年与次年


def china_today() -> dt.date:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()


def default_lunar_years(today=None):
    today = today or china_today()
    return list(range(today.year - LUNAR_YEARS_BACK, today.year + 3))


def default_almanac_years(today=None):
    today = today or china_today()
    return [today.year, today.year + 1]


def _solar_days(year: int):
    day = dt.date(year, 1, 1)
    while day.year == year:
        yield day
        day += dt.timedelta(days=1)


def _jieqi_table(lunar) -> dict:
    """交节时刻表，只保留中文键（罗马键是上个农历年的遗留项）。"""
    table = {}
    for name, solar in lunar.getJieQiTable().items():
        if name.isascii():
            continue
        table[name] = solar
    return table


def build_lunar_events(years):
    """二十四节气（含时刻）+ 每月初一/十五，农历日期入标题。"""
    events = []
    seen = set()
    for year in years:
        table = None
        for day in _solar_days(year):
            solar = Solar.fromYmd(day.year, day.month, day.day)
            lunar = solar.getLunar()
            name = lunar.getJieQi()
            is_shuo = lunar.getDayInChinese() == "初一"
            is_wang = lunar.getDayInChinese() == "十五"
            if not name and not is_shuo and not is_wang:
                continue
            if name:
                if table is None:
                    table = _jieqi_table(lunar)
                stamp = table.get(name)
                kind = "jieqi"
                summary = name
                moment = ""
                if stamp is not None and stamp.toYmd() == day.isoformat():
                    moment = f"{stamp.getHour():02d}:{stamp.getMinute():02d}"
                desc = f"{year}年{name}"
                if moment:
                    desc += f"，交节时刻 {moment}（北京时间）"
                desc += "。二十四节气依天文算法推算。"
            else:
                kind = "shuo" if is_shuo else "wang"
                month = lunar.getMonthInChinese()
                prefix = "闰" if lunar.getMonth() < 0 else ""
                day_cn = lunar.getDayInChinese()
                summary = f"{prefix}{month}月{day_cn}"
                ganzhi = lunar.getYearInGanZhi()
                desc = f"农历{lunar.getYearInChinese()}年（{ganzhi}年）{summary}"
            date_nodash = day.strftime("%Y%m%d")
            uid = f"{date_nodash}-{kind}@{UID_DOMAIN}"
            if uid in seen:
                continue
            seen.add(uid)
            events.append((day, uid, summary, desc))
    events.sort(key=lambda x: x[0])
    return events


def _fmt_list(items) -> str:
    items = [x for x in items if x]
    return "、".join(items) if items else "无"


def almanac_summary(lunar) -> str:
    yi = lunar.getDayYi()
    ji = lunar.getDayJi()

    def brief(items):
        items = [x for x in items if x]
        if not items:
            return "无"
        if len(items) > 2:
            head = " ".join(items[:2])
            return f"{head}等{len(items)}项"
        return " ".join(items)

    return f"宜 {brief(yi)}｜忌 {brief(ji)}"


def almanac_description(lunar) -> str:
    lines = [
        f"农历{lunar.getYearInChinese()}年"
        f"{'闰' if lunar.getMonth() < 0 else ''}{lunar.getMonthInChinese()}月"
        f"{lunar.getDayInChinese()}，日干支 {lunar.getDayInGanZhi()}",
        f"宜：{_fmt_list(lunar.getDayYi())}",
        f"忌：{_fmt_list(lunar.getDayJi())}",
        "冲煞：冲"
        f"{lunar.getDayChongShengXiao()}{lunar.getDayChongDesc()} "
        f"煞{lunar.getDaySha()}",
        f"彭祖百忌：{lunar.getPengZuGan()} {lunar.getPengZuZhi()}",
        f"胎神占方：{lunar.getDayPositionTai()}",
        f"吉神宜趋：{_fmt_list(lunar.getDayJiShen())}",
        f"凶神宜忌：{_fmt_list(lunar.getDayXiongSha())}",
    ]
    return "\n".join(lines)


def build_almanac_events(years):
    events = []
    for year in years:
        for day in _solar_days(year):
            lunar = Solar.fromYmd(day.year, day.month, day.day).getLunar()
            uid = f"{day.strftime('%Y%m%d')}-almanac@{UID_DOMAIN}"
            events.append((day, uid, almanac_summary(lunar), almanac_description(lunar)))
    return events


def render(events, calname, color):
    writer = CalendarWriter(calname=calname, color=color)
    for day, uid, summary, desc in events:
        nxt = (day + dt.timedelta(days=1)).strftime("%Y%m%d")
        writer.lines.extend(
            [
                "BEGIN:VEVENT",
            ]
        )
        writer.add(f"UID:{uid}")
        writer.add(f"DTSTAMP:{day.strftime('%Y%m%d')}T000000Z")
        writer.add("SEQUENCE:0")
        writer.add(f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}")
        writer.add(f"DTEND;VALUE=DATE:{nxt}")
        writer.add("TRANSP:TRANSPARENT")
        writer.add(f"SUMMARY:{summary}")
        if desc:
            writer.add(f"DESCRIPTION:{desc}")
        writer.lines.append("END:VEVENT")
    return writer.render()


def write_file(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)


def build_all(out_dir: str, lunar_years=None, almanac_years=None):
    os.makedirs(out_dir, exist_ok=True)
    lunar_years = lunar_years or default_lunar_years()
    almanac_years = almanac_years or default_almanac_years()
    lunar_events = build_lunar_events(lunar_years)
    almanac_events = build_almanac_events(almanac_years)
    outputs = [
        (
            os.path.join(out_dir, "reddays-lunar.ics"),
            render(lunar_events, "节气农历", "#F5C26B"),
        ),
        (
            os.path.join(out_dir, "reddays-almanac.ics"),
            render(almanac_events, "每日黄历", "#C4906B"),
        ),
    ]
    for path, content in outputs:
        write_file(path, content)
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=workspace_path("dist"))
    parser.add_argument("--lunar-years", type=int, nargs="*", default=None)
    parser.add_argument("--almanac-years", type=int, nargs="*", default=None)
    args = parser.parse_args()
    for path, _ in build_all(args.out, args.lunar_years, args.almanac_years):
        print(f"generated: {path}")


if __name__ == "__main__":
    main()
