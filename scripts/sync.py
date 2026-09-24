#!/usr/bin/env python3
"""数据同步：直连解析 + 快照降级 + 新鲜度/季节性守卫 + 新年份人工审查门禁。

Layer 1: 直连 gov.cn 解析公告（scripts/govcn.py，需 requests+bs4）。
Layer 2: 什么都不做，本地 git 快照原样发布。

降级不中断发布；只有守卫能让脚本失败（exit 2），确保断更不会被悄悄放过。
新年份公告首次解析出的数据会被 hold（不提交、不上线），等人工核对解析
摘要与公告原文、把年份加入 data/approved.txt 后放行。这个环节没有真值
和苹果日历兜底，是整条流水线唯一可能静默出错的地方。
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
        ["git", "log", "-1", "--format=%cI", "--", "data/[0-9][0-9][0-9][0-9].json"],
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


# ---------------------------------------------------------------- 人工审查门禁


def load_approved() -> set[int]:
    """data/approved.txt 里已人工放行的年份（# 后为注释）。"""
    path = workspace_path("data", "approved.txt")
    approved: set[int] = set()
    if not os.path.exists(path):
        return approved
    with open(path, encoding="utf-8") as f:
        for line in f:
            token = line.split("#", 1)[0].strip()
            if token.isdigit():
                approved.add(int(token))
    return approved


def head_content(year: int) -> str | None:
    """读取 git HEAD 中某年数据文件内容；文件不存在时返回 None。"""
    out = subprocess.run(
        ["git", "show", f"HEAD:data/{year}.json"],
        capture_output=True,
        text=True,
        cwd=workspace_path(),
    )
    return out.stdout if out.returncode == 0 else None


def detect_pending(years, approved=None, head_reader=None) -> list[int]:
    """返回需人工确认的年份：未放行、数据非空、且相对 HEAD 有变化。

    新年份公告首次解析没有真值与苹果日历兜底，是整条流水线唯一
    可能静默出错的环节，所以 hold 住等人工核对后再放行。
    """
    approved = load_approved() if approved is None else approved
    head_reader = head_reader or head_content
    pending = []
    for year in years:
        if year in approved:
            continue
        path = workspace_path("data", f"{year}.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            days = json.load(f).get("days", [])
        if not days:
            continue
        old = head_reader(year)
        old_days = json.loads(old).get("days", []) if old else []
        if old_days != days:
            pending.append(year)
    return pending


def summarize_days(days) -> list[str]:
    """把单日条目聚成「区间行」：连续同节日同真假合并为一行。"""
    import datetime as _dt

    groups: list[dict] = []
    for d in days:
        if groups:
            last = groups[-1]
            nxt = _dt.date.fromisoformat(last["end"]) + _dt.timedelta(days=1)
            if (
                last["name"] == d["name"]
                and last["isOffDay"] == d["isOffDay"]
                and nxt.isoformat() == d["date"]
            ):
                last["end"] = d["date"]
                last["n"] += 1
                continue
        groups.append(
            {
                "name": d["name"],
                "isOffDay": d["isOffDay"],
                "start": d["date"],
                "end": d["date"],
                "n": 1,
            }
        )
    lines = []
    for g in groups:
        span = g["start"] if g["start"] == g["end"] else f"{g['start']} ~ {g['end']}"
        kind = "放假" if g["isOffDay"] else "上班"
        tail = f"（{g['n']} 天）" if g["isOffDay"] and g["n"] > 1 else ""
        lines.append(f"- {g['name']} {kind} {span}{tail}")
    return lines


def render_pending(pending_years, layer: int) -> str:
    """生成待审报告：逐年摘要 + 公告原文链接 + 放行说明。"""
    parts = [
        "新年份数据已解析但被 hold（未提交、未上线），需人工确认。",
        "",
        "**放行方式**：核对下方摘要与公告原文一致后，把年份加入"
        "`data/approved.txt` 并提交推送，下次自动运行即照常发布。",
        f"（解析通道：layer{layer}；若与原文不符，请对照"
        "`docs/ARCHITECTURE.md` 运维手册修复 `scripts/govcn.py`）",
    ]
    for year in pending_years:
        with open(workspace_path("data", f"{year}.json"), encoding="utf-8") as f:
            data = json.load(f)
        parts.append("")
        parts.append(f"## {year} 年（共 {len(data.get('days', []))} 条）")
        parts.extend(summarize_days(data.get("days", [])))
        papers = data.get("papers", [])
        if papers:
            parts.append("")
            parts.append("公告原文：")
            parts.extend(f"- {url}" for url in papers)
    return "\n".join(parts) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, nargs="*", default=None)
    parser.add_argument(
        "--status-file", default=workspace_path("dist", "sync-status.txt")
    )
    parser.add_argument(
        "--pending-file", default=workspace_path("dist", "pending-review.txt")
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

    pending = detect_pending(years)
    if pending:
        content = render_pending(pending, layer)
        os.makedirs(os.path.dirname(args.pending_file), exist_ok=True)
        with open(args.pending_file, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"review: PENDING human approval for {pending}; workflow will hold")
    else:
        print("review: ok (no unapproved year changes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
