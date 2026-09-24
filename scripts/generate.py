#!/usr/bin/env python3
"""Generate custom holiday ICS calendars (detailed + minimal) from year JSON data.

Runtime dependency: none (stdlib only). Output goes to dist/ by default.
"""

import argparse
import datetime as dt
import glob
import itertools
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from paths import workspace_path  # noqa: E402

sys.path.insert(0, workspace_path())
from config import CONFIG  # noqa: E402

# UID 域名是日历事件身份：一旦有人订阅就冻结，改名会让订阅端把全部
# 事件判为新事件、重复插入。上线后不再变更。
UID_DOMAIN = "reddays"
PRODID = "-//ygnstudio//RedDays//CN"


def load_days():
    """Load and merge days from all yearly JSON files, deduped by date."""
    days = {}
    papers = {}
    for path in sorted(glob.glob(workspace_path("data", "[0-9][0-9][0-9][0-9].json"))):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("days", []):
            days.setdefault(item["date"], item)
        papers[data["year"]] = data.get("papers", [])
    return sorted(days.values(), key=lambda x: x["date"]), papers


def iter_runs(days):
    """Group days into consecutive runs of same name and same isOffDay."""
    for (name, is_off), group in itertools.groupby(
        days, key=lambda x: (x["name"], x["isOffDay"])
    ):
        run = []
        for item in group:
            if run:
                prev = dt.date.fromisoformat(run[-1]["date"])
                cur = dt.date.fromisoformat(item["date"])
                if (cur - prev).days != 1:
                    yield name, is_off, run
                    run = []
            run.append(item)
        yield name, is_off, run


def escape_text(value: str) -> str:
    """RFC 5545 3.3.11 TEXT escaping."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold_line(line: str) -> str:
    """Fold a content line at 75 octets (RFC 5545 3.1)."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts = []
    buf = b""
    used = 0
    limit = 75
    for ch in line:
        encoded = ch.encode("utf-8")
        if used + len(encoded) > limit:
            parts.append(buf)
            buf = b""
            used = 0
            limit = 74  # continuation lines start with one space
        buf += encoded
        used += len(encoded)
    parts.append(buf)
    return "\r\n ".join(part.decode("utf-8") for part in parts)


class CalendarWriter:
    """Minimal RFC 5545 writer with CRLF endings and line folding."""

    def __init__(self, calname=None, tz=None, color=None):
        self.lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:" + PRODID,
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "X-WR-CALNAME:" + (calname or CONFIG["calendar_name"]),
            "X-WR-TIMEZONE:" + (tz or CONFIG["tz"]),
            "X-APPLE-CALENDAR-COLOR:" + (color or CONFIG["calendar_color"]),
        ]

    def add(self, line: str):
        # escaping applies to the value part only; property name/params are structural
        name_part, sep, value = line.partition(":")
        if sep:
            line = name_part + ":" + escape_text(value)
        self.lines.append(fold_line(line))

    def render(self) -> str:
        self.lines.append("END:VCALENDAR")
        return "\r\n".join(self.lines) + "\r\n"


def _dtstamp(days) -> str:
    """Deterministic DTSTAMP derived from data (stable output for diffing)."""
    if not days:
        return "19700101T000000Z"
    latest = max(days, key=lambda x: x["date"])["date"].replace("-", "")
    return f"{latest}T000000Z"


def _papers_description(papers, year) -> str:
    links = papers.get(year, [])
    if not links:
        return ""
    return "依据国务院办公厅通知: " + " ".join(links)


def _fmt_span(start: dt.date, end: dt.date) -> str:
    if start.year == end.year:
        return f"{start.month}月{start.day}日至{end.month}月{end.day}日"
    return (
        f"{start.year}年{start.month}月{start.day}日至"
        f"{end.year}年{end.month}月{end.day}日"
    )


def _build_context(days):
    """Precompute holiday-run / makeup-work context for rich descriptions."""
    off_runs = {}  # name -> [(start, end, total_days, name)]
    for name, is_off, run in iter_runs(days):
        if is_off:
            off_runs.setdefault(name, []).append(
                (
                    dt.date.fromisoformat(run[0]["date"]),
                    dt.date.fromisoformat(run[-1]["date"]),
                    len(run),
                    name,
                )
            )
    all_runs = sorted(
        (r for runs in off_runs.values() for r in runs), key=lambda r: r[0]
    )
    next_holiday = {}  # (start, end) -> next run tuple
    for idx, r in enumerate(all_runs):
        if idx + 1 < len(all_runs):
            next_holiday[(r[0], r[1])] = all_runs[idx + 1]
    work_days = sorted(
        (dt.date.fromisoformat(x["date"]), x["name"]) for x in days if not x["isOffDay"]
    )
    groups = {}  # (name, year) -> sorted [dates]
    for day, name in work_days:
        groups.setdefault((name, day.year), []).append(day)
    next_work = {}  # workday date -> (next date, next name)
    for idx, (day, name) in enumerate(work_days):
        if idx + 1 < len(work_days):
            next_work[day] = work_days[idx + 1]
    return off_runs, groups, next_work, next_holiday


