## MODIFIED Requirements

### Requirement: Status reporting
`ct i18n status` 命令 SHALL 计算并展示每语言每表的翻译进度。

支持三种渲染模式：
- 默认：每语言一行汇总（进度百分比 + 状态计数）
- `--by-table`：每语言每表一行（便于定位翻译瓶颈）
- `--json`：机器可读 JSON，供 CI 解析

进度百分比 SHALL 为 `translated / (total - orphan)`：orphan 是 source 中已不存在的残留条目（由 `compact` 清理），不计入分母；无活跃条目视为 100%。JSON 的 `total` 仍是四态之和（含 orphan），`progress` 是不含 orphan 的分母比值。

#### Scenario: Default summary shows per-language progress
- **WHEN** 执行 `ct i18n status`
- **THEN** 每个 secondary_lang 输出一行：进度百分比、10 格进度条、`translated/(total - orphan)` 分数，以及 translated/missing/stale/orphan 的计数

#### Scenario: By-table breakdown
- **WHEN** 执行 `ct i18n status --by-table`
- **THEN** 每个 (lang, table) 组合输出一行，便于查看哪张表翻译落后

#### Scenario: JSON output for CI
- **WHEN** 执行 `ct i18n status --json`
- **THEN** 输出结构化 JSON，包含每语言每表的四态计数与总进度，stdout 不含其他文本

#### Scenario: Filter by language
- **WHEN** 执行 `ct i18n status --lang en`
- **THEN** 只输出 en 的进度报告，忽略其他语言
