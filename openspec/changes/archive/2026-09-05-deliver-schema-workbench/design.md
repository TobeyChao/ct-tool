## Context

见 [proposal.md](./proposal.md)。当前项目是 Python `src` 布局，本地 Web Panel 由 Vue 3 全局脚本驱动、无前端构建链；Schema、Excel、FBS、Binary、C#/Lua Accessor 已有独立模块，但现有 canonical model 仍以字段内联 `enum/struct/array` 为中心，模板更新也缺少稳定列路径事务。

 原型与四份调研文档已经确定交互方向：稳定的资源/主区/检查器工作台、森林绿设计系统、3/2/1 栏投影、VS Code 式局部过滤与 Quick Open。旧 `bk` 只用于参考局部密度和问题样本，不作为实现骨架。实现必须兼容 launcher 的 `720×460` 最小窗口，并保持当前无构建、随 Python 包分发的部署方式。

## Goals / Non-Goals

**Goals:**

- 建立单一 Schema canonical model，让 Web、CLI、Excel、校验与全部生成器共享类型和索引语义。
- 让跨资源编辑成为可撤销、可审查、可恢复的 Workspace 事务。
- 以一个路由/状态模型投影桌面三栏、中屏两栏和窄屏页面栈，不为断点复制业务状态。
- 在不引入前端构建链的条件下拆分全局壳、共享组件与模块代码，并用可重复浏览器验收保护布局。
- 以一次可审查的仓库切换提交直接转换现有 4 份 Schema、4 个 Excel 和测试 fixture，并用切换前后 golden 证明业务语义保持。

**Non-Goals:**

- 不实现 FlatBuffers native struct、异构 vector、嵌套 vector、cascade delete、任意复合索引或用户自定义 Accessor 名称。
- 不实现旧格式迁移模块、兼容 reader/writer、迁移 CLI/Web 升级页、永久迁移历史或 DSL；工作区仍是本机单用户模型，但会防御外部文件变化。
- 不引入完整 UI 框架、npm 打包器或运行时设计系统依赖。
- 不把依赖图可视化、收藏/标签管理和跨工作区字段搜索作为首版交付前置。

## Decisions

### 1. Canonical Type Expression 与 YAML/API 表达分层

后端 canonical model 使用递归 tagged union：

```text
ScalarType(name)
NamedType(resource_id, expected_kind=record|enum)
VectorType(element)
```

Web API 始终发送结构化 JSON，例如：

```json
{"kind":"vector","element":{"kind":"named","resourceId":"record:DropReward"}}
```

YAML 为了人工 diff 采用受控字符串：`int32`、`ItemRarity`、`vector<DropReward>`。加载器立即解析为 AST，保存器只从 AST 序列化字符串；scalar 名为保留字，Table/Record/Enum 名在统一命名域中校验，因此不存在靠字符串形状猜测类型的分支。

选择该方案而不是把每个 YAML type 写成嵌套对象，是为了保持配置可读、仓库切换 diff 紧凑；选择结构化 Web API 而不是让浏览器拼类型字符串，是为了让前端无权决定解析和序列化规则。

### 2. 资源存储与稳定标识

- Table 继续存放于 `config/schemas/*.yaml`，保持 Excel 文件、主键和表级索引归属。
- Record/Enum 存放于 `config/types/*.yaml`，每个文件包含 `kind`、`name` 与 fields/values；不再以内联定义复制到字段。
- 运行时稳定 ID 为带 kind 的标识（如 `table:Item`、`record:DropReward`、`enum:ItemRarity`），字段稳定路径为 `<resource-id>/<field-id>`。新资源和字段在 Draft 中先获得 UUID；名称不是内部选择 key。
- YAML 不需要保存 UUID；已落盘字段 ID 由资源 kind、来源文件和 canonical 路径确定性派生。显式 rename command 在同一事务内把旧 ID 映射到新 ID，避免把 rename 猜成删除+新增。

