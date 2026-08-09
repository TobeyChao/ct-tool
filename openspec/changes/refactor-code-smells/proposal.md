## Why

Change 1（ct 框架重构）/ Change 2（错误定位增强）之后 ct 框架已分层，但按
《重构》第一层诊断（24 种坏味道）重新扫描 `tool/ct/` 仍发现一批结构性坏味道：CLI 还残留编排与文件 IO、
`JsonStep` 一个步骤管四件事、字段类型分派链在 7 个模块重复、C#/Lua 访问器
生成器超长且双份平行实现、i18n 状态计数三处重复、若干重复小工具与死代码、
Accessor 步骤静默吞异常。这些直接抬高 Change 3 网页面板的复用成本——面板需要
status / compact / export 同一套用例接口，现在这些逻辑还埋在 CLI 展示层里。

## What Changes

纯重构：CLI 可观察行为逐字不变，现有 pytest 全绿为验收线；仅修复两处失败路径
缺陷（静默吞 ImportError、取消导出计数语义），正常路径行为不变。

- **用例下沉**：`ct status` 的模板漂移分类逻辑迁入 `ct/app/status.py`
  （返回结构化报告，CLI 只渲染）；`ct i18n compact` 的文件操作迁入
  `ct/export/i18n/compact.py`（与 sync 同属 i18n 领域操作，归 domain 层，
  返回 summary，CLI 只渲染）；sync 读表 `_read_all_rows_for_sync` 迁入
  `ct/app/i18n.py`，并清理 `i18n_sync` 的双重 table 过滤。
- **JsonStep 关注点分离**：JSON 写出 / fbs bytes 构建与缓存 / cache 更新 /
  未变化表复用拆成独立方法，步骤序列与日志文本不变。
- **binary_writer 类型分派收敛**：`_build_struct` 与 `build_table_bytes`
  的两份 if/elif 槽位写入链合并为查表；`_build_array` 元素分派同样查表；
  reader 的 `_coerce` / `_coerce_element` 共享标量转换 helper。
- **i18n 计数统一**：新增共享 `StatusCounts` + `count_entries()`；
  sync / status / writer 三处计数收敛，字符串字面量状态比较统一改用
  `LangStatus` 枚举。
- **Accessor 生成器模型化**：新增 `ct/export/accessor_model.py`（访问器模型：
  客户端字段 / i18n 字段 / 主键等两个生成器真正共享的派生数据），C# 与 Lua
  生成器消费同一模型，输出文本逐字不变（先补 golden 特征测试作安全网）。
- **重复小工具收敛**：`_column_span` 上移为 `FieldDef.column_span()`；
  `_resolve_flatc` 收敛为 `conventions.resolve_flatc_path()`；
  sync 的 `_load_lang_file` 复用 `load_translation`；
  模板"跳过表头找非空行"提炼为 `excel/template.py` 的共享
  `iter_data_rows`。
- **死代码清理**：删除 C# 生成器零调用的 `_BB_READ` / `_field_slot_index` /
  `_i18n_field_slot_index` / `_voffset`、`get_cached_ids`、`serialize_row` /
  `write_json` 的 `exclude_server_only` 参数、`WorkspaceIssue.detail`、
  sync 未使用的 `load_source_file` import。（`TableSyncStats.created/updated`
  经实施核实有测试消费者，保留，仅将其余状态计数收敛到 `StatusCounts`。）
- **失败路径修复**：`AccessorStep` 不再静默吞 `ImportError`（import 移模块
  顶部，失败直接暴露）；取消导出时 `ExportResult.tables_exported` 反映实际
  已导出表数（CLI 无取消入口，行为不可观察）。
- **功能验证发现的修复**（阶段 H 收尾验证时发现并修复）：① 阶段 D 下沉
  status 时误删 `get_changed_tables` import 导致无参数增量导出 NameError
  （回归，已修复并补增量导出测试）；② 既有缺陷——`ct export --table X`
  时管道 `sync_all` 未传 `table_filter`，会误删其他表的 i18n 文件（已修复
  并补回归测试）；③ 既有缺陷——Excel 单元格类型与 schema 不符时 reader
  coercion 崩溃输出 Python traceback，违反 Change 2 的友好错误定位规格
  （coercion 失败改为返回原值，由校验器报结构化错误，已补 CLI 回归测试）；
  ④ 既有缺陷——增量导出时未变化表的 fbs_bytes 缓存缺失会静默丢表
  （`_reuse_unchanged_table` 改为任一缓存缺失即重读重建，已补回归测试）；
  ⑤ 既有缺陷——schema 加载错误（命名违规 / 重复表名 / 循环引用 / YAML
  语法 / enum 值非法）裸抛 Python traceback（`cli._load_workspace` 统一
  转友好提示 + `repository` 捕获 YAMLError 并精简错误文本，新增 5 个测试）；
  ⑥ 既有缺陷（review 深化）——`sync_all` 的残留清理 valid 基于本次处理
  子集，部分表变化的增量导出也会误删其他表 lang 文件；清理拆为独立
  `cleanup_i18n_files`（valid 基于全量 schema），并保持"局部操作不清理"
  原语义；⑦ coercion 宽容契约补全——`extractor` 跳过主键类型不符的行，
  避免垃圾 source key 混入 i18n 文件。

## Capabilities

### New Capabilities

（无 —— 行为不变，按规则不发明需求）

### Modified Capabilities

（无 —— 纯重构，`.openspec.yaml` 已设置 `skip_specs: true`）

## Impact

- **改动代码**：`tool/ct/cli.py`（再变薄）、`tool/ct/app/export.py`、
  `tool/ct/export/binary_writer.py`、`tool/ct/export/csharp_accessor_generator.py`、
  `tool/ct/export/lua_accessor_generator.py`、`tool/ct/export/i18n/*`、
  `tool/ct/excel/reader.py`、`tool/ct/excel/template.py`、
  `tool/ct/schema/models.py`、`tool/ct/schema/conventions.py`、
  `tool/ct/app/template.py`、`tool/ct/cache/state.py`。
- **新增代码**：`tool/ct/app/status.py`、`tool/ct/app/i18n.py`、
  `tool/ct/export/i18n/compact.py`、`tool/ct/export/i18n/counts.py`、
  `tool/ct/export/accessor_model.py`；对应测试：
  `tool/tests/app/test_compute_status.py`、`tool/tests/app/test_i18n.py`、
  `tool/tests/i18n/test_compact.py`、`tool/tests/export/test_accessor_golden.py`、
  `tool/tests/export/test_binary_golden.py` + `tool/tests/fixtures/`。
- **删除**：`get_cached_ids`、`_BB_READ`、`_field_slot_index`、
  `_i18n_field_slot_index`、`_voffset`、`exclude_server_only` 参数、
  `WorkspaceIssue.detail`。
- **依赖**：无新增、无移除；Python 版本要求不变。
- **接口**：CLI 命令 / 参数 / 输出格式不变；无外部 API。
