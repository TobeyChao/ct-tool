## 0. 手法映射（第二层绑定）

每个阶段对应《重构》的具体手法；实施时先精读该手法小节的「做法」再动手，
每一步完成即跑测试（所有步骤均在 `cd tool && pytest` 下执行）。

| 阶段 | 手法 | 出处 |
|---|---|---|
| A 死代码清理 | 移除死代码 8.9 | 参照 `references/refactorings/ch08.md` |
| B 重复小工具收敛 | 提炼函数 6.1；搬移函数 8.1 | 参照 `ch06.md` / `ch08.md` |
| C i18n 计数统一 | 函数组合成类 6.9；移除死代码 8.9 | 参照 `ch06.md` / `ch08.md` |
| D CLI 用例下沉 | 搬移函数 8.1；拆分阶段 6.11 | 参照 `ch08.md` / `ch06.md` |
| E 管道关注点分离 | 提炼函数 6.1；拆分阶段 6.11 | 参照 `ch06.md` |
| F binary_writer 收敛 | 函数组合成类 6.9；提炼函数 6.1 | 参照 `ch06.md` |
| G Accessor 模型化 | 拆分阶段 6.11；提炼函数 6.1 | 参照 `ch06.md` |

实施纪律：每步遵循「做法」的最小步骤清单；失败回退最近绿点换更小的步子；
每阶段收尾跑完整测试 + `git diff` 复核（见 design.md D9 / Migration Plan）。

## 1. 阶段 A：死代码清理

- [x] 1.1 删除 `csharp_accessor_generator.py` 中零调用的 `_BB_READ` /
      `_field_slot_index` / `_i18n_field_slot_index` / `_voffset`
      （移除死代码 8.9：已 grep 确认生成路径全部不使用）
- [x] 1.2 删除 `cache/state.py` 中零调用的 `get_cached_ids`（含 tests 亦无引用）
- [x] 1.3 删除 `json_writer.py` 中 `serialize_row` / `write_json` 从未被
      传入的 `exclude_server_only` 参数（JSON 产物行为不变）
- [x] 1.4 删除 `validate/errors.py` 中零调用的 `WorkspaceIssue.detail` 字段
- [x] 1.5 删除 `sync.py` 中未使用的 `load_source_file` import
      （函数本身保留，tests 在用）
- [x] 1.6 `pytest` 全绿，`git diff` 复核无无关改动

## 2. 阶段 B：重复小工具收敛

- [x] 2.1 `FieldDef.column_span()` 方法上移入 `schema/models.py`；
      `excel/reader.py` 与 `excel/template.py` 删除各自 `_column_span`
      （含 `reader.leaf_column_map` 内调用改为 `leaf.column_span()`；
      搬移函数 8.1）
- [x] 2.2 `schema/conventions.py` 的 `_resolve_flatc` 公开为
      `resolve_flatc_path()`；`export/flatc_runner.py` 复用并删除本地副本
- [x] 2.3 `sync.py` 删除 `_load_lang_file`，改用 `load_translation`
      （实现完全相同，内联函数 6.2）
- [x] 2.4 `excel/template.py` 新增共享生成器
      `iter_data_rows(path, header_rows) -> Iterator[tuple]` 产出表头下
      非空行（"非空" = 任一单元格 not None，与现判断一致）；
      `app/template.py::_has_data_rows` 改为 `any(...)` 短路
      （消除 app 层对 openpyxl 的直接依赖）；`update_template` 全量时
      再 `list(...)` 复用同一遍历
- [x] 2.5 `pytest` 全绿

## 3. 阶段 C：i18n 计数统一

- [x] 3.1 新增 `ct/export/i18n/counts.py`：`StatusCounts`
      （translated/missing/stale/orphan + total/progress）+ `count_entries()`
      （函数组合成类 6.9）
- [x] 3.2 `sync.py`：`TableSyncStats` 承载 `StatusCounts`（状态字段
      转发）；**保留 `created/updated`**（测试有断言，属有消费者统计）；
      `StatusCounts` 提供 `__add__`，`totals_by_lang()` 返回
      `dict[str, StatusCounts]`
- [x] 3.3 `status.py`：`TableCounts` / `LangCounts` 组合 `StatusCounts`，
      render 输出逐字不变
- [x] 3.4 `writer.py`：`report_stale_summary` 改用 `count_entries`，状态
      比较统一用 `LangStatus` 枚举（status.py 同样去字符串字面量）
