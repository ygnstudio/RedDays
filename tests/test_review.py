"""sync.py 人工审查门禁测试。

覆盖 pending 判定的各种情形与摘要渲染；
git 依赖通过注入 head_reader 剥离，全部离线。
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from paths import workspace_path  # noqa: E402

import sync  # noqa: E402


DAYS_2027 = [
    {"name": "元旦", "date": "2027-01-01", "isOffDay": True},
    {"name": "元旦", "date": "2027-01-02", "isOffDay": True},
    {"name": "元旦", "date": "2027-01-03", "isOffDay": True},
]


def _write_year(year: int, days) -> None:
    sync.write_year_json(year, days, papers=["https://example.test/notice"])


def _head(days):
    """构造返回固定内容的 head_reader。"""

    def reader(year: int):
        return json.dumps({"days": days}, ensure_ascii=False)

    return reader


def test_approved_txt_parsing(tmp_path, monkeypatch):
    approved_file = tmp_path / "approved.txt"
    approved_file.write_text(
        "# 注释行\n2026\n\n 2027 # 行内注释\nabc\n", encoding="utf-8"
    )
    monkeypatch.setattr(sync, "workspace_path", lambda *p: str(approved_file))
    assert sync.load_approved() == {2026, 2027}


def test_pending_when_unapproved_year_changed(monkeypatch):
    monkeypatch.setattr(
        sync, "workspace_path",
        lambda *p: os.path.join("/tmp/rd-test", *p) if p else "/tmp/rd-test",
    )
    monkeypatch.setattr(sync, "load_approved", lambda: {2026})
    _write_year(2027, DAYS_2027)
    assert sync.detect_pending([2026, 2027], head_reader=_head(None)) == [2027]


def test_not_pending_when_year_approved(monkeypatch):
    monkeypatch.setattr(sync, "load_approved", lambda: {2027})
    assert sync.detect_pending([2027], head_reader=_head(None)) == []


def test_not_pending_when_unchanged(monkeypatch):
    monkeypatch.setattr(sync, "load_approved", lambda: set())
    assert sync.detect_pending([2027], head_reader=_head(DAYS_2027)) == []


def test_not_pending_when_days_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(sync, "load_approved", lambda: set())
    sync.write_year_json(2027, [])
    assert sync.detect_pending([2027], head_reader=_head(None)) == []


def test_summarize_days_groups_ranges():
    days = [
        {"name": "元旦", "date": "2027-01-01", "isOffDay": True},
        {"name": "元旦", "date": "2027-01-02", "isOffDay": True},
        {"name": "元旦", "date": "2027-01-03", "isOffDay": True},
    ] + [
        {"name": "春节", "date": f"2027-02-{n:02d}", "isOffDay": True}
        for n in range(6, 13)
    ]
    lines = sync.summarize_days(days)
    assert lines == [
        "- 元旦 放假 2027-01-01 ~ 2027-01-03（3 天）",
        "- 春节 放假 2027-02-06 ~ 2027-02-12（7 天）",
    ]


def test_summarize_days_separates_workdays():
    days = [
        {"name": "春节", "date": "2027-02-06", "isOffDay": True},
        {"name": "春节", "date": "2027-02-05", "isOffDay": False},
        {"name": "春节", "date": "2027-02-13", "isOffDay": False},
    ]
    lines = sync.summarize_days(days)
    # 输出保持输入序：公告惯例是先放假后补班
    assert lines == [
        "- 春节 放假 2027-02-06",
        "- 春节 上班 2027-02-05",
        "- 春节 上班 2027-02-13",
    ]


def test_render_pending_contains_summary_and_guide(monkeypatch):
    monkeypatch.setattr(
        sync, "workspace_path",
        lambda *p: os.path.join("/tmp/rd-test", *p) if p else "/tmp/rd-test",
    )
    _write_year(2027, DAYS_2027)
    text = sync.render_pending([2027], layer=1)
    assert "2027 年（共 3 条）" in text
    assert "- 元旦 放假 2027-01-01 ~ 2027-01-03（3 天）" in text
    assert "data/approved.txt" in text
    assert "https://example.test/notice" in text
    assert "layer1" in text
