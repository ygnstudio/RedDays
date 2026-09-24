#!/usr/bin/env python3
"""国务院公告（gov.cn）的发现、下载与解析，RedDays 原生实现。

流水线（每步均为可独立测试的纯函数）::

    find_notices(year)     搜索接口发现某年度全部公告 URL
    download_notice(url)   抓取网页并抽取正文行
    split_rules(text)      正文 -> [(节日名, 描述句段)]
    parse_rule(...)        描述 -> [(date, isOff)]
    collect_year(year)     组装全年数据（sync 层①入口）

公告语言只有三类事实句式（示例均摘自历年真实通知）::

    休   「2月15日至23日放假调休，共9天」
    班   「2月14日（星期六）、2月28日（星期六）上班」
    调   「5月2日（星期五）公休调至5月5日（星期一）休息」

日期定年采用「先收集、后统一」的两阶段法：先把文本扫描为
(显式年?, 月?, 日) 的有序单元格，再统一判定年份。这比边扫边定年
更干净地处理两个语言陷阱：

* 月份继承   「10月1日至7日」后半段无月份，继承前项；
* 跨年十二月 年度安排公告里无显式年份的 12 月，只可能是上一年
  末尾与元旦连休的日子（如 2007 年安排中的 2006-12-30），一律
  归入上一年。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

SEARCH_API = "https://sousuo.www.gov.cn/search-gov/data"
HTTP_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (compatible; RedDays/1.0)"

# 搜索接口会命中、但并非年度节假日安排的文档（排除）
NOISE_NOTICES = {
    "http://www.gov.cn/zhengce/zhengceku/2014-09/29/content_9102.htm",
    "http://www.gov.cn/zhengce/zhengceku/2015-02/09/content_9466.htm",
}

# 搜索接口收录不全、需要手工补充的公告（按年份）
EXTRA_NOTICES: dict[int, list[str]] = {
    2015: ["http://www.gov.cn/zhengce/zhengceku/2015-05/13/content_9742.htm"],
}

# 句式超出解析能力（非标准句式）、按原文手工誊录的公告。
# 2015：阅兵放假由国防部公告另行规定；2020：疫情延长通知无标准序号段落。
MANUAL_DAYS: dict[str, list[dict]] = {
    "http://www.gov.cn/zhengce/zhengceku/2015-05/13/content_9742.htm": [
        {
            "name": "抗日战争暨世界反法西斯战争胜利70周年纪念日",
            "date": "2015-09-03",
            "isOffDay": True,
        },
        {
            "name": "抗日战争暨世界反法西斯战争胜利70周年纪念日",
            "date": "2015-09-04",
            "isOffDay": True,
        },
        {
            "name": "抗日战争暨世界反法西斯战争胜利70周年纪念日",
            "date": "2015-09-05",
            "isOffDay": True,
        },
        {
            "name": "抗日战争暨世界反法西斯战争胜利70周年纪念日",
            "date": "2015-09-06",
            "isOffDay": False,
        },
    ],
    "http://www.gov.cn/zhengce/zhengceku/2020-01/27/content_5472352.htm": [
        {"name": "春节", "date": "2020-01-31", "isOffDay": True},
        {"name": "春节", "date": "2020-02-01", "isOffDay": True},
        {"name": "春节", "date": "2020-02-02", "isOffDay": True},
        {"name": "春节", "date": "2020-02-03", "isOffDay": False},
    ],
}

_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = USER_AGENT


# ---------------------------------------------------------------- 发现


def find_notices(year: int) -> list[str]:
    """搜索 gov.cn 政策库，返回某年度全部公告 URL（排序后）。

    接口约定：code 200 正常、1001 无命中（未发布年份的安全轮询信号）。
    """
    found: list[str] = []
    page = 0
    while True:
        resp = _SESSION.get(
            SEARCH_API,
            params={
                "t": "zhengcelibrary_gw",
                "p": page,
                "n": 5,
                "q": f"假期 {year}",  # 注意：空格必须编码为 +，%20 会静默空结果
                "pcodeJiguan": "国办发明电",
                "puborg": "国务院办公厅",
                "filetype": "通知",
                "sort": "pubtime",
            },
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
        code = payload.get("code")
        if code == 1001:
            break
        if code != 200:
            raise RuntimeError(f"搜索接口异常 code={code}: {payload.get('msg')}")
        hits = payload["searchVO"]["listVO"]
        found += [item["url"] for item in hits if str(year) in item["title"]]
        page += 1
        if page >= payload["searchVO"]["totalpage"]:
            break

    urls = [u for u in found if _canon(u) not in {_canon(x) for x in NOISE_NOTICES}]
    urls += EXTRA_NOTICES.get(year, [])
    urls = sorted(set(urls))
    if not urls and date.today().year >= year:
        raise RuntimeError(f"{year} 年公告未检索到（已发布年份不应为空）")
    return urls


def _canon(url: str) -> str:
    """归一化 URL 协议头，便于与手工维护的表做键比对。"""
    return re.sub(r"^https?://", "http://", url)


# ---------------------------------------------------------------- 下载


def download_notice(url: str) -> str:
    """抓取公告页并返回去空后的正文行（保留原始行序）。"""
    resp = _SESSION.get(url, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    box = soup.find(id="UCAP-CONTENT")
    if box is None:
        raise ValueError(f"页面缺少正文容器: {url}")
    for br in box.find_all("br"):
        br.replace_with("\n")
    lines = [ln.strip() for ln in box.get_text("\n").splitlines() if ln.strip()]
    if not lines:
        raise ValueError(f"正文抽取为空: {url}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 规则切分

_CN_INDEX = r"[一二三四五六七八九十]+"
_RE_NORMAL_RULE = re.compile(_CN_INDEX + r"、(.+?)：(.*)")
_RE_PATCH_ITEM = re.compile(_CN_INDEX + r"、(.+)")
_RE_PATCH_TITLE = re.compile(r"\d{4}年([^和、，。]{2,}?)(?:假期|放假|节假日)")


def split_rules(text: str) -> list[tuple[str, str]]:
    """把正文切分为 (节日名, 描述) 规则列表。

    支持三类公告结构：
    * 同行式：「一、元旦：1月1日至3日放假，共3天。」
    * 换行式（gov.cn 现行版式）：「一、元旦：」单独成行，
      描述句段写在紧随其后的行里；
    * 调整类（如 2020 疫情延长）：标题行给出上下文节日名，
      其后的序号条目若含日期则归属该节日。
    """
    lines = list(dict.fromkeys(text.splitlines()))  # 去重且保序
    rules: list[tuple[str, str]] = []
    pending: str | None = None  # 换行式：等待描述行的节日名
    patch_name: str | None = None  # 调整类公告的上下文节日名
    for line in lines:
        m = _RE_NORMAL_RULE.match(line)
        if m:
            name, desc = m.group(1).strip(), m.group(2).strip()
            if desc:
                rules.append((name, desc))
                pending = None
            else:
                pending = name
            continue
        m = _RE_PATCH_TITLE.search(line)
        if m and ("通知" in line or "安排" in line) and not _RE_PATCH_ITEM.match(line):
            # 仅认标题行（含「通知/安排」、不带序号前缀），防止把
            # 带显式年份的描述行（如「2022年1月1日至3日放假」）误判为标题
            patch_name = m.group(1).strip()
            continue
        if not re.search(r"\d{1,2}月\d{1,2}日", line):
            continue  # 与日期无关的行（抬头、落款等）
        if pending:
            rules.append((pending, line))
            pending = None  # 消费即清空，防止落款日期误挂到最近节日
        elif patch_name:
            m = _RE_PATCH_ITEM.match(line)
            if m:
                rules.append((patch_name, m.group(1).strip()))
    if not rules:
        raise ValueError(f"正文未切分出任何规则，前几行: {lines[:5]}")
    return rules


# ---------------------------------------------------------------- 日期解析

_DATE_ATOM = r"(?:(\d{4})年)?(?:(\d{1,2})月)?(\d{1,2})日"
_RE_RANGE = re.compile(_DATE_ATOM + r"\s*(?:至|—|－|-|~)\s*" + _DATE_ATOM)
_RE_ATOM = re.compile(_DATE_ATOM)
_RE_WEEKDAY_PAREN = re.compile(r"[（(][^）()]*[）)]")


@dataclass
class _Cell:
    """一个尚未定年的日期单元（区间端点或独立日期）。"""

    year: int | None
    month: int | None
    day: int
    range_end: bool = False  # 属于区间的终点（需与起点展开）


def _scan_cells(text: str) -> list[_Cell]:
    """扫描日期表达式，产出有序单元格。区间记为「起点 + range_end 终点」。"""
    clean = _RE_WEEKDAY_PAREN.sub("", text)
    cells: list[_Cell] = []
    taken: list[tuple[int, int]] = []

    def overlaps(span: tuple[int, int]) -> bool:
        return any(not (span[1] <= a or span[0] >= b) for a, b in taken)

    for m in _RE_RANGE.finditer(clean):
        if overlaps(m.span()):
            continue
        taken.append(m.span())
        cells.append(_Cell(_opt(m.group(1)), _opt(m.group(2)), int(m.group(3))))
        cells.append(
            _Cell(_opt(m.group(4)), _opt(m.group(5)), int(m.group(6)), range_end=True)
        )

    for m in _RE_ATOM.finditer(clean):
        if overlaps(m.span()):
            continue
        cells.append(_Cell(_opt(m.group(1)), _opt(m.group(2)), int(m.group(3))))

    return cells


def _opt(value: str | None) -> int | None:
    return int(value) if value else None


def resolve_dates(text: str, year: int, inherit_month: int | None = None) -> list[date]:
    """把一段描述文本解析为去重后的日期列表（保序）。

    定年规则：
    1. 显式年份直接采用；
    2. 缺月份继承前一个单元格的月份（「10月1日至7日」）；
       首单元格可继承跨句传入的 inherit_month（旧版式公告
       「将17日…调至…」这类省略月份的后续句子依赖它）；
    3. 无显式年份的 12 月属于上一年（年度安排中的 12 月
       只会出现在元旦跨年句里）；
    4. 其余归入公告目标年份。
    """
    cells = _scan_cells(text)
    if not cells:
        return []

    resolved: list[date] = []
    prev_month = inherit_month
    for cell in cells:
        month = cell.month or prev_month
        if month is None:
            raise ValueError(f"日期缺少月份且无可继承: {text!r}")
        if cell.year:
            d_year = cell.year
        elif month == 12:
            d_year = year - 1
        else:
            d_year = year
        resolved.append(date(d_year, month, cell.day))
        prev_month = month

    # 区间展开：终点 cell 紧跟其起点，故与 out 中最后一个日期配对
    out: list[date] = []
    for d, cell in zip(resolved, cells):
        if cell.range_end:
            cur = out[-1] if out else None
            if cur is None or d < cur:
                raise ValueError(f"区间展开异常: {text!r}")
            while cur < d:
                cur += timedelta(days=1)
                out.append(cur)
        else:
            out.append(d)

    seen: set[date] = set()
    unique = [d for d in out if not (d in seen or seen.add(d))]
    return unique


# ---------------------------------------------------------------- 句式分类

_RE_OFF = re.compile(r"(.+?)(?:放假|补休|调休|公休)+(?:共?\d+天)?$")
_RE_WORK = re.compile(r"(.+)上班$")
_RE_SHIFT = re.compile(r"(.+)调至(.+)")


def parse_rule(name: str, description: str, year: int) -> list[dict]:
    """把一条节日规则解析为 day 字典列表（格式与 data/*.json 一致）。

    两条跨句语义（旧版式公告依赖）：
    * 月份继承贯穿整条规则：后续句子里的裸「17日」继承最近日期的月份；
    * 同一日期以**首次出现**为准：「1月25日至31日放假」之后，
      「1月25日公休日调至…」对 1月25日的重述不再改变其休/班属性。
    """
    days: list[dict] = []
    seen: set[date] = set()
    prev_month: int | None = None

    def emit(text: str, is_off: bool) -> None:
        nonlocal prev_month
        got = resolve_dates(text, year, inherit_month=prev_month)
        for d in got:
            if d not in seen:
                seen.add(d)
                days.append({"name": name, "date": d.isoformat(), "isOffDay": is_off})
        if got:
            prev_month = got[-1].month

    for sentence in re.split(r"[，。；]", description):
        sentence = sentence.strip()
        if not sentence or sentence.startswith("不"):
            continue
        m = _RE_SHIFT.match(sentence)
        if m:  # 「A 公休调至 B 休息」：A 上班，B 休假
            emit(m.group(1), False)
            emit(m.group(2), True)
            continue
        m = _RE_OFF.match(sentence)
        if m:
            emit(m.group(1), True)
            continue
        m = _RE_WORK.match(sentence)
        if m:
            emit(m.group(1), False)
    return days


def parse_notice(url: str, year: int) -> list[dict]:
    """解析单份公告。句式无法解析的走手工誊录表。"""
    manual = next((v for k, v in MANUAL_DAYS.items() if _canon(k) == _canon(url)), None)
    if manual is not None:
        return [dict(d) for d in manual]

    text = download_notice(url)
    days: list[dict] = []
    for name, description in split_rules(text):
        got = parse_rule(name, description, year)
        if not got:
            raise ValueError(f"规则无任何日期产出: {name}: {description[:50]}… ({url})")
        days += got
    return days


# ---------------------------------------------------------------- 组装


def collect_year(year: int) -> dict:
    """抓取并组装某年度完整数据，返回与 data/*.json 同构的字典。"""
    urls = find_notices(year)
    merged: dict[str, dict] = {}
    for url in urls:  # 按 URL 序，后解析的覆盖先前的（历年惯例）
        for day in parse_notice(url, year):
            merged[day["date"]] = day
    return {
        "year": year,
        "papers": urls,
        "days": sorted(merged.values(), key=lambda x: x["date"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取并解析某年度国务院公告")
    parser.add_argument("year", type=int)
    args = parser.parse_args()
    print(json.dumps(collect_year(args.year), indent=4, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
