## Context

当前 `cli.py` 是唯一的编排层：约 580 行，把"加载配置 → 加载 schema → 解析 Excel →
校验 → i18n sync → 导出各产物 → 更新缓存"的全部流程与 Typer 参数、`print`/`logger`
输出耦合在一起。`export()` 与 `validate()` 各自重复实现"解析 + 校验"阶段。

关键现状（已核实）：

- `get_config()` 全局单例**零调用方**，可安全移除；
- `ct/export/i18n/*` 反向依赖 `ct/cli_helpers`（domain → interface 方向倒置）；
- `loader.py` 把"发现 YAML + 解析 YAML + 拓扑排序"焊死在一起；
- `fbs_generator.py` 内含隐性标准（后缀命名、容器结构、i18n 变体、DataBundle）；
- 校验错误以字符串 `format_error()` 传递，行号/列/当前值结构信息丢失；
- `flatc_runner.compile_fbs()` 返回 bool，但 `cli.py` 调用后**不检查返回值**（既有缺陷，本 change 只记录结果不改变行为）。

动机见 proposal.md。

## Goals / Non-Goals

**Goals:**

- 建立 interfaces → app → domain 单向分层，CLI 变为薄适配层；
- 以 `Workspace` 组合根替代全局单例；
- 结构化 Issue（双行号语义：`row_index` 保 CLI 文本逐字一致，`excel_row` 供未来面板）；
- 导出管道化：步骤 + 进度事件 + 取消点 + 结构化结果；
- `SchemaRepository` 抽象：canonical 模型唯一，YAML 为唯一实现，`fbs_sources()`
  返回 `dict[表名, fbs文本]`（为未来 .fbs 源留缝）；
- `FbsConvention` 显式化标准 + 检查器（"类型名与字段名不撞名"为不变量，
  后缀仅为 YAML 生成器策略）；
- 按《重构》原则小步推进：每个阶段独立可测、可提交，CLI 行为逐字不变。

**Non-Goals:**

- 不做任何界面实现（web server / HTML / 启动脚本）；
- 不改错误输出文本（行号增强属后续独立 change）；
- 不改 flatc 失败行为（继续静默记录，不改变退出码）；
- 不修"缓存键缺 schema hash"的既有缺陷（行为变更，独立 change）；
- 不实现 .fbs schema 源、不实现建表/改表/删表用例；
- 不改动 `schema_format` 之外的配置语义。

## Decisions

### D1. 分层与包结构：保留现有 domain 包名，新增 `ct/app`

```
ct/cli.py                 # 薄壳：Typer 参数 → app 用例 → presenter 渲染
ct/app/                   # 新增：应用层
  workspace.py            # Workspace 组合根（load：config + schemas 拓扑排序）
  events.py               # ProgressReporter / CancelToken / StepEvent
  export.py               # ExportPipeline + ExportStep + ExportResult
  validate.py             # run_validate()
  status.py               # compute_status()
  template.py             # 模板决策矩阵（自 cli_helpers 迁入）
  i18n.py                 # run_i18n_sync / status / compact
ct/schema/
  models.py               # 不变（canonical 模型）
  loader.py               # 只保留拓扑排序（格式无关）
  repository.py           # ★ SchemaRepository 协议 + YamlSchemaRepository + 工厂
  conventions.py          # ★ FbsConvention + validate_fbs_conventions()
  hashing.py / naming.py  # 不变
ct/export/i18n/io.py      # ★ 自 cli_helpers.i18n_json 迁入（dump_source_file/dump_lang_file）
```

**备选**：把现有包整体迁入 `ct/domain/` —— 否决：纯搬家带来大量 import 改动，
与"行为不变"目标冲突；现有 schema/excel/validate/export/cache 命名已表达职责。

### D2. Workspace 显式注入，删除全局单例

`get_config()` 零调用方，直接删除；所有用例第一个参数为 `Workspace`。
每个命令/请求按需 `Workspace.load(root)`（本地工具加载成本可忽略），
避免缓存陈旧问题（未来表格编辑后天然重新加载）。

### D3. Issue 分层与双行号

```python
class Issue:                          # 基类：table / code / message / to_dict()
class ValidationIssue(Issue):         # + row_index（现有文本行号）/
                                     #   excel_row（Excel 绝对行号）/
                                     #   column（0-based）/ value
class WorkspaceIssue(Issue):          # 缺文件、schema 加载错误等
```

`render()` 使用 `row_index` 复现现有文本（`[Item.xlsx] 第N行 字段：消息`）；
`excel_row` 本次只建模不消费（供 Change 2）。

### D4. 导出管道：步骤 + 事件 + 取消

```python
class ExportStep(Protocol):
    name: str
    def run(self, ctx: ExportContext) -> None: ...

class ProgressReporter(Protocol):
    def step_started(self, step: str): ...
    def step_finished(self, step: str): ...
    def log(self, line: str): ...

class CancelToken:
    def cancel(self) -> None: ...
    def raise_if_cancelled(self) -> None: ...
```

