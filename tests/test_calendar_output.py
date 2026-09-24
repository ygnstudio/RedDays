"""Tests for the custom calendar generation pipeline (generate/sync/crosscheck)."""

import datetime as dt
import os
import re
import sys

import pytest
from icalendar import Calendar

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/../scripts"))
from paths import workspace_path  # noqa: E402
from generate import (  # noqa: E402
    build_events,
    iter_runs,
    load_days,
    render_calendar,
)

WORK_2026 = {
    "2026-01-04",
    "2026-02-14",
    "2026-02-28",
    "2026-05-09",
    "2026-09-20",
    "2026-10-10",
}
OFF_2026_COUNT = 33
MINIMAL_2026_COUNT = 13


@pytest.fixture(scope="module")
def data():
    return load_days()


def test_2026_workdays_ground_truth(data):
    days, _ = data
    work = {
        d["date"] for d in days if d["date"].startswith("2026") and not d["isOffDay"]
    }
    assert work == WORK_2026


def test_2026_offdays_count(data):
    days, _ = data
    off = [d for d in days if d["date"].startswith("2026") and d["isOffDay"]]
    assert len(off) == OFF_2026_COUNT


def test_2026_minimal_event_count(data):
    days, _ = data
    minimal = build_events(days, {}, "minimal")
    count_2026 = sum(
        1
        for block in minimal
        for line in block
        if line.startswith("DTSTART;VALUE=DATE:2026")
    )
    assert count_2026 == MINIMAL_2026_COUNT


def test_detailed_spring_festival_progress(data):
    days, _ = data
    detailed = build_events(days, {}, "detailed")
    date_summary = {}
    for block in detailed:
        d = s = None
        for line in block:
            if line.startswith("DTSTART"):
                d = line.split(":", 1)[-1].strip()[:8]
            elif line.startswith("SUMMARY"):
                s = line.split(":", 1)[-1]
        if d and d.startswith("2026"):
            date_summary[d] = s
    assert date_summary["20260215"] == "春节 假 1/9"
    assert date_summary["20260223"] == "春节 假 9/9"
    assert date_summary["20260214"] == "春节 补 1/2"


def test_render_deterministic(data):
    days, papers = data
    assert render_calendar(days, papers, "detailed") == render_calendar(
        days, papers, "detailed"
    )
    assert render_calendar(days, papers, "minimal") == render_calendar(
        days, papers, "minimal"
    )
    assert render_calendar(days, papers, "workonly") == render_calendar(
        days, papers, "workonly"
    )


def test_workonly_has_no_off_events(data):
    days, _ = data
    workonly = build_events(days, {}, "workonly")
    summaries = [
        line.split(":", 1)[-1] for block in workonly for line in block
        if line.startswith("SUMMARY:")
    ]
    assert summaries and all(" 假 " not in s for s in summaries)
    work_dates = {
        line.split(":", 1)[-1].strip()[:8]
        for block in workonly
        for line in block
        if line.startswith("DTSTART")
    }
    expected = {
        d["date"].replace("-", "") for d in days if not d["isOffDay"]
    }
    assert work_dates == expected


def test_uid_stable_across_runs(data):
    days, papers = data
    uids_a, uids_b = set(), set()
    for block in build_events(days, papers, "detailed"):
        for line in block:
            if line.startswith("UID:"):
                uids_a.add(line)
    for block in build_events(days, papers, "detailed"):
        for line in block:
            if line.startswith("UID:"):
                uids_b.add(line)
    assert uids_a == uids_b and len(uids_a) > 0


def test_crlf_and_required_properties(data):
    days, papers = data
    for variant in ("detailed", "minimal"):
        text = render_calendar(days, papers, variant)
        assert "\r\n" in text
        for line in text.split("\r\n"):
            assert not line.startswith("\n")
        for block in build_events(days, papers, variant):
            joined = "\n".join(block)
            for prop in ("UID:", "DTSTAMP:", "SEQUENCE:", "DTSTART", "SUMMARY:"):
                assert prop in joined
            assert "END:VEVENT" in joined


