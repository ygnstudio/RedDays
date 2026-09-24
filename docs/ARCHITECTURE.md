# RedDays 架构与运维手册

## 模块地图

| 模块 | 职责 | 依赖 |
|---|---|---|
| `scripts/govcn.py` | gov.cn 搜索接口找通知 → 抽正文 → 两阶段定年解析中文句式为结构化假期数据 | requests, bs4 |
| `scripts/sync.py` | 数据同步编排：直连解析 + 快照降级 + 双重守卫，输出同步状态供 CI 判断 | 标准库（layer1 间接依赖 govcn.py） |
| `scripts/generate.py` | JSON → 双版本 ICS；RFC 5545 折行/转义自实现 | 纯标准库 |
| `scripts/crosscheck.py` | 拉苹果官方 cn_zh 日历，比对补班日集合（发布门禁） | 标准库 |
| `config.py` | 全部展示偏好：命名模板、补班时间、提醒、颜色、描述开关 | 无 |
| `publish.yml` | 编排整个链路并部署 GitHub Pages | 无 |

## 数据流

```
gov.cn 公告 ──Layer1 直连解析──┐
                              ├→ {year}.json → generate.py → dist/*.ics
本地 git 快照 ──Layer2 兜底────┘         │                     │
                                        ↓                     ↓
                              crosscheck(苹果官方)      GitHub Pages
                                        ↓                     ↓
                                   pytest 门禁          日历订阅刷新
```

发布节奏：UTC 23:30 / 11:30（北京 07:30 / 19:30）。历年公告在 10 月下旬到 12 月上旬发布，端到端最坏延迟约 12 小时。

## 降级设计

- Layer 1（主路径）：`govcn.py` 直连 gov.cn。接口会变（历史上改过至少两次），变了修这里
- Layer 2（兜底）：什么都不做，本地数据原样发布，旧数据仍然正确，只是停止追新
- 降级不拦发布：`dist/sync-status.txt` 记录本次层级，`degraded=yes` 时 CI 自动开 issue（按标题去重）
- 新鲜度守卫：`data/` 的 git 提交超 400 天就 exit 2，CI 失败并发邮件
- 季节性守卫：12 月起次年 `data/{year+1}.json` 必须非空，防的是 gov.cn 已发公告但解析失灵、本地快照健康地空跑一年的情况
- 守卫是唯一允许主动失败的路径，断更不能被悄悄放过

## 发布门禁（顺序执行，任一失败即不发布）

1. **生成守卫**：sync 前后各生成一次 ICS，数据变了而 ICS 没变 = 生成器坏 → fail
2. **新年份人审门禁**：未列于 `data/approved.txt` 的年份数据相对 HEAD 发生变化 → hold（不提交、不上线）并开 issue 附逐条摘要与公告原文链接；人工核对后把年份加入 approved.txt 推送，下次运行自动放行。这是唯一无真值、无苹果日历兜底的窗口。小模型自动校验试过并否决：Qwen3-1.7B 对 20 年公告回测仅 3/20，4B 会幻觉补班
3. **双源校验**：与苹果官方日历比对当年补班日集合（必须相等）+ 苹果休日 ⊆ 我们休日（苹果只标首日）
4. **测试**：37 项离线测试（2026 真值断言、确定性输出、UID 稳定、RFC 5545 合规）；1 项网络测试默认跳过（layer1 本身就是真集成测试）

## ICS 设计要点

- **UID**：`{YYYYMMDD}-{off|work}-{variant}@reddays`。数据与格式变更都不会改变身份，苹果日历刷新时原地更新事件，永不重复（UID 域名是事件身份，订阅者出现后冻结，永不更名）
- **DTSTAMP**：取数据中最新日期派生（非当前时间），保证输出确定性、可 diff
- **补班事件**：带 09:00-18:00 浮动本地时间 + `TRIGGER:-PT720M`（前一晚 21:00 提醒）
- **折行/转义**：按 RFC 5545 §3.1/§3.3.11 自实现；转义只作用于冒号后的 value，属性名与参数是结构（曾踩坑：把 `DTSTART;VALUE=DATE` 的结构性分号也转义导致解析异常）

## 数据口径

- 年份按**公告标题年份**归档：12 月发布的文件可能含次年 1 月日期（跨年元旦），逐日期比对时按日期分桶
- 「与周末连休」的普通周末不是法定节假日，数据不含
- `$schema`/`$id` 指向本仓库 `schema.json` 与 `data/{year}.json`

## 运维手册

**新年份公告发布后的放行流程**：公告发布后最坏 12 小时内自动运行会开「[bot] 新年份安排待人工确认」issue，附逐条摘要（放假区间/补班日/公告原文链接）。核对无误 → 把年份加入 `data/approved.txt` 提交推送，下次运行自动提交数据并上线；有出入 → 修复 `govcn.py` 后手工修正 `data/{year}.json` 再放行。issue 按标题去重，不会重复开。

**gov.cn 改版导致 Layer1 失败**：排查 `scripts/govcn.py`，最可能变动的三处是搜索接口参数（见 `find_notices`）、正文容器（`download_notice` 的 `UCAP-CONTENT`）和句式正则（`_RE_OFF/_RE_WORK/_RE_SHIFT`）；修复后跑 network 标记的真值对照测试（`pytest -m network`）确认 20 年数据仍逐日一致。修复前数据冻结在快照（照常发布旧数据 + 降级告警），可手工核对公告原文，临时往 `data/{year}.json` 补数据。

**手动补一年数据**：编辑 `data/{year}.json`，保持 `days[].{name,date,isOffDay}` 结构与 `papers[]` 出处，push 后 publish 流程自动重发布。

**修改日历长相**：只改 `config.py`；本地 `python scripts/generate.py --out dist` 预览，满意后 push。

**切换/重加订阅**：UID 稳定，删除重加订阅不会产生重复事件；历史数据保留全量（2007 起）无年限压力，唯一主动维护是每年 11 月公告发布后的自动追加。
