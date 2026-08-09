## Why

ct 的核心编排逻辑全部堆在 `cli.py`（约 580 行），与 Typer 参数和 `print` 输出耦合，
导致同一个流程（导出/校验/i18n）无法被复用，也无法支撑规划中的本地网页面板；
同时 schema 源被 YAML 焊死、fbs 结构规范散落在生成器代码里，阻碍工具演进为
"多界面 + 多 schema 源"的框架。需要先做一次行为不变的结构重构，为后续
网页面板、错误定位增强、.fbs schema 源铺平地基。

## What Changes

纯重构，CLI 可观察行为逐字不变，现有 pytest 全绿为验收线。

- **新增应用层 `ct/app/`**：`Workspace` 组合根（root + config + 拓扑排序后的 schemas，
  替代模块级 `_cfg` 单例）；用例函数 `run_export / run_validate / compute_status /
  apply_template_action / run_i18n_*`，每个用例返回结构化结果，不再 `print`。
- **结构化 Issue 模型**：`Issue` 基类 + `ValidationIssue`（含 Excel 绝对行号 `excel_row`、
  列索引、当前值）与 `WorkspaceIssue`（缺文件/schema 加载错误）；`render()` 保持现有
  错误文本逐字一致，`to_dict()` 供未来 JSON 输出。
- **导出管道化**：`ExportStep` 步骤（解析校验 → i18n sync → JSON → FBS → flatc →
  Accessor → Bundle）+ `ProgressReporter` 事件 + `CancelToken` 取消点 +
  `ExportResult` 结构化结果；取消只在步与步/表与表之间生效，被取消的导出不写
  `state.json`。
- **SchemaRepository 可插拔源**：`load_all()` 与 `fbs_sources()`（返回
  `dict[表名, fbs文本]`）抽象；YAML 为唯一实现（现有 loader 迁入）；`global.yaml`
  新增 `schema_format: yaml` 默认字段（现有项目零改动）。
- **FbsConvention 标准模块 + 检查器**：类型映射、容器/i18n/DataBundle 结构、
  "类型名与字段名不撞名"不变量（后缀只是 YAML 生成器的策略）；检查器
  `validate_fbs_conventions()` 对生成的 .fbs 做结构 + flatc 编译校验。
- **清理与迁移**：`cli_helpers` 拆解（`i18n_json` → `ct/export/i18n/io.py`，
  `template_action` → `ct/app/template.py`）后删除；移除零调用方的 `get_config()`
  单例；修正 domain 层对 `cli_helpers` 的反向依赖。

## Capabilities

纯重构：CLI 可观察行为不变，无 spec 级行为变更，`.openspec.yaml` 已设置
`skip_specs: true`，不新增/修改任何 capability。

### New Capabilities

（无 —— 行为不变，按规则不发明需求）

### Modified Capabilities

（无）

## Impact

- **改动代码**：`tool/ct/cli.py`（变薄壳）、`tool/ct/config.py`（去单例）、
  `tool/ct/schema/loader.py`（拆出 repository）、`tool/ct/export/i18n/*`（依赖修正）、
  `tool/ct/export/fbs_generator.py`（逻辑迁入 conventions/YAML 适配器）。
- **新增代码**：`tool/ct/app/`（workspace/export/validate/status/template/i18n）、
  `tool/ct/schema/repository.py`、`tool/ct/schema/conventions.py`、
  `tool/ct/export/i18n/io.py`。
- **删除**：`tool/ct/cli_helpers/` 整个包、`get_config()`。
- **依赖**：无新增、无移除；Python 版本要求不变。
- **接口**：CLI 命令/参数/输出格式不变；无外部 API。