def test_detailed_workday_has_alarm_and_time(data):
    days, papers = data
    for block in build_events(days, papers, "detailed"):
        joined = "\n".join(block)
        if "-work-" in "\n".join(l for l in block if l.startswith("UID:")):
            assert "DTSTART:20260214T090000" in joined or "T090000" in joined
            assert "BEGIN:VALARM" in joined
            assert "TRIGGER:-PT720M" in joined
            assert "TRANSP:OPAQUE" in joined
            break
    else:
        pytest.fail("no work event found in detailed calendar")


def test_icalendar_roundtrip(data, tmp_path):
    days, papers = data
    for variant in ("detailed", "minimal"):
        text = render_calendar(days, papers, variant).replace("\r\n", "\n")
        cal = Calendar.from_ical(text)
        events = [c for c in cal.walk("VEVENT")]
        expected = sum(
            1
            for block in build_events(days, papers, variant)
            if "BEGIN:VEVENT" in block
        )
        assert len(events) == expected
        for ev in events:
            assert ev.get("UID")
            assert ev.get("DTSTAMP")
            assert ev.get("SEQUENCE") is not None


def test_no_duplicate_dates_across_years(data):
    days, _ = data
    dates = [d["date"] for d in days]
    assert len(dates) == len(set(dates))


def test_detailed_work_description_context(data):
    days, papers = data
    found = False
    for block in build_events(days, papers, "detailed"):
        text = "\n".join(block).replace("\r\n ", "")  # unfold folded lines
        if "20260214-work-" in text:
            found = True
            assert "为「春节」假期（2月15日至2月23日，共9天）调休" in text
            assert "共需补班2天（2月14日、2月28日），此为第1天" in text
            assert "下一次补班：2月28日（春节）" in text
            assert "下一个假期：清明节（4月4日至4月6日）" in text
            assert "国务院办公厅通知" in text
    assert found, "work event 20260214 not found"


def test_detailed_off_description_context(data):
    days, papers = data
    found = False
    for block in build_events(days, papers, "detailed"):
        text = "\n".join(block).replace("\r\n ", "")
        if "20260215-off-" in text:
            found = True
            assert "「春节」假期第1天（共9天）" in text
            assert "假期：2月15日至2月23日" in text
            assert "调休补班：2月14日、2月28日" in text
            assert "下一个假期：清明节（4月4日至4月6日）" in text
    assert found, "off event 20260215 not found"


def test_detailed_last_workday_has_no_next(data):
    days, papers = data
    for block in build_events(days, papers, "detailed"):
        text = "\n".join(block).replace("\r\n ", "")
        if "20261010-work-" in text:
            assert "最后一个补班日" in text
            assert "下一次补班" not in text
            return
    pytest.fail("work event 20261010 not found")


def test_cross_year_references_carry_year(data):
    """跨年引用必须带年份：2025-10 的下一个假期是 2026 元旦。"""
    days, papers = data
    found = False
    for block in build_events(days, papers, "detailed"):
        text = "\n".join(block).replace("\r\n ", "")
        if "20251001-off-" in text:
            found = True
            assert "下一个假期：元旦（2026年1月1日至1月3日）" in text
    assert found, "off event 20251001 not found"


def test_last_run_without_next_shows_pending(data):
    """数据尽头（2027 未发布）的假期应明确写「待国务院公布」。"""
    days, papers = data
    found = False
    for block in build_events(days, papers, "detailed"):
        text = "\n".join(block).replace("\r\n ", "")
        if "20261001-off-" in text:
            found = True
            assert "下一个假期：待国务院公布" in text
    assert found, "off event 20261001 not found"


def test_crosscheck_internal_consistency():
    """Crosscheck parser against a tiny synthetic Apple-style ICS."""
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/../scripts"))
    import crosscheck

    sample = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\n"
        "DTSTART;VALUE=DATE:20260214\r\n"
        "SUMMARY:春节（班）\r\n"
        "END:VEVENT\r\n"
        "BEGIN:VEVENT\r\n"
        "DTSTART;VALUE=DATE:20260215\r\n"
        "SUMMARY:春节（休）\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    events = crosscheck.parse_events(sample)
    assert events["2026-02-14"] == "春节（班）"
    assert crosscheck.classify(events["2026-02-14"]) == "work"
    assert crosscheck.classify(events["2026-02-15"]) == "off"
