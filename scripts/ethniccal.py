#!/usr/bin/env python3
"""民族与宗教日历生成：产出民族节日、每日回历、基督教历三个 ICS。

- reddays-ethnic.ics：开斋节、古尔邦节（回历推算）、泼水节（公历固定）、
  火把节（农历推算）、藏历新年（已核实历年表）、彝历新年（凉山州公告口径）
- reddays-hijri.ics：每天一条带回历日期，重要纪念日写入标题
- reddays-christian.ics：复活节及关联节日（computus 纯算法）+ 圣诞相关

回历用 hijridate（Umm al-Qura 历法）；伊斯兰节日官方放假日期以当地政府公告
为准，新月观测可能比推算晚一天，描述内均有标注。
"""

import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from paths import workspace_path  # noqa: E402

from hijridate import Hijri, Gregorian  # noqa: E402
from lunar_python import Solar  # noqa: E402

from generate import CalendarWriter, UID_DOMAIN  # noqa: E402

# 藏历新年（洛萨）已核实公历日期。来源：维基百科「藏历新年」历年表与
# R calcal 包 tibetan_new_year() 交叉一致。表外年份无从推算，须逐年核实补充。
LOSAR = {
    2024: (2, 10),
    2025: (2, 28),
    2026: (2, 18),
    2027: (2, 7),
    2028: (2, 26),
}

# 彝历新年（彝族年）：凉山州人民政府办公室历年节假日安排通知均为
# 11 月 20 日开始放假（2025、2026 两年公告一致），此处记录首日。
YI_NEW_YEAR_MONTH_DAY = (11, 20)

# 回历重要纪念日：(月, 日, 名称)
HIJRI_MARKS = [
    (1, 1, "伊斯兰历新年"),
    (1, 10, "阿舒拉日"),
    (3, 12, "圣纪"),
    (7, 27, "登霄夜"),
    (8, 15, "白拉特夜"),
    (9, 1, "斋月首日"),
    (10, 1, "开斋节"),
    (12, 10, "古尔邦节"),
]


def easter(year: int) -> dt.date:
    """复活节（西方教会），Meeus/Jones/Butcher computus 算法。"""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return dt.date(year, month, day)


def in_window(date: dt.date, years: list[int]) -> bool:
    return date.year in years


def lunar_month_day(year: int, month: int, day: int) -> dt.date:
    """农历月日 -> 公历。lunar_python 的 Lunar.fromYmd 无跨年回退问题，
    直接用当年农历年号即可。"""
    from lunar_python import Lunar
    lunar = Lunar.fromYmd(year, month, day)
    s = lunar.getSolar()
    return dt.date(s.getYear(), s.getMonth(), s.getDay())


def build_ethnic(years: list[int]) -> list:
    """民族节日合集：(date, uid, summary, description) 列表。"""
    events = []
    hi_years = range(
        Gregorian(years[0], 1, 1).to_hijri().year - 1,
        Gregorian(years[-1], 12, 31).to_hijri().year + 2,
    )
    for hy in hi_years:
        for hm, hd, name in ((10, 1, "开斋节"), (12, 10, "古尔邦节")):
            try:
                g = Hijri(hy, hm, hd).to_gregorian()
            except (ValueError, OverflowError):
                continue
            date = dt.date(g.year, g.month, g.day)
            if not in_window(date, years):
                continue
            desc = (
                f"回历 {hy} 年 {hm} 月 {hd} 日推算。"
                "官方放假日期以当地政府公告为准，新月观测可能晚一天。"
            )
            events.append(
                (date, f"{date.strftime('%Y%m%d')}-ethnic-{name}@{UID_DOMAIN}", name, desc)
            )

    for year in years:
        # 泼水节：公历固定 4 月 13 至 15 日，西双版纳、德宏官方假日
        date = dt.date(year, 4, 13)
        events.append(
            (
                date,
                f"{date.strftime('%Y%m%d')}-ethnic-poshui@{UID_DOMAIN}",
                "泼水节",
                "傣历新年，公历 4 月 13 至 15 日，共 3 天。"
                "西双版纳、德宏等地法定假日。",
            )
        )
        # 火把节：农历六月二十四
        date = lunar_month_day(year, 6, 24)
        events.append(
            (
                date,
                f"{date.strftime('%Y%m%d')}-ethnic-huoba@{UID_DOMAIN}",
                "火把节",
                "农历六月二十四。彝、白、纳西等民族传统节日，"
                "凉山州等地的放假安排以当年公告为准。",
            )
        )
        # 藏历新年：已核实表
        if year in LOSAR:
            month, day = LOSAR[year]
            date = dt.date(year, month, day)
            events.append(
                (
                    date,
                    f"{date.strftime('%Y%m%d')}-ethnic-losar@{UID_DOMAIN}",
                    "藏历新年",
                    "藏历正月初一（洛萨）。日期逐年经官方名单核实；"
                    "西藏等地法定假日。",
                )
            )
        # 彝历新年：凉山州公告口径，11 月 20 日
        month, day = YI_NEW_YEAR_MONTH_DAY
        date = dt.date(year, month, day)
        events.append(
            (
                date,
                f"{date.strftime('%Y%m%d')}-ethnic-yi@{UID_DOMAIN}",
                "彝历新年",
                "凉山州法定假日，历年公告均为 11 月 20 日起放假，"
                "具体天数以当年公告为准。",
            )
        )

    events.sort(key=lambda e: e[0])
    return events


