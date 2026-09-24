"""sync.py 年度合理性校验测试（替代原人工门禁测试）。

新年份数据不再人工放行，改为机器校验拦截解析错误：
天数区间、与上年偏差、香港天数区间。全部离线。
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import sync  # noqa: E402


def _year_days(off: int, work: int) -> list[dict]:
    days = [{"name": "假", "date": f"2028-01-{i + 1:02d}", "isOffDay": True} for i in range(off)]
    days += [{"name": "班", "date": f"2028-02-{i + 1:02d}", "isOffDay": False} for i in range(work)]
    return days


def test_sanity_passes_on_normal_year(monkeypatch):
    monkeypatch.setattr(
        sync, "_read_year_days", lambda y: _year_days(30, 7)
    )
    assert sync.sanity_mainland([2028]) == []


def test_sanity_blocks_absurd_off_count(monkeypatch):
    monkeypatch.setattr(
        sync, "_read_year_days", lambda y: _year_days(5, 7)
    )
    problems = sync.sanity_mainland([2028])
    assert problems and "off-days" in problems[0]


def test_sanity_blocks_absurd_work_count(monkeypatch):
    monkeypatch.setattr(
        sync, "_read_year_days", lambda y: _year_days(30, 40)
    )
    problems = sync.sanity_mainland([2028])
    assert problems and "workdays" in problems[0]


def test_sanity_flags_yoy_deviation(monkeypatch):
    def fake_read(year):
        return _year_days(30, 7) if year == 2027 else _year_days(50, 7)

    monkeypatch.setattr(sync, "_read_year_days", fake_read)
    problems = sync.sanity_mainland([2027, 2028])
    assert any("deviates" in p for p in problems)


def test_sanity_tolerates_normal_yoy(monkeypatch):
    def fake_read(year):
        return _year_days(30, 7) if year == 2027 else _year_days(26, 7)

    monkeypatch.setattr(sync, "_read_year_days", fake_read)
    assert sync.sanity_mainland([2027, 2028]) == []


def test_sanity_skips_empty_years(monkeypatch):
    """空年份不校验（由 12 月季节性守卫负责），不产生问题。"""
    monkeypatch.setattr(sync, "_read_year_days", lambda y: [])
    assert sync.sanity_mainland([2028]) == []


def test_sanity_hk_range(tmp_path, monkeypatch):
    hk = tmp_path / "data" / "hk"
    hk.mkdir(parents=True)
    for year, n in ((2025, 17), (2026, 3), (2027, 25)):
        days = [{"date": f"{year}-01-01", "name": "a", "name_zh_hk": "a"}] * n
        (hk / f"{year}.json").write_text(
            json.dumps({"days": days}), encoding="utf-8"
        )
    monkeypatch.setattr(
        sync, "workspace_path", lambda *p: tmp_path.joinpath(*p)
    )
    problems = sync.sanity_hk()
    assert len(problems) == 2
    assert all("holidays" in p for p in problems)
