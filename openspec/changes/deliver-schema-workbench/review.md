# Review: deliver-schema-workbench

- 评审日期：2026-09-01
- 评审对象：`openspec/changes/deliver-schema-workbench/`（proposal / design / tasks / 12 份 delta spec）
- 对照基准：`openspec/specs/` 下主 spec（schema-management、excel-processing、flatbuffers-export、web-panel、json-export、data-validation、incremental-export、i18n-pipeline）
- 处理状态：2026-09-01 已完成规格补强并通过 strict validation；第 3 节保留为原始评审记录。
- 结论：**原评审有实质价值；H1–H3 与 M/L 级有效项已吸收，并额外补上共享类型的传递缓存失效和 FBS 文件归属两个遗漏。**

---

## 0. 评审处理结果

- H1：首版明确禁止 Record 字段声明 `i18n` 或 `server_only`；i18n 仅允许 Table 顶层 string，避免为 `vector<Record>` 发明不稳定的下标 key。
- H2：新增 `json-export` 与 `incremental-export` delta；JSON 使用 Record/Enum/vector 术语，增量导出改用包含传递类型依赖的 `export_fingerprint`。
- H3：`Load schema from YAML files` 已 MODIFY 为 Table 从 `config/schemas`、Record/Enum 从 `config/types` 加载并共享统一命名域。
- M1–M6：查询采用解析后的精确字符串且不归一化；整数主键不变；i18n 字段禁止建索引；Playwright 进入 Python/CI 测试基建；Enum wire type 固定 `byte`。
- L1/L3/L5：补入 Windows Office 文件占用预检、IndexedDB Draft 与默认两小时 plan TTL；L4 仅为路径提示，不进入设计约束。L2 曾被吸收，后续按真实资产规模复核后撤销产品级迁移入口。
- 新增 H4：共享 Record/Enum 变化沿反向依赖使全部受影响 Table fingerprint 失效，禁止复用旧 Binary bytes。
- 新增 H5：共享 Record/Enum 统一生成到唯一 `types.fbs`，Table schema 只 include，不复制定义。
- 新增 H6：原单一 export fingerprint 漏掉逐语言 i18n 输入；改为 schema/data/i18n-per-lang/bundle 分层 fingerprint，翻译变化只失效对应语言产物。
- 后续结构复核：针对现有 `web/app.py`、`app.js`、`app/export.py` 与 repository 职责膨胀风险，新增单向依赖、query/command 分离、持久化/生成分离、AST architecture test 和旧总控代码退场门。
- 后续范围精简：仓库只有 4 份 Schema、4 个小型 Excel，旧复杂类型仅 2 个内联 Enum、1 个 struct、1 个 array；删除迁移 CLI、Web 升级页、兼容 reader/writer 与迁移 application module，改为一次可审查的仓库切换提交。

---

## 1. 总体结论

这是一个"交付型"大型变更：canonical model 重写（Type Expression + Table/Record/Enum 资源）→ 一次性仓库配置切换 → Workspace Draft / Change Plan / 原子 Apply 事务 → Web 全量改版（AppShell + 3/2/1 栏自适应 + 资源发现 + 虚拟列表）→ 导出/i18n/日志/历史全模块视觉改版 → 浏览器验收矩阵。体量很大，但设计中的分阶段与完成门（任务 1.2 / 13.6）能控制长期半成品风险。

评审结论：**规格补强后可进入实现；实现顺序仍应从 canonical model、仓库切换 golden 和传递 fingerprint 开始。**

---

## 2. 做得好的地方

### 2.1 决策都有理由与取舍
Design Decisions 1–11 每个都给出了方案选择的依据：
- YAML 用受控字符串而非嵌套对象（配置可读、仓库切换 diff 紧凑）；Web API 用结构化 JSON（前端无权决定解析/序列化规则）。
- `config/types/*.yaml` 而非统一迁入 `config/resources/`（不破坏既有 CLI 路径约定与用户仓库结构）。
- journal + 同文件系统 staging 而非整目录原子替换（工作区可能很大且含用户未纳入管理的文件）。

