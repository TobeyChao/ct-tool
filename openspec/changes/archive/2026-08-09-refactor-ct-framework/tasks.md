## 0. 手法映射（第二层绑定）

每个阶段对应《重构》的具体手法；实施时先精读该手法小节的「做法」再动手，
每一步完成即跑测试（所有步骤均在 `cd tool && pytest` 下执行）。

| 阶段 | 手法 | 出处 |
|---|---|---|
| A 清死代码/搬家 | 移除死代码 8.9；搬移函数 8.1 | 参照 `references/refactorings/ch08.md` |
| B Workspace/参数对象 | 引入参数对象 6.8；函数组合成类 6.9 | 参照 `references/refactorings/ch06.md` |
| C 共享解析校验 | 拆分阶段 6.11；提炼函数 6.1 | 参照 `references/refactorings/ch06.md` |
| D 导出管道化 | 拆分阶段 6.11；以命令取代函数 11.9；引入参数对象 6.8；函数组合成变换 6.10；将查询函数和修改函数分离 11.1 | 参照 `ch06.md` / `references/refactorings/ch11.md` |
| E Issue/Repository/Conventions | 以对象取代基本类型 7.3；搬移函数 8.1；改变函数声明 6.5 | 参照 `references/refactorings/ch07.md` / `ch08.md` / `ch06.md` |

实施纪律：每步遵循「做法」的最小步骤清单；失败回退最近绿点换更小的步子；
每阶段收尾跑完整测试 + `git diff` 复核（见 design.md D8）。

## 1. 阶段 A：死代码清理与 cli_helpers 拆解

- [x] 1.1 将 `ct/cli_helpers/i18n_json.py` 迁至 `ct/export/i18n/io.py`，更新
      `extractor.py` / `sync.py` / `cli.py` 的 import，删除原文件
      （搬移函数 8.1：先复制到目标、源函数改委托、再删源）
- [x] 1.2 将 `ct/cli_helpers/template_action.py` 迁至 `ct/app/template.py`，
      更新 `cli.py` import，删除原文件（搬移函数 8.1）
- [x] 1.3 删除 `get_config()` 单例与整个 `ct/cli_helpers/` 包
      （移除死代码 8.9：先确认零调用点再删）
- [x] 1.4 `pytest` 全绿，`git diff` 复核无无关改动

## 2. 阶段 B：Workspace 组合根与参数对象

- [x] 2.1 新增 `ct/app/workspace.py`：`Workspace.load(root)` 组装 config +
      拓扑排序后的 schemas + schema_map，替代 `cli.py` 中重复的
      `load_config` / `load_and_sort_schemas` 片段
      （函数组合成类 6.9：把结伴数据收进 Workspace）
- [x] 2.2 新增 `ExportOptions` 参数对象（all_tables / table / lang / verbose）
      （引入参数对象 6.8：先建值对象、改函数声明、逐调用点替换）
- [x] 2.3 `cli.py` 各命令改为先构建 `Workspace` 再访问路径（cfg.resolve 统一
      走 Workspace），暂不抽取用例函数
- [x] 2.4 `pytest` 全绿

## 3. 阶段 C：共享解析校验阶段

- [x] 3.1 新增 `ct/app/validate.py`：抽取公共解析阶段（读 Excel + 类型校验 +
      引用校验 + id_sets 收集），返回结构化结果
      （拆分阶段 6.11：先提炼第二阶段、引入中转数据结构、逐参数归位）
- [x] 3.2 `export()` 与 `validate()` 改用共享阶段，删除重复编排代码
- [x] 3.3 `pytest` 全绿（现有 CLI 测试全部通过）

## 4. 阶段 D：导出管道化

- [x] 4.1 新增 `ct/app/events.py`：`ProgressReporter` / `CancelToken` 协议
- [x] 4.2 新增 `ct/app/export.py`：`ExportStep` 协议 + `ExportResult` +
      `ExportPipeline`（ParseValidate → I18nSync → Json → Fbs → Flatc →
      Accessor → Bundle）
      （拆分阶段 6.11 + 以命令取代函数 11.9：复杂函数包成命令对象、
      字段共享中间状态；95% 场景不用命令，此处因步骤生命周期/取消点成立）
- [x] 4.3 新增 CLI presenter（`CLIProgressReporter`），复现现有日志文本
      （`[parse]` / `[json]` / `[skip]` / 汇总）逐字一致
- [x] 4.4 取消语义：取消点位于步与步/表与表之间；被取消的导出不写
      `state.json`；`FlatcStep` 记录 `compile_fbs()` 返回值到
      `ExportResult`（CLI 行为不变）
- [x] 4.5 `pytest` 全绿 + `gd/` 真实数据导出输出快照与重构前逐字对比

## 5. 阶段 E：Issue 对象化 + SchemaRepository + FbsConvention

- [x] 5.1 改造 `ct/validate/errors.py`：`Issue` 基类 + `ValidationIssue`
      （row_index / excel_row / column / value）+ `WorkspaceIssue`；
      `render()` 复现现有错误文本逐字一致；`validate/types.py` 与
      `validate/refs.py` 改为返回 issue 对象
      （以对象取代基本类型 7.3：先封装变量、建小类、取值函数改调、
      明确值对象语义）
- [x] 5.2 新增 `ct/schema/repository.py`：`SchemaRepository` 协议 +
      `create_repository()` + `YamlSchemaRepository`（`loader.load_schemas`
      迁入）；`GlobalConfig` 增加 `schema_format: yaml` 默认字段；
      `loader.py` 只保留拓扑排序
      （搬移函数 8.1 + 改变函数声明 6.5：load 逻辑迁入适配器，签名收敛）
- [x] 5.3 新增 `ct/schema/conventions.py`：`FbsConvention`（类型映射、容器 /
      i18n 变体 / DataBundle 结构、撞名不变量）+ `validate_fbs_conventions()`
      （结构检查 + flatc 编译校验，flatc 缺失降级为结构检查）
- [x] 5.4 fbs 生成逻辑迁入 YAML 适配器 `fbs_sources()`（返回
      `dict[表名, fbs文本]`），FBS 步骤负责写盘 + flatc；golden test 断言
      生成文本与现有 `fbs_generator` 产物逐字相同
      （搬移函数 8.1：生成逻辑整体搬入适配器，纯委托过渡）
- [x] 5.5 补充特征测试：错误文本快照、导出产物快照、conventions 检查器
      （撞名拦截 / 合法通过）
- [x] 5.6 `pytest` 全绿 + `gd/` 真实数据 CLI 输出快照对比 + `git diff` 复核
- [x] 5.7 更新 `AGENTS.md` 模块表与 `tool/docs/README.md` 中涉及的模块说明
