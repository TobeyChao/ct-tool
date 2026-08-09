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

- [ ] 4.1 新增 `ct/app/status.py`：`StatusReport`（changed/drifted/
      untracked/missing）+ `compute_status(ws, cache)`，逻辑自
      `cli.status()` 整体搬移；CLI 只渲染，文本逐字不变
      （搬移函数 8.1）；新增 `tool/tests/app/test_status.py` 直接单测
      `compute_status` 四类状态与顺序
- [ ] 4.2 新增 `ct/export/i18n/compact.py`：`compact_i18n(...)` +
      `CompactSummary` + `CompactError`；`cli.i18n_compact` 改为只渲染，
      文本逐字不变（拆分阶段 6.11）；新增 `tool/tests/i18n/test_compact.py`
      直接单测 `compact_i18n`（dry_run / 移除 / 无 orphan / lang 非法）
- [ ] 4.3 新增 `ct/app/i18n.py::read_i18n_rows`（自
      `cli._read_all_rows_for_sync` 搬移），返回 `ReadRowsResult`
      （rows_by_table + missing），CLI 渲染 `[warn]` 文本；
      `i18n_sync` 保留 `--table` 存在性校验，删除预过滤后的二次过滤，
      过滤职责归 `sync_all`；新增 `tool/tests/app/test_i18n.py` 单测
      `read_i18n_rows`（含 missing 收集与顺序）
- [ ] 4.4 `pytest` 全绿（status / i18n compact / i18n sync 的 CLI 文本
      断言保持不变）

## 5. 阶段 E：管道关注点分离 + 失败路径修复

- [ ] 5.1 `JsonStep.run` 按关注点拆私有方法：`_export_changed_table` /
      `_reuse_unchanged_table` / `_write_json` / `_build_and_cache_bytes` /
      `_update_cache`，步骤序列与日志文本不变（提炼函数 6.1）
- [ ] 5.2 `AccessorStep` 的生成器 import 移到模块顶部，删除
      `try/except ImportError`（失败直接暴露，不再静默）
- [ ] 5.3 `ExportContext` 增加 `exported_tables`，取消时
      `tables_exported` 返回实际已导出表数；更新 `test_export_pipeline.py`
      并补中途取消测试（用两张表的项目，处理第一张后 cancel，
      断言 `tables_exported == 1`）
- [ ] 5.4 `pytest` 全绿

## 6. 阶段 F：binary_writer 类型分派收敛

- [ ] 6.1 槽位写入提炼 `_prepend_slot` + `_SCALAR_SLOT_WRITERS` 查表，
      `_build_struct` 与 `build_table_bytes` 共用（函数组合成类 6.9）
- [ ] 6.2 `_build_array` 元素写入分派合并为 `_ELEMENT_VECTOR_WRITERS` 查表
- [ ] 6.3 `reader.py` 的 `_coerce` / `_coerce_element` 提炼共享标量转换
      helper（注意两者 int 转换语义不同：Python 值与字符串两条路径，
      用参数区分或保留分层，行为逐字不变）
- [ ] 6.4 补 `build_table_bytes` 固定 schema 的逐字节 golden 测试
      （schema 覆盖全部标量类型 + enum + string + array + struct；
      重构前先落快照到 `tests/fixtures/`；注释注明 flatbuffers
      库升级需重录）
- [ ] 6.5 `pytest` 全绿（binary golden 验证零漂移）

## 7. 阶段 G：Accessor 生成器模型化

- [ ] 7.1 补 C# / Lua 生成器 golden 特征测试：固定两个样例 schema
      （样例 A = i18n string + enum + array<int32> + server_only；
      样例 B = struct 含 int32 / string 子字段 + 普通标量），断言
      当前生成文本逐字一致（重构前先落快照到 `tests/fixtures/`）
- [ ] 7.2 新增 `ct/export/accessor_model.py`：`AccessorModel` +
      `build_accessor_model()`，只含共享派生数据（client_fields /
      string_fields / i18n_fields / primary），**不含槽位索引**
      （拆分阶段 6.11）
- [ ] 7.3 `csharp_accessor_generator.py` 改为消费 `AccessorModel`，
      golden 测试零漂移
- [ ] 7.4 `lua_accessor_generator.py` 改为消费 `AccessorModel`，
      golden 测试零漂移
- [ ] 7.5 `pytest` 全绿

## 8. 阶段 H：收尾

- [ ] 8.1 全量 `pytest` + `gd/` 真实数据 CLI 输出快照对比 +
      `git diff` 复核无无关改动
- [ ] 8.2 更新 `AGENTS.md` 模块表与 `tool/docs/README.md` 中涉及的
      模块说明