- [x] 3.5 `pytest` 全绿（i18n 全部测试）

## 4. 阶段 D：CLI 用例下沉

- [x] 4.1 新增 `ct/app/status.py`：`StatusReport`（changed/drifted/
      untracked/missing）+ `compute_status(ws, cache)`，逻辑自
      `cli.status()` 整体搬移；CLI 只渲染，文本逐字不变
      （搬移函数 8.1）；新增 `tool/tests/app/test_compute_status.py` 直接单测
      `compute_status` 四类状态与顺序
- [x] 4.2 新增 `ct/export/i18n/compact.py`：`compact_i18n(...)` +
      `CompactSummary` + `CompactError`；`cli.i18n_compact` 改为只渲染，
      文本逐字不变（拆分阶段 6.11）；新增 `tool/tests/i18n/test_compact.py`
      直接单测 `compact_i18n`（dry_run / 移除 / 无 orphan / lang 非法）
- [x] 4.3 新增 `ct/app/i18n.py::read_i18n_rows`（自
      `cli._read_all_rows_for_sync` 搬移），返回 `ReadRowsResult`
      （rows_by_table + missing），CLI 渲染 `[warn]` 文本；
      `i18n_sync` 保留 `--table` 存在性校验，删除预过滤后的二次过滤，
      过滤职责归 `sync_all`（`table` 同时传给 `read_i18n_rows` 保证
      缺失警告范围一致）；新增 `tool/tests/app/test_i18n.py` 单测
      `read_i18n_rows`（含 missing 收集与顺序）
- [x] 4.4 `pytest` 全绿（status / i18n compact / i18n sync 的 CLI 文本
      断言保持不变）

## 5. 阶段 E：管道关注点分离 + 失败路径修复

- [x] 5.1 `JsonStep.run` 按关注点拆私有方法：`_export_changed_table` /
      `_reuse_unchanged_table` / `_write_json` / `_build_and_cache_bytes` /
      `_update_cache`，步骤序列与日志文本不变（提炼函数 6.1）
- [x] 5.2 `AccessorStep` 的生成器 import 移到模块顶部，删除
      `try/except ImportError`（失败直接暴露，不再静默）
- [x] 5.3 `ExportContext` 增加 `exported_tables`，取消时
      `tables_exported` 返回实际已导出表数；更新 `test_export_pipeline.py`
      并补中途取消测试（用两张表的项目，处理第一张后 cancel，
      断言 `tables_exported == 1`）
- [x] 5.4 `pytest` 全绿

## 6. 阶段 F：binary_writer 类型分派收敛

- [x] 6.1 槽位写入提炼 `_prepend_slot` + `_SCALAR_SLOT_WRITERS` 查表，
      `_build_struct` 与 `build_table_bytes` 共用（函数组合成类 6.9）
- [x] 6.2 `_build_array` 元素写入分派合并为 `_ELEMENT_VECTOR_WRITERS` 查表
- [x] 6.3 `reader.py` 的 `_coerce` / `_coerce_element` 提炼共享标量转换
      helper（注意两者 int 转换语义不同：Python 值与字符串两条路径，
      用参数区分或保留分层，行为逐字不变）
- [x] 6.4 补 `build_table_bytes` 固定 schema 的逐字节 golden 测试
      （schema 覆盖全部标量类型 + enum + string + array + struct；
      重构前先落快照到 `tests/fixtures/`；注释注明 flatbuffers
      库升级需重录）
- [x] 6.5 `pytest` 全绿（binary golden 验证零漂移）

## 7. 阶段 G：Accessor 生成器模型化

- [x] 7.1 补 C# / Lua 生成器 golden 特征测试：固定两个样例 schema
      （样例 A = i18n string + enum + array<int32> + server_only；
      样例 B = struct 含 int32 / string 子字段 + 普通标量），断言
      当前生成文本逐字一致（重构前先落快照到 `tests/fixtures/`）
- [x] 7.2 新增 `ct/export/accessor_model.py`：`AccessorModel` +
      `build_accessor_model()`，只含共享派生数据（client_fields /
      string_fields / i18n_fields / primary），**不含槽位索引**
      （拆分阶段 6.11）
- [x] 7.3 `csharp_accessor_generator.py` 改为消费 `AccessorModel`，
      golden 测试零漂移
