## Why

现有 Web Panel 的表格管理、旧 `bk` Schema 编辑器和多次原型探索仍缺少统一的领域模型、安全应用事务与跨尺寸工作台，继续局部修补会重复产生模态栈、侧栏状态、表格错位和部分写入等问题。现在已有 v4 原型及类型系统、响应式三栏、资源发现和商业化工作台调研，可以收敛为一个必须端到端交付、而非只交互演示的正式变更。

## What Changes

- 将 Web Panel 重构为统一的专用工作台：共享森林绿设计 token、顶栏、模块 Activity Bar、命令栏、数据表、检查器、任务栏、错误与空态语言；导出、i18n、Schema、日志和历史保持同一设计语言。
- 交付 Schema Editor v4：左侧 `Tables / Records / Enums` 资源区、中间资源编辑区、右侧属性/草稿工具区；命名类型在同一工作区导航，不再使用嵌套编辑模态。
- 增加可扩展的资源发现：左栏 fuzzy 过滤、匹配高亮、结果计数和完整键盘路径；`Cmd/Ctrl+P` Quick Open 在空查询时显示最近资源、输入后搜索全部资源；生产列表使用单一可虚拟化实现，不设置任意条数开关。
- 建立 `wide / medium / compact / phone` 自适应状态机：宽屏三栏、中屏主编辑区与检查器两栏且资源为唯一临时选择层、窄屏/手机为可返回页面栈；尺寸变化只改变布局投影，不丢失资源、页签、字段选择、滚动位置或草稿。
- **BREAKING**：用统一递归 Type Expression 替代 `type + type_ref + element_type + element_type_ref` 等互斥组合；正式资源为 Table、Record、Enum，Record 生成 FlatBuffers `table`，旧 `struct` 名称不再表示这种可复用对象结构，旧 `array` 统一为 `vector`。
- 第一版端到端支持 `vector<record>`；vector 的 `excel_columns` 只定义 Excel 可填写的展开组数，运行时仍为普通变长 vector；禁止 `vector<vector<T>>` 和匿名大型 record。
- 将 Code 与 Group 查询从字段布尔开关提升为表级 `indexes` 模型；生成 C#/Lua 查询 API，Code 保证唯一，Group 支持一对多；hash 输入和碰撞确认均使用 Excel 解析后的精确原字符串，不做 trim、大小写折叠或 Unicode 归一化，任何 hash 命中后都不能只相信 hash。
- 锁定首版字段角色边界：`i18n` 与 `server_only` 仅允许出现在 Table 顶层字段，Record 叶子禁止这两个角色，i18n 字段不得作为 Code/Group 索引；Enum 的 FlatBuffers wire type 固定为 `byte`。
- 将单一导出 fingerprint 拆为 schema、data、逐语言 i18n 与 bundle 四层：译文或 `confirmed` 变化必须刷新对应语言 JSON/i18n bytes/Bundle，但不得无意义重建 FBS、Accessor、主语言产物或其他语言。
- 所有 Schema 编辑进入 Workspace Draft，支持命令级 undo/redo、撤销当前字段修改和放弃全部草稿；资源切换、pane 折叠与断点变化不得清除草稿。
- “审查并应用”先构建完整 Candidate Workspace 和 Change Plan，展示 Schema、Excel、引用、FlatBuffers、Binary 与 Accessor 影响；apply 使用 snapshot/candidate hash 防并发变化，并在临时目录完成全链路生成、postcheck 和原子替换，任一环节失败不得部分落盘。
- 以清晰依赖方向重组实现：Schema domain 与生成引擎不依赖 App/Web，App 只编排 use case，CLI/Web 只做输入输出适配；Schema repository 不再混入 FBS 生成，现有 `web/app.py`、`app.js` 和 `app/export.py` 不继续成长为总控文件。
- Excel 数据搬移按稳定字段路径和显式 rename command 建立旧列到新列映射；删除、类型转换、enum 值变化和 `excel_columns` 收缩必须扫描现有数据并给出具体行列与阻塞原因。
- 删除被引用的 Table、Record、Enum 或字段默认阻止并展示反向引用；第一版不提供 cascade delete；native FlatBuffers struct、异构 vector、跨工作区字段搜索和依赖图可视化不在本 change 内。
- **BREAKING**：旧的 Schema 直接 CRUD/保存即写 YAML 行为改为 Draft → Change Plan → Apply；Web API 使用结构化 JSON，不接受前端提交 YAML 文本。仓库内仅有的 4 份旧 Schema 与 4 个小型 Excel 在实现切换提交中直接转换并做产物对拍；产品不提供旧格式迁移 CLI、Web 升级页或兼容 reader/writer，也不保留两套编辑协议。