### 2.2 正确性边界定义清晰
- 查询索引：hash 只定位候选桶，命中后必做精确原字符串比较（design 7 / query-indexes spec）。
- schema hash 只用于漂移/并发检测，关键查询正确性不依赖 hash 相等（excel-processing MODIFIED）。
- `excel_columns` 只影响 Excel 录入布局，不改 FlatBuffers wire type（flatbuffers-export ADDED + task 5.9 专门验收 wire contract 不变）。

### 2.3 交互决策收敛干净
- side area 仅 `activeTool/null` 两态，无 hidden/collapsed/overlay 组合态；无 pane 横向移出屏幕动画。
- 单一虚拟列表路径（无 `count > 200` 切换实现）。
- 路由与布局投影完全分离，断点变化不改 route / selection / Draft / scroll（design 9）。
- `<960px` 用语义 row layout，不通过 CSS 压扁桌面表格。
- 与 `ct/docs/TODO/` 下的  原型（schema-editor-prototype.html）和调研（responsive-three-pane / resource-discovery / commercial-workbench）方向一致。

### 2.4 仓库切换 / 回滚 / 失败恢复完备
- golden 基线 → 直接转换 4 Schema/4 Excel/fixtures → 人工单元格核对与产物对拍；运行期 Apply 继续由 journal、启动恢复和字节级一致性验收保护（task 13.2）。
- 明确"回滚必须同时恢复 Schema/type/Excel/output，不能只回退前端"（旧 writer 不理解新格式）。

### 2.5 任务可验证性高
- 绝大多数任务带 verify 子句；14 个任务节覆盖 5 个新增能力 + 7 个修改能力的 delta。

---

## 3. 需要处理的问题

### 3.1 高优先级（会阻塞同步主 spec / 评审）

#### H1. i18n × Record / vector\<record\> 的交叉语义完全空白
- 现状：i18n 管线是扁平 `{id}.{field}` key（主 spec i18n-pipeline；`ct/export/i18n/extractor.py`）。
- 问题：新模型把 Record 提升为一等资源并支持 `vector<record>`（type-system spec），但 **Record 内 string 叶子若标 `i18n`，source key 格式、Excel 展开下的路径、merge 规则全未定义**，也未显式禁止。
- 现有约束（`i18n` 仅限 string；`i18n` 与 `server_only` 互斥）在 schema-management delta 中未被重复/更新，覆盖不到嵌套场景。
- 影响：task 5.4 "preserve i18n/server-only behavior" 会悬空，实现者无从下手。
- 建议（二选一）：
  - (a) 定义嵌套 key 格式（如 `1001.Rewards.DropName`；vector 需含组下标）并补 extractor/merger 场景；
  - (b) v1 显式禁止 Record 内 i18n，加校验 + 对应任务。

#### H2. 主 spec 残留被删除的旧类型术语，本 change 未做 delta
- `array` 与内联 `struct` 已在本 change 的 schema-management delta 中被 REMOVED，但：
  - **json-export** 主 spec 的 "Serialize complex field types to JSON" 仍含 `Struct serialized as nested object`、`Array of primitives…`、`Array of enum…` 场景（术语已失效），本 change 没有任何文件 MODIFY/RENAME 它。
  - **incremental-export** 主 spec：design 决策 6 新增 `cache/template_layouts/` 并改变 hash 输入与 apply 后的缓存失效语义（Impact 也写了 "cache 状态受影响"），但无对应 delta。
- 建议：补 json-export 的 RENAMED/MODIFIED delta（struct→Record、array→vector，序列化语义不变只是正名）；在 incremental-export 补一小段缓存/增量语义说明。

#### H3. schema-management 主 spec 的加载要求未更新到新仓库布局
- design 决策 2：Table→`config/schemas/*.yaml`，Record/Enum→`config/types/*.yaml`。
- 但 delta 只**新增**了 "Load named schema resources"，未 MODIFY 主 spec 的 "Load schema from YAML files"（仍写"从 config/schemas/ 目录加载所有 \*.yaml"）。两要求并存且前者不覆盖后者，加载语义口径分裂。
- 建议：将加载要求 MODIFY 为"Table 从 config/schemas/、Record/Enum 从 config/types/ 加载"。