曾考虑统一迁入一个 `config/resources/` 目录，但这会同时破坏现有 CLI 路径约定和用户仓库结构，收益不足。

### 3. WorkspaceSnapshot、Draft command log 与前端持久化

后端提供只读 WorkspaceSnapshot，包含 revision/hash、资源、引用、模板状态和能力信息。前端 store 持有：

```text
baseRevision
commands[] / undoCursor
derivedDraft
route(resourceId, tab, selectionPath, stack)
panePreferences
recentResources
```

每次编辑追加具名 command（add/delete/rename/move/set property/set type/set index），undo/redo 只移动 cursor 并重新归约；不能用深拷贝最终 JSON 猜测用户意图。Draft command log 与必要快照按工作区路径、格式版本和 base revision 存入 IndexedDB；`localStorage` 只保存 pane preference、最近资源等小型偏好。刷新时仅在 revision 相同且 command 格式版本可读的情况下恢复；revision 不同则进入“源已变化”状态并要求丢弃或重新基于最新快照应用 command，不静默覆盖。配额或写入失败必须保留内存草稿并持续显示不可消失的持久化警告，不得假装已保存。

后端仍是所有校验与 apply 的权威。前端局部校验只用于即时反馈，不替代 Candidate 校验。

### 4. Workspace API 使用无服务器会话的 plan token

新增概念接口：

```text
GET  /api/schema-workspace
POST /api/schema-workspace/validate      {baseRevision, commands}
POST /api/schema-workspace/change-plan   {baseRevision, commands}
POST /api/schema-workspace/apply         {planId, baseRevision, candidateHash}
```

Change Plan 服务构建 Candidate、扫描 Excel、试生成必需产物并保存带 `expiresAt` 的 plan manifest；默认有效期为生成后 2 小时，大型 staged 文件放在工作区外的临时目录。TTL 只用于清理计划资源，正确性始终由 base revision、candidate hash 与受管输入 manifest 复核保证；即使未到期，只要任一输入变化也必须判 stale。Apply 不接受完整 Candidate 重新覆盖 plan，只接受 token 与 hash，避免“审查 A、应用 B”。进程重启后只有 manifest、staging 和 hash 均完整且未过期的计划可继续使用，否则要求重新审查。旧 `/api/schemas` 读接口可在切换期委托 Snapshot，直接写接口在前端切换后删除，不长期维持双写协议。

### 5. 逻辑原子发布使用 journal + 同文件系统 staging

普通文件系统不能对多个目录提供单条原子事务，因此这里的“原子”定义为：任何正常完成或恢复后的可观察 Workspace 都对应完整旧 revision 或完整新 revision，绝不长期暴露混合 revision。

流程：

1. 获取工作区 apply lock 并复核 base revision。
2. 在与目标同一文件系统创建受控 staging，生成完整 Candidate 文件集与 manifest。
3. 在 staging 运行 Schema 重载、Excel 复读、FBS/Binary 对拍和生成代码 postcheck。
4. 对全部待替换目标执行可写性与文件占用预检；Windows 上 Excel/Office 占用导致无法原子替换时，在发布前失败并明确列出文件及“关闭 Excel 后重试”，不得进入部分备份/发布阶段。
5. 写 durable journal，记录旧/新 manifest、备份与发布阶段。
6. 将受影响文件移动到 transaction backup，再把 staged 文件以 `os.replace` 发布；每一步更新 journal。
7. 发布后从真实目标重新加载并核对 revision，成功才标记 committed 并清理临时文件。
8. 启动时若发现未完成 journal，按阶段完成发布或恢复 backup，再允许加载工作区。

这比逐文件直接写入复杂，但能满足跨 YAML、Excel 和 output 的事务语义。曾考虑只原子替换整个 `gd` 目录，但工作区可能很大且包含用户未纳入管理的文件，不可接受。

### 6. Excel 列路径 manifest 与数据变更规划

模板继续在 Custom Document Properties 保存 `ct_schema_hash`、`ct_header_rows` 等摘要；完整列路径不塞进属性字符串，而写入 `cache/template_layouts/<table>.json`：

