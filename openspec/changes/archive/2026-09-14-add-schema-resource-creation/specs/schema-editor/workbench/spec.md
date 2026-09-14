## ADDED Requirements

### Requirement: Create Schema resources from the workbench
工作台 SHALL 提供「新增 Schema」入口及 Table、Record、Enum 类型选择，资源分组入口 SHALL 预选对应类型；入口 SHALL 在资源面板折叠、空分组和已配置但没有任何资源的工作区可用。创建表单 SHALL 支持名称、注释和类型对应的最小合法内容，遵守既有键盘、焦点恢复及窄屏交互规范。

#### Scenario: Create from an empty workspace
- **WHEN** 已配置工作区无任何 Schema 且用户选择新增 Table
- **THEN** 可完成表单并进入新 Table 编辑器，无须先手写 YAML 或打开已有资源

#### Scenario: Create while resource pane is collapsed
- **WHEN** 资源面板折叠且用户用键盘打开新增入口
- **THEN** 可选择三类资源；取消后焦点回到入口，成功后焦点进入新资源标题，390px 窄屏没有页面横向溢出

### Requirement: Kind-specific creation forms
Table 创建 SHALL 自动包含固定 `primary: Id` 和 `Id: int32`，不自动添加 CodeName 或索引；Record SHALL 至少填写一个合法字段，不能隐式添加主键；Enum SHALL 至少填写一个具名项并支持 comment，ordinal 从 0 按输入顺序派生。空名称、不合法名称、重复名称、空 Record/Enum SHALL 阻止创建并保留输入，校验不得通过静默改名修复。

#### Scenario: Minimal Table
- **WHEN** 用户以合法名称 Item 完成 Table 创建
- **THEN** 草稿 Table 包含 Id 主键，Excel 文件和 JSON key 使用既有默认规则，用户可继续添加普通字段和查询索引

#### Scenario: Minimal Record
- **WHEN** 用户创建 DropReward 并填写首个字段 Min、类型 int32
- **THEN** 草稿 Record 包含 Min 且不包含自动生成的 Id；未填写首字段时不能提交

#### Scenario: Minimal Enum
- **WHEN** 用户创建 ItemRarity 并填写首项 Common、注释「普通」
- **THEN** 草稿 Enum 显示 Common 的 ordinal 为 0，继续追加值沿用现有编辑器行为；空项和重复项被拒绝

#### Scenario: Existing resource name collision
- **WHEN** 用户以现有或当前草稿资源的名称创建任意类别资源
- **THEN** 表单显示名称冲突且不增加命令，不因类别不同而允许重名

### Requirement: Newly created resources participate in draft navigation
创建成功 SHALL 仅加入草稿，自动选中新资源并标记未保存；资源列表、计数、过滤、Quick Open、类型选择和 ref 选择 SHALL 反映当前撤销光标下的候选资源。Record/Enum SHALL 可被当前草稿的字段引用，Table SHALL 仅作为合法 ref 目标而非具名字段类型。取消表单 SHALL 不改变草稿。

#### Scenario: Build three related resources without saving between them
- **WHEN** 用户依次创建 ItemRarity、引用它的 DropReward、引用 DropReward 的 Item
- **THEN** 每次创建后后续类型选择均能找到新类型，三者可在同一草稿中编辑和保存

#### Scenario: Undo selected resource creation
- **WHEN** 用户撤销当前选中资源的创建
- **THEN** 资源从所有候选列表消失，主区回到有效资源或空状态而不保留失效详情；重做可恢复资源

### Requirement: Explicit post-save Table workflow
新 Table 保存成功后 SHALL 展示真实模板状态，缺失时提供针对该表的显式生成模板操作；尚未保存时 SHALL 提示先保存且不能向模板操作传入未落盘资源。保存 SHALL 不自动生成 Excel 或导出产物。Record/Enum SHALL 不提供独立 Excel 模板操作。

#### Scenario: Save then generate and export
- **WHEN** 用户保存包含新 Table 的草稿，再显式生成模板、填写合法数据、执行校验及导出
- **THEN** 模板包含新字段布局，校验成功，JSON、FBS、Binary 与 C#/Lua Accessor 按当前配置包含新表及其引用类型

#### Scenario: Existing workbook at the new Table path
- **WHEN** 新 Table 对应路径已有 Excel 且用户显式生成模板
- **THEN** 使用既有无损预检，不能证明数据可保留时拒绝覆盖并显示问题，已保存 YAML 与原工作簿保持不变

#### Scenario: Template generation fails after save
- **WHEN** YAML 已保存而显式模板生成失败
- **THEN** 界面分别显示保存成功与模板生成失败，可重试模板操作，不把 YAML 保存标记为失败或恢复已保存草稿
