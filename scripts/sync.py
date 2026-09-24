#!/usr/bin/env python3
"""数据同步：直连解析 + 快照降级 + 新鲜度/季节性/年度合理性守卫。

Layer 1: 直连 gov.cn 解析公告（scripts/govcn.py，需 requests+bs4）。
Layer 2: 什么都不做，本地 git 快照原样发布。

降级不中断发布；守卫是唯一能让脚本失败（exit 2）的路径：
新鲜度、季节性守卫盯「断更」，年度合理性校验盯「解析错误」。
新年份公告解析出的数据若与上年规模偏差过大或条数异常，
直接拦下本次发布并在 workflow 开告警 issue。
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from paths import workspace_path  # noqa: E402

SCHEMA_URL = "https://raw.githubusercontent.com/ygnstudio/RedDays/master/schema.json"
STALE_AFTER_DAYS = 400  # 正常节奏每年 11 月必更新次年
# 年度合理性阈值（依据 2007-2026 年实数据校准：off 22-33 天，work 5-12 天）
MAINLAND_OFF_RANGE = (10, 40)
MAINLAND_WORK_RANGE = (3, 15)
MAINLAND_YOY_MAX_RATIO = 0.4  # 与上年放假日数偏差不得超过 40%
HK_DAYS_RANGE = (12, 20)  # 香港公众假期 2025-2027 实测均为 17 天


def china_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=8)))


def default_years():
    now = china_now()
    return [now.year, now.year + 1]


def write_year_json(year: int, days, papers=None) -> None:
    """Write year data in the schema-compatible JSON format."""
    payload = {
        "$schema": SCHEMA_URL,
        "$id": f"https://raw.githubusercontent.com/ygnstudio/RedDays/master/data/{year}.json",
        "year": year,
        "papers": papers or [],
        "days": days,
    }
    os.makedirs(workspace_path("data"), exist_ok=True)
    path = workspace_path("data", f"{year}.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)


def sync_layer1(years):
    """Direct gov.cn parsing via scripts/govcn.py."""
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    from govcn import collect_year  # noqa: F401  imports requests/bs4

    for year in years:
        data = collect_year(year)
        write_year_json(year, data["days"], data.get("papers", []))
    return True


def check_freshness():
    out = subprocess.run(
        [
            "git",
            "log",
            "-1",
            "--format=%cI",
            "--",
            "data/[0-9][0-9][0-9][0-9].json",
            "data/hk/[0-9][0-9][0-9][0-9].json",
        ],
        capture_output=True,
        text=True,
        cwd=workspace_path(),
    )
    line = out.stdout.strip()
    if not line:
        print("freshness: no git history for data files, skip")
        return
    last = datetime.fromisoformat(line)
    age_days = (datetime.now(last.tzinfo) - last).days
    if age_days > STALE_AFTER_DAYS:
        raise SystemExit(
            f"freshness guard FAILED: data last updated {last.date()} "
            f"({age_days} days ago, limit {STALE_AFTER_DAYS})"
        )
    print(f"freshness: ok (last data update {last.date()}, {age_days} days ago)")


def check_seasonal(now: datetime | None = None) -> None:
    """季节性守卫：12 月起次年数据必须落地，否则说明解析层失灵。

    400 天新鲜度守卫的盲区：gov.cn 已发公告、但 layer1 解析失败时，
    layer2 快照会健康地空跑一整年。此守卫把最坏静默窗口
    从一年压缩到一个月。
    """
    now = now or china_now()
    if now.month != 12:
        print("seasonal: ok (guard active in December only)")
        return
    path = workspace_path("data", f"{now.year + 1}.json")
    try:
        with open(path, encoding="utf-8") as f:
            days = json.load(f).get("days", [])
    except FileNotFoundError:
        days = []
    if not days:
        raise SystemExit(
            f"seasonal guard FAILED: it is December, but data/{now.year + 1}.json "
            "is empty. gov.cn likely published the notice and the parse layer "
            "failed; investigate before publishing."
        )
    print(f"seasonal: ok ({now.year + 1}.json has {len(days)} days)")


# ------------------------------------------------------------- 年度合理性校验


def _read_year_days(year: int) -> list[dict]:
    path = workspace_path("data", f"{year}.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("days", [])


def sanity_mainland(years: list[int]) -> list[str]:
    """大陆年份校验：放/班天数在合理区间内，且与上年偏差不超阈值。

    返回问题列表；非空即拦发布。解析 gov.cn 公告正文没有第二真值，
    这组校验替代人工核对，拦截绝大多数解析错漏（整段丢失、日期错位）。
    """
    problems = []
    counts: dict[int, tuple[int, int]] = {}
    for year in years:
        days = _read_year_days(year)
        if not days:
            continue  # 空年份由季节性守卫在 12 月负责
        off = sum(1 for d in days if d.get("isOffDay"))
        work = sum(1 for d in days if not d.get("isOffDay"))
        counts[year] = (off, work)
        if not MAINLAND_OFF_RANGE[0] <= off <= MAINLAND_OFF_RANGE[1]:
            problems.append(
                f"mainland {year}: {off} off-days outside "
                f"{MAINLAND_OFF_RANGE}, parse likely broken"
            )
        if not MAINLAND_WORK_RANGE[0] <= work <= MAINLAND_WORK_RANGE[1]:
            problems.append(
                f"mainland {year}: {work} workdays outside "
                f"{MAINLAND_WORK_RANGE}, parse likely broken"
            )
    sorted_years = sorted(counts)
    for prev, cur in zip(sorted_years, sorted_years[1:]):
        if cur - prev != 1:
            continue
        ratio = abs(counts[cur][0] - counts[prev][0]) / counts[prev][0]
        if ratio > MAINLAND_YOY_MAX_RATIO:
            problems.append(
                f"mainland {cur}: off-days {counts[cur][0]} deviates "
                f"{ratio:.0%} from {prev} ({counts[prev][0]}), "
                "verify against the announcement"
            )
    return problems


def sanity_hk() -> list[str]:
    """香港年份校验：每年公众假期天数在合理区间内。"""
    problems = []
    hk_dir = workspace_path("data", "hk")
    if not os.path.isdir(hk_dir):
        return problems
    for fname in os.listdir(hk_dir):
        if not fname.endswith(".json"):
            continue
        year = int(fname[:4])
        with open(os.path.join(hk_dir, fname), encoding="utf-8") as f:
            n = len(json.load(f).get("days", []))
        if not HK_DAYS_RANGE[0] <= n <= HK_DAYS_RANGE[1]:
            problems.append(
                f"hk {year}: {n} holidays outside {HK_DAYS_RANGE}, "
                "source data suspicious"
            )
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, nargs="*", default=None)
    parser.add_argument(
        "--status-file", default=workspace_path("dist", "sync-status.txt")
    )
    args = parser.parse_args()
    years = args.years or default_years()

    layer = 2
    try:
        if sync_layer1(years):
            layer = 1
            print("sync: layer1 OK (direct gov.cn parsing)")
    except Exception as ex:  # noqa: BLE001
        print(f"sync: layer1 FAILED: {type(ex).__name__}: {ex}")
        print("sync: layer2 (local snapshot, no update this run)")

    degraded = layer != 1
    status = f"layer={layer} degraded={'yes' if degraded else 'no'} years={years}"
    print(status)
    os.makedirs(os.path.dirname(args.status_file), exist_ok=True)
    with open(args.status_file, "w", encoding="utf-8") as f:
        f.write(status + "\n")

    check_freshness()
    check_seasonal()

    problems = sanity_mainland(years) + sanity_hk()
    if problems:
        for p in problems:
            print(f"sanity: FAILED: {p}")
        raise SystemExit(
            "sanity guard FAILED: new year data failed plausibility checks; "
            "publication blocked. Compare data/*.json against the official "
            "announcement before fixing scripts/govcn.py."
        )
    print("sanity: ok (mainland + hk plausibility checks passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