def _nearest_off_run(off_runs, name, day):
    candidates = off_runs.get(name, [])
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda r: min(abs((r[0] - day).days), abs((r[1] - day).days)),
    )


def _next_holiday_line(next_holiday, run):
    nxt = next_holiday.get((run[0], run[1]))
    if nxt:
        span = _fmt_span(nxt[0], nxt[1])
        if nxt[0].year != run[0].year:
            span = f"{nxt[0].year}年{span}"
        return f"下一个假期：{nxt[3]}（{span}）"
    return "下一个假期：待国务院公布"


def _work_rich(item, off_runs, groups, next_work, next_holiday) -> str:
    day = dt.date.fromisoformat(item["date"])
    name = item["name"]
    lines = []
    run = _nearest_off_run(off_runs, name, day)
    if run:
        lines.append(
            f"为「{name}」假期（{_fmt_span(run[0], run[1])}，共{run[2]}天）调休"
        )
    group = groups.get((name, day.year), [])
    if group:
        order = group.index(day) + 1
        dates = "、".join(f"{x.month}月{x.day}日" for x in group)
        lines.append(f"本次假期共需补班{len(group)}天（{dates}），此为第{order}天")
    nxt = next_work.get(day)
    if nxt:
        nxt_day = nxt[0]
        year_prefix = f"{nxt_day.year}年" if nxt_day.year != day.year else ""
        lines.append(
            f"下一次补班：{year_prefix}{nxt_day.month}月{nxt_day.day}日（{nxt[1]}）"
        )
    else:
        lines.append("这是当前已发布数据中的最后一个补班日")
    if run:
        nxt_line = _next_holiday_line(next_holiday, run)
        if nxt_line:
            lines.append(nxt_line)
    return "\n".join(lines)


def _off_rich(item, off_runs, groups, next_holiday) -> str:
    day = dt.date.fromisoformat(item["date"])
    name = item["name"]
    run = _nearest_off_run(off_runs, name, day)
    if not run:
        return ""
    order = (day - run[0]).days + 1
    lines = [f"「{name}」假期第{order}天（共{run[2]}天）"]
    lines.append(f"假期：{_fmt_span(run[0], run[1])}")
    group = groups.get((name, day.year), [])
    if group:
        dates = "、".join(f"{x.month}月{x.day}日" for x in group)
        lines.append(f"调休补班：{dates}")
    nxt_line = _next_holiday_line(next_holiday, run)
    if nxt_line:
        lines.append(nxt_line)
    return "\n".join(lines)


def _all_day_event(item, summary, uid, dtstamp, variant, description):
    date = item["date"].replace("-", "")
    nxt = (dt.date.fromisoformat(item["date"]) + dt.timedelta(days=1)).strftime(
        "%Y%m%d"
    )
    w = CalendarWriter.__new__(CalendarWriter)  # reuse .add without VCALENDAR header
    w.lines = ["BEGIN:VEVENT"]
    w.add(f"UID:{uid}")
    w.add(f"DTSTAMP:{dtstamp}")
    w.add("SEQUENCE:0")
    w.add(f"DTSTART;VALUE=DATE:{date}")
    w.add(f"DTEND;VALUE=DATE:{nxt}")
    w.add("TRANSP:TRANSPARENT" if variant == "detailed" else "TRANSP:OPAQUE")
    w.add(f"SUMMARY:{summary}")
    if description:
        w.add(f"DESCRIPTION:{description}")
    w.add("END:VEVENT")
    return w.lines


def _timed_event(item, summary, uid, dtstamp, cfg, description):
    date = item["date"].replace("-", "")
    start_h, start_m = cfg["work_time"][0].split(":")
    end_h, end_m = cfg["work_time"][1].split(":")
    w = CalendarWriter.__new__(CalendarWriter)
    w.lines = ["BEGIN:VEVENT"]
    w.add(f"UID:{uid}")
    w.add(f"DTSTAMP:{dtstamp}")
    w.add("SEQUENCE:0")
    w.add(f"DTSTART:{date}T{start_h}{start_m}00")
    w.add(f"DTEND:{date}T{end_h}{end_m}00")
    w.add("TRANSP:OPAQUE")
    w.add(f"SUMMARY:{summary}")
    if description:
        w.add(f"DESCRIPTION:{description}")
    if cfg["work_alarm_min"]:
        w.add("BEGIN:VALARM")
        w.add("ACTION:DISPLAY")
        w.add(f"TRIGGER:-PT{cfg['work_alarm_min']}M")
        w.add("DESCRIPTION:明天补班")
        w.add("END:VALARM")
    w.add("END:VEVENT")
    return w.lines


