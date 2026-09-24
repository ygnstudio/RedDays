"""govcn.py 解析器测试。

离线用例的句子均取自历年真实公告的典型句式；
真值对照测试（network 标记）用 data/ 里 21 年已核验数据
对整条解析流水线做端到端验证。
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from paths import workspace_path  # noqa: E402

import govcn  # noqa: E402


def test_off_range_and_month_inherit():
    days = govcn.parse_rule("春节", "2月15日至23日放假调休", 2026)
    assert [d["date"] for d in days] == [f"2026-02-{n:02d}" for n in range(15, 24)]
    assert all(d["isOffDay"] for d in days)


def test_workday_list_strips_weekday_parentheses():
    days = govcn.parse_rule("春节", "2月14日（周六）、2月28日（周六）上班", 2026)
    assert [(d["date"], d["isOffDay"]) for d in days] == [
        ("2026-02-14", False),
        ("2026-02-28", False),
    ]


def test_shift_moves_rest_to_workday():
    days = govcn.parse_rule("元旦", "1月4日（星期日）公休日调至1月2日（星期五）", 2009)
    assert [(d["date"], d["isOffDay"]) for d in days] == [
        ("2009-01-04", False),
        ("2009-01-02", True),
    ]


def test_explicit_cross_year_range():
    # 2008 公告原文：两端年份都显式给出
    days = govcn.parse_rule("元旦", "2007年12月30日—2008年1月1日放假，共3天", 2008)
    assert [d["date"] for d in days] == [
        "2007-12-30",
        "2007-12-31",
        "2008-01-01",
    ]
    assert all(d["isOffDay"] for d in days)


def test_implicit_cross_year_december():
    days = govcn.parse_rule("元旦", "12月30日至1月1日放假，共3天", 2007)
    assert [d["date"] for d in days] == [
        "2006-12-30",
        "2006-12-31",
        "2007-01-01",
    ]
    assert all(d["isOffDay"] for d in days)


def test_first_occurrence_wins_within_rule():
    # 春节假期首日先以「放假」出现，后文「调至」句重述它时不得翻转为班
    desc = "1月25日至31日放假，共7天。" "1月25日（星期日）公休日调至1月28日（星期三）。"
    days = govcn.parse_rule("春节", desc, 2009)
    by_date = {d["date"]: d["isOffDay"] for d in days}
    assert by_date["2009-01-25"] is True
    assert by_date["2009-01-28"] is True


def test_cross_sentence_month_inheritance():
    # 2007 旧版式：调至句的「3日」继承前句日期的月份
    desc = "1月1日至3日放假，共3天。将17日、18日公休日分别调至1月2日、3日"
    days = govcn.parse_rule("元旦", desc, 2007)
    by_date = {d["date"]: d["isOffDay"] for d in days}
    assert by_date["2007-01-17"] is False
    assert by_date["2007-01-18"] is False
    assert by_date["2007-01-02"] is True
    assert by_date["2007-01-03"] is True


def test_split_rules_newline_layout():
    text = "\n".join(
        [
            "国务院办公厅关于2026年",
            "部分节假日安排的通知",
            "一、元旦：",
            "1月1日（周四）至3日（周六）放假调休，共3天。1月4日（周日）上班。",
            "二、春节：",
            "2月15日至23日放假调休，共9天。",
            "国务院办公厅",
            "2025年11月4日",  # 落款日期不得误挂为规则
        ]
    )
    rules = govcn.split_rules(text)
    assert rules[0] == (
        "元旦",
        "1月1日（周四）至3日（周六）放假调休，共3天。1月4日（周日）上班。",
    )
    assert rules[1] == ("春节", "2月15日至23日放假调休，共9天。")
    assert len(rules) == 2


def test_split_rules_same_line_layout():
    text = (
        "一、元旦：1月1日至3日放假，共3天。\n二、春节：1月31日至2月6日放假调休，共7天。"
    )
    rules = govcn.split_rules(text)
    assert [r[0] for r in rules] == ["元旦", "春节"]


def test_split_rules_adjustment_notice():
    # 2019 劳动节调整类公告：标题行给上下文，条目「一、日期…」直接是内容
    text = "\n".join(
        [
            "国务院办公厅关于调整",
            "2019年劳动节假期安排的通知",
            "经国务院批准，现将调整2019年劳动节放假安排通知如下",
            "一、2019年5月1日至4日放假调休，共4天。4月28日（星期日）上班。",
        ]
    )
    rules = govcn.split_rules(text)
    assert rules[0][0] == "劳动节"
    assert "5月1日至4日" in rules[0][1]


def test_manual_days_cover_nonstandard_notices():
    for url, days in govcn.MANUAL_DAYS.items():
        assert days, url
        assert all(set(d) == {"name", "date", "isOffDay"} for d in days)


def test_seasonal_guard_december_only():
    from datetime import datetime, timedelta, timezone

    # 非十二月：任何数据状态都通过
    june = datetime(2026, 6, 1, tzinfo=timezone(timedelta(hours=8)))
    govcn  # noqa: B018  (确保模块可导入)
    from sync import check_seasonal

    check_seasonal(june)  # 不抛异常即通过


def test_seasonal_guard_fails_on_empty_next_year():
    from datetime import datetime, timedelta, timezone

    from sync import check_seasonal

    december = datetime(2026, 12, 15, tzinfo=timezone(timedelta(hours=8)))
    december_missing = workspace_path("data", "2099.json")
    if os.path.exists(december_missing):
        os.remove(december_missing)
    with pytest.raises(SystemExit):
        check_seasonal(datetime(2098, 12, 15, tzinfo=timezone(timedelta(hours=8))))


@pytest.mark.network
def test_full_pipeline_matches_verified_data():
    """端到端：重析全部年份公告，与 data/ 真值逐日比对（需外网）。"""
    mismatches = []
    for year in range(2007, 2027):
        with open(workspace_path("data", f"{year}.json"), encoding="utf-8") as f:
            stored = {d["date"]: d["isOffDay"] for d in json.load(f)["days"]}
        got = {}
        for url in json.load(
            open(workspace_path("data", f"{year}.json"), encoding="utf-8")
        )["papers"]:
            for d in govcn.parse_notice(url, year):
                got[d["date"]] = d["isOffDay"]
        if got != stored:
            mismatches.append(year)
    assert not mismatches, f"解析结果与真值不一致的年份: {mismatches}"
