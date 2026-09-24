"""节气农历、每日黄历与香港假期生成的离线测试。"""

import json

import pytest

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))
from lunarcal import build_almanac_events, build_lunar_events, render  # noqa: E402
from ethniccal import build_christian, build_ethnic, build_hijri, easter  # noqa: E402
from hkcal import build_events as hk_build_events  # noqa: E402
from hkcal import render as hk_render  # noqa: E402
from hkcal import write_all as hk_write_all  # noqa: E402


@pytest.fixture(scope="module")
def lunar_events_2026():
    return build_lunar_events([2026])


@pytest.fixture(scope="module")
def almanac_events_2026():
    return build_almanac_events([2026])


def test_lunar_has_24_jieqi(lunar_events_2026):
    jieqi = [e for e in lunar_events_2026 if "-jieqi@" in e[1]]
    assert len(jieqi) == 24


def test_lunar_covers_year_boundary(lunar_events_2026):
    """2026 年 1 月应有上个农历年的腊月日期，12 月后无断档。"""
    dates = {e[0].isoformat() for e in lunar_events_2026}
    jan = [d for d in dates if d.startswith("2026-01")]
    assert jan, "年初缺少上一年农历月的日期"


def test_lunar_daily_covers_every_day(lunar_events_2026):
    """每日农历事件覆盖全年且无重复日期；农历正月初一在标题中。"""
    daily = [e for e in lunar_events_2026 if "-lunar@" in e[1]]
    assert len(daily) == 365
    assert len({e[0] for e in daily}) == 365
    assert any(e[2] == "正月初一" and e[0].isoformat() == "2026-02-17" for e in daily)


def test_lunar_jieqi_moment_in_description(lunar_events_2026):
    lichun = [e for e in lunar_events_2026 if e[2] == "立春"]
    assert len(lichun) == 1
    assert "交节时刻" in lichun[0][3]


def test_almanac_covers_every_day(almanac_events_2026):
    assert len(almanac_events_2026) == 365
    assert len({e[0] for e in almanac_events_2026}) == len(almanac_events_2026)


def test_almanac_summary_has_yi_ji(almanac_events_2026):
    for _, _, summary, _ in almanac_events_2026:
        assert summary.startswith("宜 ")


def test_almanac_description_fields(almanac_events_2026):
    sample = almanac_events_2026[100][3]
    for key in ("宜：", "忌：", "冲煞：", "彭祖百忌：", "胎神占方："):
        assert key in sample


def test_render_deterministic(lunar_events_2026, almanac_events_2026):
    assert render(lunar_events_2026, "节气农历", "#F5C26B") == render(
        lunar_events_2026, "节气农历", "#F5C26B"
    )
    assert render(almanac_events_2026, "每日黄历", "#C4906B") == render(
        almanac_events_2026, "每日黄历", "#C4906B"
    )


@pytest.fixture
def hk_days(tmp_path):
    return [
        {
            "date": "2026-01-01",
            "name": "一月一日",
            "name_zh_hk": "一月一日",
        },
        {
            "date": "2026-12-25",
            "name": "圣诞节",
            "name_zh_hk": "聖誕節",
        },
    ]


def test_hk_events_use_simplified_desc(hk_days):
    events = hk_build_events(hk_days, "sc")
    by_summary = {e[2]: e for e in events}
    assert set(by_summary) == {"一月一日", "圣诞节"}
    christmas = by_summary["圣诞节"]
    assert "依据香港特区政府" in christmas[3]
    assert all("聖誕節" not in e[3] for e in events)


def test_hk_tc_variant_all_traditional(hk_days):
    events = hk_build_events(hk_days, "tc")
    by_summary = {e[2]: e for e in events}
    assert set(by_summary) == {"一月一日", "聖誕節"}
    christmas = by_summary["聖誕節"]
    assert "依據香港特區政府" in christmas[3]
    assert all("圣诞节" not in e[3] and "香港特区政府" not in e[3] for e in events)


def test_hk_render_has_events(hk_days):
    text = hk_render(hk_build_events(hk_days, "sc"), "香港公众假期")
    assert text.count("BEGIN:VEVENT") == 2
    assert "X-WR-CALNAME:香港公众假期" in text
    assert "-off-hk-sc@reddays" in text


def test_hk_write_all_emits_both_variants(hk_days, tmp_path, monkeypatch):
    import hkcal

    monkeypatch.setattr(hkcal, "load_days", lambda: hk_days)
    outputs = hk_write_all(str(tmp_path))
    names = {os.path.basename(p) for p in outputs}
    assert names == {"reddays-hk.ics", "reddays-hk-tc.ics"}
    sc = (tmp_path / "reddays-hk.ics").read_text(encoding="utf-8")
    tc = (tmp_path / "reddays-hk-tc.ics").read_text(encoding="utf-8")
    assert "SUMMARY:圣诞节" in sc and "SUMMARY:聖誕節" in tc
    assert "X-WR-CALNAME:香港公眾假期" in tc
    assert "-off-hk-tc@reddays" in tc


def test_hk_gate_detects_unapproved_change(tmp_path, monkeypatch):
    """未放行年份的数据变化必须被 detect_hk_pending 捕获。"""
    import sync as sync_mod

    days_old = [{"date": "2027-01-01", "name": "a", "name_zh_hk": "a"}]
    days_new = [{"date": "2027-01-01", "name": "b", "name_zh_hk": "b"}]

    def fake_read(year):
        return days_new

    def fake_head(year):
        return json.dumps({"days": days_old})

    monkeypatch.setattr(sync_mod, "_read_hk_days", fake_read)
    monkeypatch.setattr(sync_mod, "hk_head_content", fake_head)
    assert sync_mod.detect_hk_pending(approved={2025, 2026}, head_reader=fake_head) == [2027]
    assert sync_mod.detect_hk_pending(approved={2025, 2026, 2027}, head_reader=fake_head) == []


def test_easter_computus():
    assert easter(2026) == __import__("datetime").date(2026, 4, 5)
    assert easter(2025) == __import__("datetime").date(2025, 4, 20)


def test_ethnic_key_dates_2026():
    events = build_ethnic([2026])
    got = {(e[0].isoformat(), e[2]) for e in events}
    assert ("2026-03-20", "开斋节") in got
    assert ("2026-05-27", "古尔邦节") in got
    assert ("2026-02-18", "藏历新年") in got
    assert ("2026-04-13", "泼水节") in got
    assert ("2026-08-06", "火把节") in got
    assert ("2026-11-20", "彝历新年") in got


def test_ethnic_islamic_desc_carries_caveat():
    events = build_ethnic([2026])
    for _, _, summary, desc in events:
        if summary in ("开斋节", "古尔邦节"):
            assert "以当地政府公告为准" in desc


def test_hijri_daily_covers_full_year():
    events = build_hijri([2026])
    assert len(events) == 365
    assert len({e[0] for e in events}) == 365
    marks = [e for e in events if "斋月首日" in e[2]]
    assert any(e[0].isoformat() == "2026-02-18" for e in marks)


def test_christian_key_dates_2026():
    events = build_christian([2026])
    got = {(e[0].isoformat(), e[2]) for e in events}
    assert ("2026-04-05", "复活节") in got
    assert ("2026-04-03", "耶稣受难节") in got
    assert ("2026-12-25", "圣诞节") in got
    assert len(events) == 9