def build_events(days, papers, variant: str):
    """Return list of VEVENT line-blocks for the given variant."""
    cfg = CONFIG[variant]
    dtstamp = _dtstamp(days)
    rich = cfg.get("rich_description")
    if rich:
        off_runs, groups, next_work, next_holiday = _build_context(days)
    # 补班编号按（节日, 年份）分组：不连续的补班日也要编成 1/2、2/2
    wlists = {}
    for x in days:
        if not x["isOffDay"]:
            wlists.setdefault((x["name"], x["date"][:4]), []).append(x["date"])
    work_order = {
        d: (idx + 1, len(lst)) for lst in wlists.values() for idx, d in enumerate(lst)
    }
    events = []
    for name, is_off, run in iter_runs(days):
        if is_off and cfg.get("skip_off_days"):
            continue
        total = len(run)
        for i, item in enumerate(run, 1):
            kind = "off" if is_off else "work"
            uid = f"{item['date'].replace('-', '')}-{kind}-{variant}@{UID_DOMAIN}"
            year = int(item["date"][:4])
            parts = []
            if rich:
                ctx = (
                    _work_rich(item, off_runs, groups, next_work, next_holiday)
                    if not is_off
                    else _off_rich(item, off_runs, groups, next_holiday)
                )
                if ctx:
                    parts.append(ctx)
            if cfg["attach_papers"]:
                papers_line = _papers_description(papers, year)
                if papers_line:
                    parts.append(papers_line)
            description = "\n".join(parts)
            if is_off:
                if variant == "minimal" and i != 1:
                    continue
                summary = cfg["off_pattern"].format(name=name, i=i, n=total)
                events.append(
                    _all_day_event(item, summary, uid, dtstamp, variant, description)
                )
            else:
                wi, wn = work_order[item["date"]]
                summary = cfg["work_pattern"].format(name=name, i=wi, n=wn)
                if cfg["work_time"]:
                    events.append(
                        _timed_event(item, summary, uid, dtstamp, cfg, description)
                    )
                else:
                    events.append(
                        _all_day_event(
                            item, summary, uid, dtstamp, "minimal", description
                        )
                    )
    return events


def render_calendar(days, papers, variant: str) -> str:
    writer = CalendarWriter()
    for block in build_events(days, papers, variant):
        writer.lines.extend(block)
    return writer.render()


INDEX_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{
    margin: 0;
    background: #f5f4ed;
    color: #33322e;
    font: 16px/1.9 "Songti SC", "Noto Serif CJK SC", "Source Han Serif SC", serif;
  }}
  main {{
    max-width: 40em;
    margin: 0 auto;
    padding: 56px 24px 72px;
  }}
  h1 {{
    font-size: 28px;
    font-weight: 600;
    color: #1B365D;
    margin: 0 0 10px;
  }}
  .sub {{
    margin: 0 0 44px;
    color: #6b6a61;
  }}
  h2 {{
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 0.1em;
    color: #6b6a61;
    border-bottom: 1px solid #d9d6c8;
    padding-bottom: 8px;
    margin: 52px 0 4px;
  }}
  .cal {{
    padding: 16px 0 6px;
  }}
  .cal h3 {{
    font-size: 18px;
    font-weight: 600;
    color: #1B365D;
    margin: 0 0 4px;
  }}
  .cal p {{
    margin: 0 0 6px;
  }}
  .links {{
    font-size: 15px;
  }}
  .how {{
    color: #6b6a61;
  }}
  .how h2 {{
    color: #6b6a61;
  }}
  p {{
    margin: 0 0 10px;
  }}
  a {{
    color: #1B365D;
    text-decoration: none;
    border-bottom: 1px solid #b9c4d4;
  }}
  .links a + a {{
    margin-left: 14px;
  }}
  footer {{
    border-top: 1px solid #d9d6c8;
    margin-top: 52px;
    padding-top: 18px;
    color: #6b6a61;
    font-size: 14px;
  }}