### 3.2 中优先级（语义歧义，建议一两句话钉死）

| # | 问题 | 位置 | 建议 |
|---|------|------|------|
| M1 | "规范化原字符串"规则未定义（trim? case-fold? NFKC?）；Code 预检"拒绝相同原字符串"未说明按原始串还是规范化串 | query-indexes / design 7 | 把规范化函数写成显式需求 + golden |
| M2 | 主键 int32/int64 限制（主 spec 未被修改、继续生效）与新增 Code 唯一索引的关系未澄清 | schema-management | 显式声明"主键类型限制不变，string 唯一性通过 Code 索引表达" |
| M3 | 被客户端表引用的 Record 若含 `server_only` 叶子，共享 Record 的客户端 FBS 如何处理 | type-system / flatbuffers-export | 定义排除规则或禁止该组合 |
| M4 | Code/Group 索引字段若为 i18n string，查询基于哪个语言版本 | query-indexes | 显式禁止 i18n 字段作索引字段（或定义以主语言为准） |
| M5 | 浏览器验收基建未落实（用什么驱动、在哪跑、是否进 CI） | tasks 1.3 / 13.3 | 明确 Playwright/WebDriver 选型与运行位置 |
| M6 | 命名 Enum 的 wire type 未定义（workbench 枚举编辑器要展示 "wire type"） | workbench / query-indexes | 确认是否仍固定 byte |

### 3.3 低优先级

| # | 问题 |
|---|------|
| L1 | Excel 被 Office 打开时 `os.replace` 在 Windows 会失败：需文件占用时的明确提示/降级（失败不落盘已被 spec 覆盖） |
| L2 | 一次性迁移入口的触发面未指明（后续基于资产规模复核后决定不实现产品级迁移入口） |
| L3 | 超大 workspace 下浏览器 store 的 Draft command log 可能触 localStorage 容量边界 |
| L4 | 目录名为 `deliver-schema-workbench`（比口头称呼多  后缀），实现时按实际路径引用 |
| L5 | plan token 的过期时长未定义（design 4 只说"带过期时间"） |

---

## 4. 交叉一致性核验

- **proposal ↔ design ↔ specs ↔ tasks 追溯**：补强后完整。14 个任务节覆盖 5 个新增能力 + 7 个修改能力，并为 Record 角色边界、共享 FBS、传递/逐语言 fingerprint、仓库切换、文件锁与浏览器基建新增验证任务。
- **新增能力清单**（proposal Capabilities）与 5 份 ADDED spec 文件一一对应：workbench / type-system / workspace-draft / query-indexes / web-panel-design-system。
- **修改能力清单**（schema-management / excel-processing / json-export / flatbuffers-export / incremental-export / i18n-pipeline / web-panel）与 7 份 MODIFIED/RENAMED/REMOVED/ADDED delta 文件一一对应。
- **断点边界一致**：wide `>=1360px`、medium `960-1359px`、compact `<960px`、phone `<600px`（design 9 / workbench spec / tasks 9.2–9.4 一致）；viewport 矩阵（1600×900、1360×768、1280×720、960×640、720×460、390×844 + 100/125/150% 缩放）在 proposal Impact、workbench spec、tasks 1.3/13.3 间一致。
- **`.openspec.yaml` 格式**：`schema: spec-driven` + `created: 2026-09-01`，与其他 active change 约定一致。
- **引用文档**：proposal 提到的  原型与四份调研文档均存在于 `ct/docs/TODO/`（schema-editor-prototype.html、responsive-three-pane-research.md、resource-discovery-patterns-research.md、commercial-workbench-reference-research.md），无溯源缺口。

---

## 5. 建议的落地顺序

1. 从 tasks 1–2 建立 golden、canonical model、具名资源 repository 与角色校验。
2. 在任何增量复用前完成统一 `types.fbs` 和传递 `export_fingerprint`，用共享类型变更 fixture 证明不会复用旧 bytes。
3. 再进入运行期事务、Web shell 与 Schema 编辑器；生产入口保持关闭直到端到端 Apply 和 Playwright/launcher 验收通过。
