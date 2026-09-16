## Purpose

定义原生桌面配表工作台的交互、视觉和业务入口契约，使用户能够在不启动浏览器或本地 Web 服务的情况下完成 Schema、翻译、模板与导出工作，并保持与独立 CLI 共用的校验和可靠保存保证。

## ADDED Requirements

### Requirement: Native workspace navigation
客户端 SHALL 提供工作区选择、总览、Table/Record/Enum 搜索和导航、Schema 编辑、只读数据预览、翻译、导出、独立部署、日志、最近五次导出历史和设置。资源列表和选择器 SHALL 反映当前草稿 cursor 下的候选资源；切换页面或改变分栏不得丢失编辑状态。数据预览 SHALL 按需分页而非一次加载整表。

#### Scenario: Navigate unsaved resources
- **WHEN** 用户创建 Record 后切换到 Table 并调整分栏
- **THEN** 类型选择可找到该 Record，返回时草稿、选择和撤销历史保留

#### Scenario: Empty workspace
- **WHEN** 打开已配置但无资源的工作区
- **THEN** 显示空态及三类资源创建入口，不要求先手写 YAML

### Requirement: Native visual and interaction quality
客户端 SHALL 采用一致的深林绿浅色视觉令牌，统一文字层级、状态色、间距、表格对齐和可见焦点；提供可折叠/可调整宽度的辅助区、键盘搜索、保存、撤销重做与平台对应快捷键。对话框关闭 SHALL 恢复合理焦点，隐藏区域不得获取焦点，减少动态效果偏好 SHALL 生效。Windows/macOS SHALL 验收 1440×900、1280×800、1024×700 逻辑尺寸及 100%/125%/150% 缩放，中文长文本、路径和错误信息不遮挡主操作。

#### Scenario: Resize while editing
- **WHEN** 用户在上述矩阵调整窗口和缩放
- **THEN** 表头与行对齐、页面不横向溢出、表格可内部横滚，选择和草稿保持，主操作可达

#### Scenario: Keyboard and input method
- **WHEN** 用户使用中文输入法编辑字段，并用键盘保存、撤销和关闭弹窗
- **THEN** 输入法组合期间不误触快捷键，焦点可见且关闭后回到有效入口

### Requirement: Guarded native Schema draft
客户端 SHALL 遵守 workspace-draft、type-system、query-indexes 的现行业务规则；通过内核计算候选和净差异，保存携带原始 schemaRevision 和 candidateHash，候选刷新不得推进基线。保存 SHALL 仅改 YAML；模板生成、翻译同步、导出与部署是独立操作。草稿恢复 SHALL 按工作区和基线隔离，失败/冲突保留命令与 cursor，不静默覆盖外部修改。

#### Scenario: External schema modification
- **WHEN** 有草稿时另一进程改变 YAML 后用户保存
- **THEN** 展示冲突，磁盘不被覆盖，草稿与撤销历史保留

#### Scenario: Save a new Table
- **WHEN** 新 Table 保存成功
- **THEN** 展示实际模板缺失状态并提供显式生成入口，不自动创建 Excel、翻译、导出或成功账本

#### Scenario: Restart with a draft
- **WHEN** 应用重启且草稿基线未变
- **THEN** 恢复相同命令、cursor 和资源；基线变化时标记冲突，不自动套用或删除草稿

### Requirement: Translation and template workflow parity
客户端 SHALL 提供翻译表/语言/状态筛选、列显隐、行内失焦保存、长文本对照编辑、同步和按表/语言进度；保存条目遵守 text/confirmed/status 规则，compact 显示删除范围并确认。模板 SHALL 显式调用迁移预检与生成，阻塞时保留原工作簿。Record/Enum 不提供独立 Excel 模板按钮。

#### Scenario: Edit long translation
- **WHEN** 用户编辑长译文并保存
- **THEN** 对应条目经内核保存，confirmed=true，状态及过滤更新；取消对照弹窗不提交弹窗内修改

#### Scenario: Unsafe template migration
- **WHEN** 模板缺少安全迁移依据或存在不可迁移数据
- **THEN** 显示定位问题，不覆盖 Excel，不把已成功的 YAML 保存改判为失败

### Requirement: Responsive export and process lifecycle
耗时任务期间客户端 SHALL 保持导航、滚动和日志查看可用，并显示阶段、耗时、缓存统计及可定位错误。桌面 export SHALL 仅本地导出并在成功后记账，部署由独立操作触发。同工作区冲突写入 SHALL 展示 busy；发布前取消、发布后延迟取消以内核终态为准。断连无终态 SHALL 显示结果未知并保留草稿，不自动重放写请求。

#### Scenario: Cancel during publication
- **WHEN** 用户取消时内核已经开始发布
- **THEN** 界面展示正在完成，等待终态，不直接标记取消或杀死进程

#### Scenario: Worker crashes
- **WHEN** worker 在写请求终态前退出
- **THEN** 显示未知结果和恢复入口；重新连接检查状态，保存和导出不自动重试

#### Scenario: Old workspace event arrives
- **WHEN** 用户切换工作区后收到原工作区任务事件
- **THEN** 事件仍归属原任务，不更新当前工作区资源或草稿