- [x] 7.4 `lua_accessor_generator.py` 改为消费 `AccessorModel`，
      golden 测试零漂移
- [x] 7.5 `pytest` 全绿

## 8. 阶段 H：收尾

- [x] 8.1 全量 `pytest`（152 passed）+ `gd/` 真实数据导出验证
      （output 产物零变化，仅 cache/state.json 时间戳被导出更新，
      已恢复）+ `git diff` 复核无无关改动
- [x] 8.2 更新 `AGENTS.md` 模块表（新增 app/status、app/i18n、
      accessor_model、i18n/counts、i18n/compact；status/counts 职责
      拆清；excel/template 职责补全）；`tool/docs/README.md` 为纯
      用户文档、无模块说明，无需改动

## 9. 功能验证发现与修复（收尾阶段，全流程 CLI 验证）

- [x] 9.1 修复阶段 D 回归：`cli.py` 删除 `get_changed_tables` import 导致
      无参数增量导出 NameError；恢复 import 并补
      `test_export_incremental_without_flags` 测试
- [x] 9.2 修复既有缺陷：`ct export --table X` 时管道 `sync_all` 未传
      `table_filter`，误删其他表 i18n 文件（gd/ 真实数据复现并恢复）；
      `I18nSyncStep` 改传 `ctx.opts.table`，补
      `test_export_single_table_keeps_other_i18n_files` 回归测试
- [x] 9.3 修复既有缺陷：类型转换失败（如 int32 填 "abc"）在 reader
      coercion 崩溃输出 Python traceback，违反 Change 2 友好错误规格；
      coercion 失败返回原值、由校验器报结构化错误，补
      `test_validate_reports_type_mismatch_instead_of_traceback` 回归测试
- [x] 9.4 全流程验证通过：gd/ 真实数据 status / validate / i18n status /
      export（增量 / 全量 / 按表 / 按语言）产物零漂移；临时项目
      gen-template 决策矩阵、i18n sync/status/compact（dry-run/真实）、
      错误定位、错误路径退出码全部符合预期
- [x] 9.5 修复既有缺陷：增量导出时未变化表的 fbs_bytes 缓存缺失（被清理/
      损坏）时静默跳过导致 bundle 缺表；`_reuse_unchanged_table` 改为
      任一缓存缺失即重读 Excel 完整重建（补
      `test_incremental_export_rebuilds_missing_cache_bytes` 回归测试）
- [x] 9.6 修复既有缺陷：schema 加载错误（命名违规 / 重复表名 / 循环引用 /
      YAML 语法 / enum 值非法）裸抛 Python traceback；`cli._load_workspace`
      统一捕获转 `[error]` 友好提示，`repository` 捕获 YAMLError 并精简
      pydantic 错误文本（新增 `tool/tests/cli/test_schema_errors.py` 5 个测试）
- [x] 9.7 深测覆盖且通过：gen-template 决策矩阵全分支（legacy /
      hash 不同±数据 / force / update-header / table_name 不匹配）、i18n
      状态机（translated→stale→orphan→compact 生命周期、--lang 过滤）、
      数组元素与跨表引用校验定位、无 secondary / 无 i18n 表边界、
      flatc 缺失降级、Windows `.exe` 路径解析、翻译合并回退语义
- [x] 9.8 review 遗留修复：① `sync_all` 内部清理拆为独立
      `cleanup_i18n_files`（valid 基于**全量** schema），并保持"局部操作
      （--table）不清理"原语义——增量导出（部分表变化）与 `i18n sync
      --table` 均不再误删其他表文件（新增两个 CLI 回归测试）；②
      `extractor` 跳过主键类型不符的行（coercion 宽容契约补全，防垃圾
      source key）；③ 顺手：`_handle_unchanged_table` 改名、
      `_load_workspace` verbose 时保留 traceback、`_schema_error_text`
      改用 pydantic `ctx.error`（去掉对 msg 前缀的字符串依赖）
- [x] 9.9 多轮循环验证：3 轮完整用户工作流（全量导出 → 翻译 →
      增量导出 → 单表导出 → sync --table → 残留清理）全通过；专项
      循环（坏主键 sync 无垃圾 key、缓存缺失重建、schema 友好错误、
      校验失败不写产物）全通过；gd/ 全量导出仅清理小写历史残留
      （表名规范为大写），现存表文件无误删