```text
layoutRevision
schemaHash
headerRows
columns[{index, stablePath, typeExpr, groupIndex?}]
```

Change Plan 以已落盘 layout manifest + 当前 SchemaSnapshot 和 Candidate layout 生成映射；显式 rename command 优先，未改名同路径其次。对删除列、类型变化、Enum 值移除和 vector 组收缩扫描实际非空单元格。manifest 缺失或与 Excel hash 不匹配时不猜测为安全搬移，而是报告 untracked，并要求受控推断结果进入审查。

这种 sidecar 方案复用现有 cache 目录且不污染 Excel 可见 Sheet；代价是清缓存会失去自动精确列搬移能力，因此 Change Plan 必须有明确降级状态。

### 7. Query index 以 hash bucket + 精确原字符串确认为正确性边界

Code 与 string Group 索引生成：

```text
hash -> candidate row index / candidate row indices
```

这里的“原字符串”固定指 Excel reader 完成类型解析后交给索引层的 string 值。hash 输入与碰撞确认使用同一串 UTF-8/code-point 内容，区分大小写，不执行 trim、case-fold、NFC/NFKC 或其他 Unicode 归一化；因此 `Code`、`code` 和全角变体是不同键。预加载时同时保留该精确字符串。查询先算 hash，只遍历该桶，再逐个执行 ordinal 相等比较；不同字符串即使 hash 相同也绝不视为命中。Code 的预检拒绝完全相同的字符串，hash 相同但原文不同合法；Group 返回桶内所有原值完全相等的行。首版禁止 i18n 字段作为 Code/Group 索引，避免查询键随语言变化。

额外比较的成本是 O(bucket size)，正常桶接近 O(1)，而不是 O(table size)。测试通过可注入 hash provider 构造碰撞，不依赖寻找真实算法碰撞。C# 与 Lua 必须使用同一精确字符串输入规则和 golden 数据；hash provider 可以测试注入，但生产算法、编码输入和整数溢出语义必须固定并记录，不能依赖进程随机化的运行时 string hash。

### 8. ResourceIndex 与虚拟列表从第一天走单一路径

前端维护独立资源索引，不查询 DOM：规范化 label、kind、可选别名、稳定 ID、最近使用时间与搜索描述。局部过滤和 Quick Open 共享 fuzzy scorer 与命中位置，但拥有不同 scope 与呈现。

资源树先扁平化为 group header + visible resource rows，再由固定行高 windowed list 只渲染视口和 overscan；Quick Open 复用同一列表原语。不会在 `count > 200` 时切换实现。100/1,000/10,000 项基准记录首屏、查询响应、滚动、DOM 数与内存，结果只用于调节 overscan 和缓存，不改变行为契约。

### 9. 路由状态与布局投影完全分离

路由表达资源、页签、字段和 Change Plan：

```text
#/schema/resources
#/schema/<resource-id>?tab=fields
#/schema/<resource-id>/fields/<field-id>?panel=properties
#/schema/changes/review
```

AdaptiveWorkspace 只根据可用宽度计算 visible pages/panes。宽屏 pane 收起使用 activity tool 的 `activeTool/null`；中屏资源选择是唯一临时 overlay；`<960px` 通过页面栈条件渲染，不保留负位移的不可见 pane。断点变化不会修改 route、selection、Draft 或 scroll store。

字段列表在窄屏使用专用语义 row layout，不通过 CSS 把桌面五列表格压扁。需要跨行比较的索引与 diff 保留真正 table 并在自身容器滚动。

### 10. 无构建前端按 ES module 分层

静态资源拆为：

```text
styles/tokens.css, base.css, layout.css, components.css, modules/*.css
js/core/{api,store,router,task,focus}.js
js/components/*.js
js/modules/{export,i18n,schema,logs,history}/*.js
```

