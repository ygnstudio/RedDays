"""重写 README 的「数据维护状态」区块（标记对之间的内容）。

由 publish workflow 在每次同步后运行：范围与时间全部实时读取，
数据变化时随 chore(sync) 提交一起更新，README 无需人工维护。
"""

import json
import os
import subprocess
import sys
import datetime as dt

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from paths import workspace_path  # noqa: E402

START = "<!-- data-status:start -->"
END = "<!-- data-status:end -->"


def _nonempty_years() -> list[int]:
    years = []
    for f in os.listdir(workspace_path("data")):
        if not f.endswith(".json"):
            continue
        with open(workspace_path("data", f), encoding="utf-8") as fh:
            if json.load(fh).get("days"):
                years.append(int(f[:4]))
    return sorted(years)


def _hk_years() -> list[int]:
    return sorted(
        int(f[:4])
        for f in os.listdir(workspace_path("data", "hk"))
        if f.endswith(".json")
    )


def _last_sync() -> str:
    out = subprocess.run(
        ["git", "log", "-1", "--format=%cI", "--", "data/"],
        capture_output=True,
        text=True,
        cwd=workspace_path(),
    )
    line = out.stdout.strip()
    return line[:10] if line else dt.date.today().isoformat()


def build_block() -> str:
    today = dt.date.today()
    cn = _nonempty_years()
    hk = _hk_years()
    with open(workspace_path("data", "losar.json"), encoding="utf-8") as f:
        losar_years = sorted(int(y) for y in json.load(f)["losar"])
    lines = [
        f"截至 {dt.date.today().isoformat()}（此节由 `scripts/readme_status.py` 自动生成）：",
        "",
        f"- **最近维护**：{_last_sync()}。GitHub Actions 每日对照官方来源同步数据，"
        "历法类每日滚动生成，平时无需人工。",
        "- **数据范围**：",
        f"  - 大陆法定节假日：{cn[0]}-{cn[-1]} 年（`data/*.json`）",
        f"  - 香港公众假期：{hk[0]}-{hk[-1]} 年（`data/hk/*.json`，1823 官方 JSON）",
        "  - 节气农历、回历每日、民族节日、基督教历：滚动窗口，"
        f"近 1 年加未来 2 年（当前 {today.year - 1}-{today.year + 2} 年）",
        f"  - 每日黄历：滚动窗口，当年加次年（当前 {today.year}-{today.year + 1} 年）",
        f"  - 藏历新年：Phugpa 参考实现生成，覆盖 {losar_years[0]}-{losar_years[-1]} 年"
        "（`data/losar.json`，2000-2030 与 Janson 论文 Table 9 逐年一致）",
        "- **新年份数据**：公告发布后自动解析、机器校验（天数区间与同比偏差）通过即上线，"
        "校验不过则拦下发布并开告警 issue。",
        f"- **下一次更新**：大陆 {today.year + 1} 年放假安排预计 {today.year} 年 10-12 月"
        "公告发布后自动上线；香港名单预计年末至次年初官方数据更新后自动同步；"
        "其余日历随每日运行自动推进窗口。",
        "",
    ]
    return START + "\n" + "\n".join(lines) + END + "\n"


def main() -> None:
    path = workspace_path("README.md")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if START not in text or END not in text:
        raise SystemExit("README.md is missing the data-status markers")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(head + build_block() + tail)
    print("readme: data-status block regenerated")


if __name__ == "__main__":
    main()
