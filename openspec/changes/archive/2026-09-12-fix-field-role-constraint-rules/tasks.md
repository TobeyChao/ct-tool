# Tasks: fix-field-role-constraint-rules

## 1. 模型层校验

- [x] 1.1 在 `FieldDef._validate_field` 增加「`separator` 仅允许配 `vector<Scalar>` / `vector<Enum>`」校验，非 vector 或 `vector<Record>` 字段声明 `separator` 报错（指明表名/字段名/类型），并新增 `tests/schema/test_role_boundaries.py` 用例覆盖；验证 `pytest ct/tests/schema/` 通过
- [x] 1.2 在 `TableResource._validate_table` 增加「主键字段禁止 `server_only`」校验（报错指明表名 + 主键字段名），并新增拒绝用例；验证 `pytest ct/tests/schema/test_role_boundaries.py` 新增用例通过
- [x] 1.3 存量扫描 `gd/config/schemas/*.yaml`：确认无主键字段误标 `server_only`、非 vector 或 `vector<Record>` 字段误标 `separator`；验证扫描命令零命中（命中则先在 gd 侧修正）
- [x] 1.4 在 design.md 记录固定字段名约定（主键 `Id` 必有、代号 `Code` 可选）与 `ct/schema/commands.py` 命令模型核对无冲突；验证 design.md D8 含该约定（不通过 add_field 指派主键，草稿命令无 pk）
- [x] 1.5 在 `FieldDef._validate_field` / `resource_repository._resolve_fields` 增加「`excel_columns` 仅适用于 `vector<Record>`」校验（非 vector、`vector<Scalar>`/`vector<Enum>` 声明即报错），并新增 `test_role_boundaries.py` 用例覆盖；验证 `pytest ct/tests/schema/` 通过

## 2. 原型弹窗（ct/docs/design/responsive-app-shell.html）

- [x] 2.1 移除「必填」checkbox；「主键」checkbox 一并移除（主键字段名固定 `Id`，不通过新增字段指派）；ref / 代号 `Code` 的工具强制约束以只读提示呈现；草稿命令移除 `req` 与 `pk`；验证 `__dbg()` 命令不含 req/pk
- [x] 2.2 代号字段（Code）固定约束：勾选「代号字段」后锁定 字段名=`Code` / 类型=`string` / 角色=无（i18n、server_only 禁用）；验证无法提交 `fieldType` 非 string 或带角色的 Code 命令
- [x] 2.3 类型 × 角色联动：I18N 角色下类型选择器仅允许 `string`（其他候选禁用或选择后被拦）；验证无法提交 `fieldType` 非 string 且 `role='i18n'` 的命令
- [x] 2.4 一表至多一个 Code：已含代号字段的表（ItemType）阻止再次添加并提示；验证 Item 可添加 Code、ItemType 不可
- [x] 2.5 分隔符工具内置（默认 `,`）：弹窗不提供分隔符输入，草稿命令不携带 `separator`；验证所有 `__dbg()` 命令均无 `sep` 键
- [x] 2.6 原型全量回归：更新并运行入库的 Playwright 回归脚本（`ct/docs/design/responsive-app-shell_e2e.py`），覆盖既有交互路径 + 新增互斥用例，验证全部通过且无 console 错误
- [x] 2.7 vector 修饰符：类型选择器去掉 vector 项（只选基础 T）；弹窗新增「vector」checkbox + 「定长/变长」pill（T=Record 强制定长 + 展开组数输入，T=标量/Enum 变长 + 内置分隔符提示，T=ref 不支持 vector）；提交类型 = `vector<${T}>`；验证 E2E 覆盖上述用例

## 3. Spec 同步与收尾

- [x] 3.1 运行 `openspec sync-specs` 将 schema-management 与 schema-editor/workbench 两份 delta 合入主 spec；验证 `openspec validate` 通过
- [x] 3.2 归档本 change 前复核：模型校验、原型联动、存量扫描三项完成；验证 `openspec status --change fix-field-role-constraint-rules` 全部任务完成