`index.html` 只加载入口 ES module 和共享样式。Vue 继续由现有分发方式提供，组件使用原生 module 导出；若目标内嵌浏览器验证不支持某项 module 能力，只允许在同一边界降级为显式 namespace，不回到单文件累加。设计 token 是唯一颜色/尺寸来源，原型 HTML 不进入生产包。

### 11. 分阶段交付但一次完成行为切换

实现顺序先建立 canonical model、仓库配置切换与事务后端，再建立 shell/store，最后接 Schema UI 和其他模块视觉改版。功能可以在开发中受内部 flag 保护，但正式切换时旧写 API、旧表格 modal 与新 Draft 流程不能同时对用户可见，避免两套状态源。

### 12. 共享 FBS 类型文件与传递导出指纹

所有具名 Record 和 Enum 由生成器按稳定依赖顺序写入唯一的 `types.fbs`；每个 Table `.fbs` 通过确定性 include 引用该文件，只定义 Table 自身、索引和必要容器结构。Record 始终生成 FlatBuffers `table`，Enum 首版 wire type 固定为 `byte`，工作台只读展示 wire type。生成器必须拒绝跨文件重复定义、include 环和生成符号冲突，不能把同一共享类型复制到多张 Table schema。

增量导出的跳过条件不再只是 Excel MD5，也不使用一个把所有产物绑在一起的总 fingerprint。缓存按实际依赖图保存：

```text
schemaFingerprint(table)
  = Table canonical schema + transitive Record/Enum + indexes
    + schema/codegen format version

dataFingerprint(table)
  = schemaFingerprint + Excel content + parsing/layout inputs

i18nFingerprint(table, lang)
  = dataFingerprint + lang + effective translation semantics
    + language config + merge policy version

bundleFingerprint(lang)
  = ordered hashes of all table bytes for that language
    + container format version
```

`schemaFingerprint` 控制 Table/shared FBS 与 C#/Lua Accessor；`dataFingerprint` 控制主语言 JSON 与主表 bytes；`i18nFingerprint` 只控制对应 Table/语言的 JSON 与 i18n bytes；`bundleFingerprint` 控制对应语言 Bundle。Record/Enum 内容变化必须沿反向依赖图使受影响 Table 的 schema/data/语言指纹失效；被 `ref` 指向的另一张 Table 只有数据变化时仍不级联重导出。单个英文译文变化不得重建 FBS、Accessor、主语言或其他语言产物。

有效翻译语义只包含当前 source key 集合中每个 key 的存在性、`text` 与 `confirmed`，并包含 `primary_lang`、目标 lang、启用语言集合和 merge policy version。lang 文件中的派生 `source`、派生 `status`、orphan 条目、JSON 空白与 key 排列不参与产物 fingerprint。翻译文件损坏必须作为错误报告，不能通过复用旧 i18n bytes 掩盖。若 Excel/source 变化，先 parse + sync 得到 canonical lang 状态，再计算并提交最终 i18n fingerprint；这样 export 结束后 cache 不会立即自失效。

选择阶段同时比较 data 与请求语言的 i18n fingerprint：只有翻译变化时可以复用主表 bytes，但必须获得当前主语言行数据来重建目标语言 JSON/i18n bytes（首版允许重读 Excel，不为此增加长期 parsed-row cache）。新增/删除 secondary language、翻译文件出现/消失或 `confirmed` 改变，即使 Excel 未变也必须进入相应语言导出路径。

Workspace Apply 和普通 export 都只在相应产物成功后发布新 fingerprint/cache bytes；失败或恢复旧 revision 时不得留下宣称新 fingerprint 已导出的 cache 状态。`cache/template_layouts` 仍负责 Excel 列搬移证据，不替代任何导出 fingerprint。

### 13. 仓库直接切换与浏览器验收基建