## Capabilities

### New Capabilities

- `schema-editor/workbench`: Schema v4 的资源导航、字段/枚举编辑、检查器、资源发现、键盘操作与 3/2/1 栏自适应行为。
- `schema-editor/type-system`: 统一 Type Expression、Table/Record/Enum 资源、命名引用、`vector<record>`、依赖与删除保护。
- `schema-editor/workspace-draft`: Workspace 级草稿、undo/redo、Change Plan、数据预检、并发保护、原子 apply 与失败恢复。
- `schema-editor/query-indexes`: 表级 Code/Group 索引、数据约束、C#/Lua Accessor 生成及 hash 碰撞后的原值确认。
- `web-panel-design-system`: 全 Web Panel 的 AppShell、视觉 token、共享组件、响应式与可访问性交互契约。

### Modified Capabilities

- `web-panel`: 将顶部页签与弹窗式表格管理改为统一模块工作台和 Schema Workspace Draft 流程，并同步改版其他既有模块。
- `schema-management`: 用具名 Enum/Record 与统一 Type Expression 替换内联 `enum/struct/array` 模型，扩展全局依赖图、反向引用和命名校验。
- `excel-processing`: 支持 Record 与 `vector<record>` 的单格/展开布局、稳定字段路径映射、rename 与危险变更数据预检。
- `json-export`: 将旧 struct/array 序列化术语收敛为具名 Record、Enum 与 vector，并覆盖 `vector<Record>` JSON 语义。
- `flatbuffers-export`: Record 生成 FlatBuffers table、共享 Record/Enum 统一归属 `types.fbs`、vector 可包含命名 Record，并让新索引查询契约贯穿 Binary 与 C#/Lua Accessor。
- `incremental-export`: 由仅比较 Excel MD5 改为 Excel 内容与传递 Schema/type 依赖共同决定导出指纹；共享类型变化必须使所有依赖 Table 重新生成，不能复用旧 Binary bytes。
- `i18n-pipeline`: 为每张 Table/语言计算只包含有效 key、`text`、`confirmed` 与 merge policy 的语义 fingerprint；翻译文件格式、派生 status/source 和 orphan 不得造成无意义产物重建。

## Impact

- 后端：`ct/schema/` canonical model、repository、dependency graph、hashing；`ct/app/schema_workspace/` Draft、candidate、change-plan/apply 用例；validate、Excel reader/template/layout change planning、FBS/Binary/Accessor 生成器及缓存状态。共享诊断契约下沉到无上层依赖的基础模块，避免 schema↔validate 反向耦合。
- Web API：新增 Workspace snapshot/draft validation/change-plan/apply 与资源查询接口；替换 Schema 直接写入协议，同时保持导出、i18n、日志和历史的现有业务语义。
- 前端：重组 `ct/src/ct/web/static/` 为无构建 ES module 的 shell、共享组件、模块和样式层；移除旧表格管理 modal、重复 CSS、侧栏 hidden/collapsed/overlay 组合状态与移出屏幕动画。
- 数据与产物：在实现切换提交中直接转换 `gd/config/schemas/*.yaml`、对应 Excel 与测试 fixture；Record/Enum 定义、Excel 表头与数据映射、共享 `types.fbs`、Table `.fbs`、Binary Bundle、C#/Lua Accessor，以及 schema/data/per-language-i18n/bundle 分层 cache fingerprint 均受影响。
- 验证：需要依赖边界与旧协议残留检查、后端单元/契约/集成/端到端测试、仓库切换前后产物 golden、hash 碰撞测试、大资源列表基准，以及 `1600×900`、`1360×768`、`1280×720`、`960×640`、`720×460`、`390×844` 与 100%/125%/150% 缩放的浏览器截图和键盘验收。