步骤：`ParseValidate → I18nSync → Json → Fbs → Flatc → Accessor → Bundle`；
取消点位于每步之间与每表之间；**被取消的导出不写 `state.json`**（fbs bytes
缓存文件幂等可覆盖），`ExportResult.cancelled=True`。

**备选**：单一 `run_export()` 过程函数 + 回调 —— 否决：回调散落、无法表达
步骤序列与取消检查点；步骤列表使"新增导出目标 = 新增一个步骤类"成立（开闭原则）。

### D5. SchemaRepository：窄协议 + fbs 文本返回

```python
class SchemaRepository(Protocol):
    def load_all(self) -> list[TableSchema]: ...
    def fbs_sources(self, schemas: list[TableSchema]) -> dict[str, str]: ...

def create_repository(schemas_dir: Path, fmt: str = "yaml") -> SchemaRepository: ...
```

- 返回**文本**而非路径：写盘与 flatc 由管道的 FBS 步骤负责，repository 不依赖
  产物目录（避免职责污染）；未来 .fbs 实现直接读源文件文本。
- **不声明 `save/delete/write_new`**：无调用方，属夸夸其谈通用性（YAGNI）；
  待表格管理 change 时再扩展。
- `global.yaml` 增加 `schema_format: yaml`（默认值），YamlSchemaRepository 由
  `loader.load_schemas()` 迁入，拓扑排序留在 loader。

### D6. FbsConvention：不变量与策略分离

- **不变量（检查器检查）**：任何类型名与任何字段名不得相同（flatc 拒绝）；
  容器结构（`{Table}Table` + `root_type`）、i18n 变体结构、
  DataBundle 结构、类型映射（`float→float32` 等）。
- **策略（YAML 生成器）**：`Enum/Struct/Elem` 后缀保证不变量，仅为当前实现手段，
  未来 .fbs 源可自由命名只要不撞名。
- `validate_fbs_conventions(text) -> list[Issue]`：结构检查 + flatc 编译校验
  （flatc 缺失时降级为结构检查并告警）。
- 现有 `fbs_generator.py` 生成逻辑迁入 YamlSchemaRepository 的 `fbs_sources()`
  （或独立适配模块），产物内容逐字不变。

### D7. cli_helpers 拆解与死代码清理

- `i18n_json` → `ct/export/i18n/io.py`（domain 内），修正反向依赖；
- `template_action` → `ct/app/template.py`（应用层）；
- 删除 `ct/cli_helpers/` 整个包与 `get_config()`。

### D8. 实施节奏：五阶段，每阶段独立绿

按《重构》"小步、行为不变"原则，Change 内五个连续阶段（对应 tasks.md）：

```
A 清死代码 + cli_helpers 搬家（纯搬移）
B Workspace + 引入参数对象（拆函数签名）
C 拆分阶段：抽出共享 ParseValidate
D 导出管道化（步骤/reporter/cancel，输出逐字一致）
E Issue 对象化 + SchemaRepository + FbsConvention（新抽象，render 逐字一致）
```

每阶段结束 pytest 全绿 + `git diff` 复核无无关改动；整个 change 完成时对
`gd/` 真实数据做一次 CLI 输出快照对比（重构前后逐字一致）。

## Risks / Trade-offs

- [行为漂移（重构最大的风险）] → 每阶段以现有 pytest 为安全网；E 阶段前补
  特征测试（characterization tests）固定错误文本与导出产物；完成时真实数据
  输出快照 diff。
- [fbs 文本迁移导致产物变化] → `fbs_sources()` 单测断言生成的 fbs 文本与
  当前 `fbs_generator` 输出逐字相同（golden test）。
- [取消导出留下不一致缓存] → 明确语义：取消不写 `state.json`，fbs bytes
  缓存幂等覆盖，bundle 不写；文档化并测试。
- [flatc 失败被静默（既有缺陷）] → FlatcStep 把 `success=False` 记入
  `ExportResult`（CLI 行为不变），供未来面板展示；是否让 CLI 失败退出为
  独立决策（见 Open Questions）。
- [Workspace 每操作加载的开销] → 本地小文件集，可忽略；换来"永不陈旧"。
- [阶段化带来临时中间态] → 每阶段是完整可工作状态（原则：任何时刻代码可用）。

## Migration Plan

1. 按 D8 五阶段顺序实施，每阶段独立提交；
2. 每阶段运行 `cd tool && pytest`，失败回退最近绿点换更小步；
3. 全部完成后：`ct status / export / validate / i18n *` 在 `gd/` 上做输出快照
   对比 + `git diff` 复核；
4. 回滚策略：按阶段提交逐个 revert（每阶段行为独立，无跨阶段耦合）。

## Open Questions

- flatc 编译失败时 CLI 是否应失败退出（改退出码）？→ 独立小 change 决策。
- "缓存键是否加入 schema hash"（既有缺陷修复）→ 独立行为变更 change。
- .fbs 作为 schema 源时的解析方式（轻量解析器 vs flatc 反射）→ 归 .fbs change。
- YAML schema 是否保留到 .fbs 化（演进文档遗留问题）→ 归 .fbs change。