### Requirement: Visual prototype is an intermediate milestone
客户端 SHALL 先交付带明确模拟标识的可运行视觉样板，覆盖资源树、Schema 编辑、属性区及导出面板的空态/错误/忙碌状态。正式完成 SHALL 使用真实运行时在 Windows/macOS 无 Python 环境完成创建资源、保存、生成模板、填表后校验导出、编辑翻译和独立部署全链路，并记录截图与验证结果。

#### Scenario: Mock export completes
- **WHEN** 样板中的模拟导出显示完成
- **THEN** 明确标识模拟，不能据此勾选真实导出或完整迁移验收任务

### Requirement: Full Schema navigation and Enum editing
原生工作台 SHALL 保留 schema-editor/workbench 的非浏览器业务交互：全局 Cmd/Ctrl+P、空查询最近资源、fuzzy 搜索及键盘选择、类型/ref 链接主区跳转与来源导航、Enum item 追加/显式改名/删除/重排、wire type 与引用显示。Enum 显式改名 SHALL 保留 originalOrdinal 身份；净差异 SHALL 展示受影响项旧/新 ordinal 和 API 名称风险，不能把改名猜成删除新增。

#### Scenario: Quick Open from export
- **WHEN** 用户在导出页且资源区关闭时按 Cmd/Ctrl+P
- **THEN** 空查询显示最近资源，搜索选择后转到 Schema 并打开目标，保留原草稿

#### Scenario: Enum reorder and rename
- **WHEN** 用户重排枚举项后改名并查看差异
- **THEN** 显示旧/新 ordinal 及名称影响，撤销可逐步恢复；不自动改写 Excel 中的旧 token

#### Scenario: Follow a type or ref link
- **WHEN** 用户点击字段中的 Record 类型或 Table.Primary 引用
- **THEN** 主区打开对应定义且可返回来源字段，不叠加独立编辑模态或丢失草稿

### Requirement: Draft persistence and response ordering safety
原生草稿 SHALL 包含格式版本、工作区身份、原始基线、完整 commands 和 cursor，原子持久化。失败 SHALL 保留内存编辑并持续显示未持久化警告；未知格式或损坏数据 SHALL 保留供查看，不静默清空。候选响应 SHALL 仅更新匹配当前编辑代次的草稿，保存期间冻结编辑且不能重复提交；候选计算中/净差异为零/有阻塞问题时禁用保存。跨模块草稿条 SHALL 显示净变化资源数、撤销重做、保存及放弃入口，放弃需确认。旧 IndexedDB 草稿 SHALL 明确提示先在旧端保存，不自动扫描迁移。

#### Scenario: Disk write fails then user exits
- **WHEN** 草稿持久化因权限或磁盘空间失败且用户选择保留草稿后退出
- **THEN** 不宣称已保留，不按该选择直接退出，允许重试或明确选择放弃；内存编辑仍在

#### Scenario: Older candidate response arrives last
- **WHEN** 较早 cursor 的候选响应晚于当前编辑代次返回
- **THEN** 丢弃旧响应，不替换当前候选、hash、净差异或保存状态

#### Scenario: Successful save followed by refresh failure
- **WHEN** YAML 保存成功但后续模板状态刷新失败
- **THEN** 显示已保存及状态暂不可用，不恢复旧草稿或要求重复保存

#### Scenario: Data-only external change
- **WHEN** Excel 或翻译变化而 Schema 基线未变
- **THEN** 草稿保持有效，不能因这些变化清空历史或阻止结构保存

### Requirement: Durable history and actionable diagnostics
客户端 SHALL 从内核读取按工作区隔离、跨重启保留的最近五次成功桌面导出记录，兼容旧 panel_history.json。日志 SHALL 支持导出/校验/i18n/模板/系统模块与级别筛选，失败问题持续可定位，任务通知可显式关闭；大问题集 SHALL 分页而不静默截断。帮助、关于、外部导出文档入口 SHALL 可达，版本和快捷键信息真实。

#### Scenario: Restart after upgrade
- **WHEN** 原工作区已有五条旧导出记录且客户端升级后重启
- **THEN** 原有记录可查看，新成功导出裁剪最早一条，失败不伪造成功记录

#### Scenario: Dismiss failure and navigate
- **WHEN** 用户关闭失败通知并切换模块或重连同一 worker
- **THEN** 已关闭通知不复活，日志和问题定位入口仍可查看

### Requirement: Desktop lifecycle and configured workspace paths
客户端 SHALL 保留单实例、可配置开机自启与托盘常驻，使用可调整窗口且最小逻辑尺寸为 1024×700。所有概览/资源/语言/最后导出信息 SHALL 来自内核，不通过固定目录扫描推断。窗口关闭、Cmd+Q、托盘退出 SHALL 使用相同草稿和任务保护流程。

#### Scenario: Customized workspace directories
- **WHEN** schemas_dir、i18n_dir、output_dir、cache_dir 均非默认值
- **THEN** 总览、翻译、历史和资源数仍正确，未在默认路径创建重复文件

#### Scenario: Duplicate launch and login start
- **WHEN** 应用已启动后再次启动或登录自启触发
- **THEN** 不产生第二个应用 worker，已有任务和草稿不被中断，自启开关与实际系统状态一致