</style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <p class="sub">官方公告与天文历法算法，GitHub Actions 每日自动发布。以下订阅按需选订，互不冲突。</p>

  <h2>中国大陆法定节假日</h2>
  <div class="cal">
    <h3>逐日详细版</h3>
    <p>假期每天一条（春节 假 2/9），补班带 09:00-18:00 时间和前一晚 21:00 的提醒。放假前后开着看进度用。</p>
    <p class="links"><a href="reddays-detailed.ics">reddays-detailed.ics</a><a href="webcal://ygnstudio.github.io/RedDays/reddays-detailed.ics">iPhone 点此直接添加</a></p>
  </div>
  <div class="cal">
    <h3>极简版</h3>
    <p>只有假期首日和补班日，全年约 13 条，日历保持干净。建议与详细版都订，平时只开极简版。</p>
    <p class="links"><a href="reddays-minimal.ics">reddays-minimal.ics</a><a href="webcal://ygnstudio.github.io/RedDays/reddays-minimal.ics">iPhone 点此直接添加</a></p>
  </div>
  <div class="cal">
    <h3>补班版</h3>
    <p>只含调休补班日，不含任何放假，带 09:00-18:00 时间和前一晚 21:00 的提醒。放假自己记得住、只怕忘了补班的人用。</p>
    <p class="links"><a href="reddays-workonly.ics">reddays-workonly.ics</a><a href="webcal://ygnstudio.github.io/RedDays/reddays-workonly.ics">iPhone 点此直接添加</a></p>
  </div>

  <h2>历法</h2>
  <div class="cal">
    <h3>节气农历</h3>
    <p>二十四节气（含交节时刻）加每月初一十五，农历日期写在标题里，全年约 48 条。天文算法本地推算，不用等任何机构发布。</p>
    <p class="links"><a href="reddays-lunar.ics">reddays-lunar.ics</a><a href="webcal://ygnstudio.github.io/RedDays/reddays-lunar.ics">iPhone 点此直接添加</a></p>
  </div>
  <div class="cal">
    <h3>每日黄历</h3>
    <p>每天一条，标题是宜忌摘要，点开有完整宜忌、冲煞、彭祖百忌、胎神占方和吉凶神。信不信由你，当个传统文化日历用。</p>
    <p class="links"><a href="reddays-almanac.ics">reddays-almanac.ics</a><a href="webcal://ygnstudio.github.io/RedDays/reddays-almanac.ics">iPhone 点此直接添加</a></p>
  </div>

  <h2>香港公众假期</h2>
  <div class="cal">
    <h3>简体版</h3>
    <p>香港特区政府 1823 官方名单，标题与描述均为简体。港股、跨境安排用。</p>
    <p class="links"><a href="reddays-hk.ics">reddays-hk.ics</a><a href="webcal://ygnstudio.github.io/RedDays/reddays-hk.ics">iPhone 点此直接添加</a></p>
  </div>
  <div class="cal">
    <h3>繁體版</h3>
    <p>同一份官方名單，標題與描述均為繁體。與簡體版任選其一即可。</p>
    <p class="links"><a href="reddays-hk-tc.ics">reddays-hk-tc.ics</a><a href="webcal://ygnstudio.github.io/RedDays/reddays-hk-tc.ics">iPhone 點此直接添加</a></p>
  </div>

  <section class="how">
    <h2>添加方式</h2>
    <p>Mac：日历 → 文件 → 新建日历订阅（⌥⌘S），粘贴链接。</p>
    <p>iPhone/iPad：点上面的 webcal 链接；或到 设置 → Apps → 日历 → 日历账户 → 添加订阅日历，粘贴 https 链接。</p>
    <p>Android（Google 日历）：手机或电脑浏览器打开 calendar.google.com，左上角 ＋ → 设置 → 添加日历 → 从网址，粘贴链接。订阅会自动同步到登录同一账号的手机日历。无法访问 Google 的设备，可换用任何支持「网址订阅」的日历应用，粘贴 https 链接即可。</p>
  </section>

  <footer>原始数据（JSON）与源码：<a href="https://github.com/ygnstudio/RedDays">github.com/ygnstudio/RedDays</a></footer>
</main>
</body>
</html>
"""


def write_all(out_dir: str):
    days, papers = load_days()
    os.makedirs(out_dir, exist_ok=True)
    outputs = []
    for variant in ("detailed", "minimal", "workonly"):
        path = os.path.join(out_dir, f"reddays-{variant}.ics")
        content = render_calendar(days, papers, variant)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        outputs.append(path)
    index_path = os.path.join(out_dir, "index.html")
    with open(index_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(INDEX_TEMPLATE.format(title=CONFIG["calendar_name"]))
    outputs.append(index_path)
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default=workspace_path("dist"), help="output directory"
    )
    args = parser.parse_args()
    for path in write_all(args.out):
        print(f"generated: {path}")


if __name__ == "__main__":
    main()