现有工作区只有 4 份 Schema、4 个小型 Excel，旧复杂类型仅为 2 个内联 Enum、1 个 struct 和 1 个 array，因此不为它们设计产品级迁移子系统。实现时先冻结旧产物 golden，再在一个可审查的仓库提交中直接增加具名 type 文件、改写 4 份 Schema、按明确列映射更新 4 个 Excel 与测试 fixture，最后用 JSON/FBS/Binary/C#/Lua 对拍确认除目标格式变化外语义一致。用于机械转换的开发期命令或临时脚本不进入 Python package、CLI、Web 或最终提交；新 loader 遇到 `type: struct`、`type: array` 或内联 enum values 时直接返回带文件/字段位置的升级错误，不自动转换或写盘。

浏览器验收固定使用 Python 测试环境中的 Playwright 驱动本地 Web Panel，不引入前端构建链。截图、键盘、焦点、断点和缩放用例在 CI 与本地使用同一 fixture；发布矩阵允许按浏览器能力模拟 device scale factor，但 720×460 launcher 最小窗口必须在真实打包面板上再跑一次 smoke test。

### 14. 代码架构使用单向依赖与按变化原因拆分

本 change 不通过继续扩张现有总控文件交付。Python 依赖方向固定为：

```text
CLI / Web adapters
        ↓
application use cases (`ct/app`)
        ↓
schema domain + excel/validate/export/cache engines
        ↓
shared diagnostics/config primitives
```

下层模块不得 import `ct.app`、`ct.web` 或 `ct.cli`；Web/CLI 不得直接写 YAML、Excel、cache 或调用低层 generator 绕过 use case。现有 `ct.export.deploy` 对 App 对象的反向依赖在相关改造中搬到 application 层；现有 Schema convention 与 validation 共享的 Issue/Location 契约下沉到无业务编排依赖的 diagnostics 模块，避免概念环。

Workspace 事务按变化原因组织在 `ct/app/schema_workspace/`：snapshot、commands/reducer、candidate validation、change plan、apply/publish 和 recovery 使用清晰入口；纯查询/规划与修改发布分离。`validate` 和 `change-plan` 不得产生文件副作用，只有 apply/publish 边界持有写权限。不要用一个带大量 flag 的 service 函数承载所有阶段，也不要为只有单一实现且无测试替身需求的对象预先制造 Protocol/抽象层。

持久化与生成职责分离：Schema repository 只负责 canonical resource 的加载/保存与来源定位；FBS 文本生成归 `ct/export`，Excel layout/data mapping 归 `ct/excel`，fingerprint/cache persistence 归 `ct/cache`，`ct/app` 只组合这些能力。C# 与 Lua 生成器继续消费一个共享 Accessor/Index model，不各自解析 Type Expression 或复制 Code/Group 规则。

Web 后端的 `create_app` 只做 app factory、依赖装配和 blueprint 注册；各模块 route 只负责请求解析、调用 use case、映射结构化响应。前端 `js/core` 不 import 具体业务模块，业务模块可依赖 core 与共享组件但不得相互读取内部 store；Draft、route、pane projection 和 task state 各有单一状态所有者。旧 `app.js`、旧 Schema 写 route、旧 modal/CSS 在切换完成后物理删除，不保留注释代码或长期兼容分支。

代码规模只作为重构信号而非机械分文件指标：新增模块必须有单一变化原因；出现同时处理 HTTP、领域规则和文件 I/O，或一个修改需要跨多份重复 switch/type parsing 时，必须先提炼/搬移到拥有该规则的模块。行为保持型提炼先在绿色测试下独立完成，再在稳定边界增加新功能，避免一边搬家一边改变语义。测试分为纯 model/reducer/fingerprint 单元测试、repository/API contract、plan/apply 集成和浏览器端到端四层，避免所有验证都压到慢速 E2E。

## Risks / Trade-offs