def build_hijri(years: list[int]) -> list:
    """每日回历：标题带回历日期，纪念日写入标题。"""
    events = []
    for year in years:
        d = dt.date(year, 1, 1)
        while d.year == year:
            h = Gregorian(d.year, d.month, d.day).to_hijri()
            mark = next((n for m, dd, n in HIJRI_MARKS if (h.month, h.day) == (m, dd)), "")
            title = f"回历 {h.year}年{h.month}月{h.day}日"
            if mark:
                title = f"{mark}（回历 {h.month}月{h.day}日）"
            desc = "伊斯兰历每日换算，Umm al-Qura 历法。新月观测地区的实际入月日期可能晚一天。"
            events.append(
                (
                    d,
                    f"{d.strftime('%Y%m%d')}-hijri@{UID_DOMAIN}",
                    title,
                    desc if mark else "",
                )
            )
            d += dt.timedelta(days=1)
    return events


def build_christian(years: list[int]) -> list:
    """基督教历：复活节 computus 推算关联节日 + 圣诞相关固定日期。"""
    events = []
    offset_days = [
        (-46, "圣灰星期三", "四旬期首日"),
        (-7, "棕枝主日", "复活节前一周"),
        (-2, "耶稣受难节", ""),
        (0, "复活节", "基督教最核心的节日"),
        (39, "升天节", "复活节后第 39 天"),
        (49, "圣灵降临节", "复活节后第 49 天"),
    ]
    for year in years:
        e = easter(year)
        for offset, name, note in offset_days:
            date = e + dt.timedelta(days=offset)
            desc = f"{year} 年复活节为 {e.isoformat()} 推算。" + (f"{note}。" if note else "")
            events.append(
                (
                    date,
                    f"{date.strftime('%Y%m%d')}-christian-{name}@{UID_DOMAIN}",
                    name,
                    desc,
                )
            )
        for month, day, name in ((12, 24, "平安夜"), (12, 25, "圣诞节"), (1, 6, "主显节")):
            date = dt.date(year, month, day)
            events.append(
                (
                    date,
                    f"{date.strftime('%Y%m%d')}-christian-{name}@{UID_DOMAIN}",
                    name,
                    "",
                )
            )
    events.sort(key=lambda e: e[0])
    return events


def render(events, calname: str, color: str) -> str:
    writer = CalendarWriter(calname=calname, tz="Asia/Shanghai", color=color)
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


def default_years() -> list[int]:
    year = dt.date.today().year
    return [year - 1, year, year + 1, year + 2]


def write_all(out_dir: str, years: list[int] | None = None) -> list[str]:
    years = years or default_years()
    os.makedirs(out_dir, exist_ok=True)
    jobs = [
        ("reddays-ethnic.ics", "民族节日", build_ethnic(years), "#6FBF9B"),
        ("reddays-hijri.ics", "回历每日", build_hijri(years), "#8FBFA8"),
        ("reddays-christian.ics", "基督教历", build_christian(years), "#A8B8D9"),
    ]
    outputs = []
    for filename, calname, builder, color in jobs:
        path = os.path.join(out_dir, filename)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(render(builder, calname, color))
        outputs.append(path)
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=workspace_path("dist"))
    parser.add_argument("--years", help="逗号分隔的公历年份，默认近 1 年加未来 2 年")
    args = parser.parse_args()
    years = [int(y) for y in args.years.split(",")] if args.years else None
    for path in write_all(args.out, years):
        print(f"generated: {path}")


if __name__ == "__main__":
    main()
