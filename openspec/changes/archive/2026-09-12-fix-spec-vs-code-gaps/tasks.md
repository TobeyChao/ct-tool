# Tasks: fix-spec-vs-code-gaps

## 1. 过滤取值校验（app 层，措辞沿用既有的 `表 'X' 不存在` / `语言 'X' 不在 secondary_langs 中`）

- [x] 1.1 `canonical_gen_template`：`--table` 不存在时报错（大小写不符时提示正确写法），不再静默处理 0 张表并 exit 0；验证 `ct gen-template --table Nope` 退出码非 0
- [x] 1.2 `canonical_i18n_sync`：新增 `lang_filter`（只写该语言的骨架，source 仍全量）、表存在性与 i18n 字段校验、语言校验；验证 `--lang zz` 退出码非 0 且不写文件
- [x] 1.3 `canonical_i18n_compact`：新增 `lang_filter` + 语言校验 + 表校验；验证 `--lang en` 只动 `i18n/en/`
- [x] 1.4 `canonical_export`：`lang_filter` 不在 `all_langs` 时报错；验证 `ct export --lang zz` 退出码非 0（此前静默导出 0 种语言）

## 2. CLI 渲染层（`ct/src/ct/cli.py`）

- [x] 2.1 `ct i18n sync`：转发 `--lang` / `--verbose`，异常转友好提示 + 退出码 1（不打印 traceback），输出汇总行
- [x] 2.2 `ct i18n status`：默认输出 `[en]  89% [█████████░] 170/190 translated, ...` 进度行；`--by-table` 追加逐表行；`--json` 只输出 `{"langs": {...}}`；`--lang` 校验
- [x] 2.3 `ct i18n compact`：转发 `--dry-run` / `--lang`（dry-run 绝不落盘），逐文件输出 `[compact] en/Item: 移除 N 条 orphan` / dry-run 的待删 key 列表 / `[compact] 无 orphan 条目，无需操作`
- [x] 2.4 三个 i18n 子命令的 `ValueError` / `FileNotFoundError` 统一转为 `[i18n ...] <msg>` + 退出码 1

## 3. `ct i18n sync` 的汇总与 verbose

- [x] 3.1 `canonical_i18n_sync` 统计新增/更新/stale/orphan，追加汇总 message `处理 N 张表 × M 语言：新增 a、更新 b、stale c、orphan d`；`verbose=True` 时逐文件 message `写入 i18n/en/Item.json（新增 2、更新 0、stale 0、orphan 0）`；返回类型保持 `list[str]`（web 调用方零改动）

## 4. 整数值域（解析校验阶段拦截越界）

- [x] 4.1 `type_expression.py` 新增整数值域表；`canonical_reader._coerce_scalar` 越界返回 `(raw, False)`；验证 `int32` 主键填 `5000000000` 时 `ct validate` 报 `期望 int32 类型`、`ct export` 在阶段 1 中止（两者都不再出现 `TypeError` traceback）

## 5. 主键类型收紧为 `int32`

- [x] 5.1 `type_expression.py` 新增 `PRIMARY_KEY_TYPE = "int32"`；`schema/resources.py` 按它校验并修正错误文案（原文案写「必须为 int32 或 int64」而实际检查的是 8 种整数标量）；验证 `int64` / `uint32` / `int8` 主键在加载阶段报错

## 6. schema 加载错误不再抛 traceback（验收时顺带发现，同属「规格 vs 代码」）

- [x] 6.1 抽出 `_friendly_exit(prefix, exc)`（DEBUG 时把堆栈写日志，即 `--verbose` 逃生门）；`ct validate` / `ct status` 包住 workspace 加载错误，`ct i18n sync|status|compact` 统一走同一路径；验证 `int64` 主键下 `ct validate`/`ct status` 输出 `[error] …` + 退出码 1 且无 `Traceback`

## 7. 测试

- [x] 7.1 新增用例覆盖：过滤取值被忽略（export/sync/compact/status/gen-template）、`compact --dry-run` 不落盘、`compact` 输出行格式、`status` 进度行与 `--json` 的 `langs` 结构、整数值域越界、非 `int32` 主键、schema 加载错误的友好报错（含 `--verbose` 堆栈）
- [x] 7.2 全量 `pytest ct/tests` 通过（基线 403 passed）

## 8. 文档同步

- [x] 8.1 同步 `ct/docs/README.md` 中受影响的两处（主键类型、整数越界行）；`README.md` / `AGENTS.md` 未涉及主键与值域表述，无需改动
- [x] 8.2 记录在案（不在本 change 范围）：`ct/src/ct/cache/artifacts.py` 的增量导出实现当时是**另一个并发会话的未提交工作**，故本 change 的 delta **不描述增量复用**（`incremental-export` / `web-panel` 的措辞留给那次实现），提交也只含本 change 的 hunk

## 9. 验收

- [x] 9.1 `openspec validate --all`（ct-tool 20/20 + 本 change）通过，归档后无未归档 change
- [x] 9.2 沙盒工程实测：`--lang zz` 系列退出码非 0、`compact --dry-run` 文件未被改、`status --json` 带 `langs`、`gen-template --table Nope` 非 0、越界主键在 validate 阶段报错、`int64` 主键在加载阶段友好报错
- [x] 9.3 暂存内容隔离验证：把 index 物化到 `/tmp/idxcheck` 后跑全量测试（**437 passed**），确认本提交不依赖那次未提交的增量导出实现
