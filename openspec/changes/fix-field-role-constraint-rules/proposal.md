## Why

新增字段流程的「角色 × 约束」互斥逻辑与真实 schema 功能不一致：面板/原型允许勾选无真实语义或会产生非法/客户端不可用 schema 的组合——「必填」在模型层根本不存在，主键 × Server-only 会产生客户端无主键的 bundle，I18N 角色下仍可选非 string 类型。问题既在模型校验缺口，也在 UI 未联动。

## What Changes

- **模型层（schema 加载校验）新增两条规则**：
  - 主键字段禁止标记 `server_only`（主键是客户端与次语言 bundle 的唯一 key，`server_only` 字段不进入客户端 Binary，组合会让客户端数据失去主键）
  - `separator` 仅允许配合 vector 标量 / Enum（`vector<Scalar>` / `vector<Enum>`）；非 vector 字段或 `vector<Record>`（按 `excel_columns` 展开为列组、不使用分隔符）声明 `separator` 报错
- **面板/原型（添加字段弹窗）互斥联动**：
  - 移除无真实语义的「必填」勾选；主键 / ref 外键字段显示「工具强制非空」只读提示
  - 角色 × 主键互斥：主键 ⇄ I18N / Server-only 相互禁用
  - 类型 × 角色联动：I18N 角色下类型选择器仅允许 `string`
  - 一表只能有一个主键（现有主键存在时新勾选需显式处理）
  - 非 vector 类型不显示分隔符控件，草稿不携带 `separator`
- **不新增 `required` 能力**：真实工具链中唯一强制非空的字段是主键（ref 外键由外键校验间接强制），不为此发明新 schema 属性。

## Capabilities

### New Capabilities

无（不新增能力域；规则归入现有 schema-management 与 schema-editor/workbench）。

### Modified Capabilities

- `schema-management`: 字段标记组合校验新增两条规则——主键 × `server_only` 互斥、`separator` 仅限 `vector<T>`
- `schema-editor/workbench`: 添加字段流程新增「角色 × 约束」互斥联动行为（必填降级、主键互斥、类型联动、一表一主键、分隔符仅 vector）

## Impact

- `ct/src/ct/schema/resources.py`：`FieldDef._validate_field`（separator 规则）、`TableResource._validate_table`（主键 × server_only 规则）
- `ct/tests/schema/test_role_boundaries.py` 等：新增两条规则的拒绝用例
- `ct/docs/design/responsive-app-shell.html`：添加字段弹窗互斥联动（原型当前承载该流程的交互设计）
- 正式 Vue 面板（`ct/web/static/` 后续对接同一规则，本 change 不直接改面板实现）
- 存量数据复核：`gd/config/schemas/*.yaml` 需扫描主键字段是否误标 `server_only`、非 vector 字段是否误标 `separator`