- [Change 体量跨前后端和产物链，容易出现长期半成品] → 任务按 canonical model、事务、UI shell、Schema、全模块改版和验收设置明确完成门；不开启生产入口直到端到端 apply 通过。
- [多文件发布无法获得内核级全局原子性] → 使用 lock、同文件系统 staging、durable journal、backup 和启动恢复，把逻辑原子性纳入故障注入测试。
- [清理 cache 后失去旧 Excel 精确路径 manifest] → 将状态显示为 untracked，生成可审查推断并阻止无法证明安全的自动搬移；绝不按列序静默处理。
- [大列表虚拟化影响读屏器集合语义和焦点] → 保存逻辑总数/位置语义、roving focus 和选中滚入视口，并以键盘/读屏验收覆盖过滤后焦点变化。
- [Type Expression YAML 字符串未来需要更多修饰符] → parser/AST 保持递归，YAML grammar 有版本与清晰错误；新增修饰符不要求下游改用字符串判断。
- [原字符串比较增加查询成本] → 只比较 hash 桶候选并缓存精确解析字符串；基准覆盖正常和对抗桶，不以牺牲正确性换取理论常数。
- [统一视觉改版可能误改既有业务] → 导出、i18n、日志、历史先以现有 API 契约做行为回归，视觉改版不得改变其文件写入和任务语义。
- [浏览器存储中的 Draft 与外部 Git/编辑器修改冲突] → Draft 绑定 base revision；不自动重放到未知快照，必须显式重新基于最新版本或丢弃。
- [共享类型变化但 Excel 未变化时复用旧 bytes] → export fingerprint 包含全部传递 Record/Enum 内容并沿反向依赖失效，缓存发布与 Workspace revision 同事务完成。
- [翻译变化但 Excel 未变化时复用旧语言产物] → 每表每语言保存语义 i18n fingerprint，并将语言 JSON/i18n bytes/Bundle 与 schema/data 产物分开失效。
- [Windows 中 Excel 文件被 Office 占用] → 发布前预检全部目标并提供关闭文件后的可重试错误；未通过预检不进入 journal publish 阶段。
- [Draft 超出浏览器小型键值存储容量] → command log 使用带版本的 IndexedDB，localStorage 只存偏好；持久化失败保持内存草稿并显示持续警告。
- [新功能继续堆入现有大文件并产生多向依赖] → 以 AST import-boundary 测试保护层次，按变化原因拆分 schema workspace、route 和 generator；旧总控路径在 cutover 后删除。
- [为了整洁过度抽象，出现只有一个实现的接口和转发层] → Protocol 只用于真实多实现边界或必要测试 seam，优先明确函数和值对象，评审同时检查冗余中间层和死代码。
- [直接仓库切换漏改配置或 fixture] → 固定核对 4 Schema、4 Excel、测试 fixture 与全套生成产物，扫描产品代码无旧类型解析分支，并以切换前后 golden 和人工单元格检查作为完成门。

## Repository Cutover Plan

1. 为当前 4 份 Schema、4 个 Excel 与 JSON/FBS/Binary/C#/Lua 产物建立只读 fixture/golden，并记录完整导出结果。
2. 实现只接受新格式的 AST、Record/Enum repository 与统一 `types.fbs`；对旧 `struct`、`array` 和内联 Enum 只提供明确只读错误，不加入兼容解析分支。
3. 在一个独立、可审查的仓库修改中直接创建具名 Record/Enum、将 array 改为 vector、更新 4 份 Schema、4 个 Excel 与测试 fixture；逐项列出旧→新字段路径，不提交临时转换脚本。
4. 重建模板、layout manifest 和全部导出产物，运行 golden/字节级回归并人工核对小型 Excel 数据；通过后将新格式作为唯一受支持输入。
5. 上线 Workspace 读 API、Candidate/Change Plan/Apply 后端和故障恢复测试，再切换前端 Schema 模块。
6. 改版 AppShell 和其余模块视觉；完成尺寸、缩放、键盘、截图和大列表基准后移除旧 modal/CSS/API。

回滚开发期仓库切换时直接回退同一提交中的 Schema/type/Excel/fixture/output；上线后的 Workspace Apply 回滚则从最近 committed transaction backup 恢复受影响文件和上一版静态资源。两种情况都不能只回退前端。
