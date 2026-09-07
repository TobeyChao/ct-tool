# Design: fix-field-role-constraint-rules

## Context

现状（动机见 proposal.md - Why）：

- 模型层：`FieldDef._validate_field`（`ct/src/ct/schema/resources.py` L61-72）已强制「i18n × server_only 互斥」「i18n 仅 string」「separator 非空」；`TableResource._validate_table`（L103-119）已强制主键类型 `int32`/`int64`。缺口：主键 × `server_only` 未校验、`separator` 未要求配 `vector<T>`。`FieldDef` 为 `extra="forbid"`，未知键直接拒绝。
- 数据校验层：唯一强制非空的字段是主键（`canonical_commands._primary_issues`：空主键报「主键为空」）；ref 外键因外键值校验必须有效；其余标量空单元格放行（string→`""`，数值→`None`），vector 空组丢弃。**「必填」在模型与校验层均不存在**。
- 原型：`ct/docs/design/responsive-app-shell.html` 添加字段弹窗当前把 角色（radio：无/I18N/Server-only，天然互斥）+ 约束（主键/必填 checkbox + 分隔符 input）全部读入草稿命令（`fieldType/role/pk/req/sep`），无任何互斥联动。
- 固定字段名约定：仓库内 4 张表主键全为 `primary: Id`；`ItemType.yaml` 含代号字段 `Code`（string，注释「程序引用用」）。`query-indexes` spec 规定 Code 索引字段非 i18n string、非空、表内唯一。结论：**主键字段名固定 `Id` 且必有；代号字段 `Code` 可选增加（固定名）**——主键不通过添加字段指派。

## Goals / Non-Goals

**Goals**
- 模型层补两条校验规则，保证 YAML 直写与 UI 走同一道闸
- 弹窗按固定字段名约定重新设计：主键（Id）必有不提供指派、代号（Code）可选增加并锁定取值、必填降级为只读提示、类型×角色联动、分隔符仅 vector

**Non-Goals**
- 不发明 `required`（非空校验）能力——现有强制非空/唯一是主键与 Code 索引，ref 由外键校验兜底
- 不改 i18n 管线、导出、`ref` 语义与主键类型规则（int32/int64 维持）
- 不在模型层强制「字段名必须叫 Code」（Code 索引校验已兜底非 i18n string），仅固化 UI 约定
- 本 change 不实现正式 Vue 面板的代码（`ct/web/static/`），只固化规则与原型

## Decisions

**D1 主键 × `server_only` 落模型层校验，而非仅前端禁用**
- 位置：`TableResource._validate_table`（与既有主键类型校验同处）
- 理由：只改前端等于没堵住 YAML 直写；错误信息指明表名 + 主键字段名
- 备选：仅前端禁用 → 被 YAML 绕过，否决

**D2 `separator` 仅限 vector 标量 / Enum，校验点在 `FieldDef._validate_field`**
- 非 vector 或 `vector<Record>` 声明 `separator` 报错（表名/字段名/类型）；`vector<Scalar>` / `vector<Enum>` 保留现有「separator 非空」规则
- 依据：`canonical_reader` 仅对单格 token 式 vector 使用 separator（`_split_vector`，L153-160）；`vector<Record>` 按 `excel_columns` 展开为列组（L142-152），不使用分隔符
- 备选：仅 UI 隐藏控件 → 存量 YAML 仍可写，否决

**D3 「必填」勾选移除，替换为「工具强制」只读提示**
- ref 外键、代号 `Code`（索引非空/唯一）等由工具强制的约束在弹窗中以只读提示呈现；草稿命令**移除 `req` 字段**（不再读 checkbox）
- 理由：保留 UI 上的语义说明，但不再制造无落盘目标的命令字段（`extra="forbid"` 会拒）

**D4 互斥联动 =「控件禁用 + 提交校验」双保险**
- 原型内联 JS 以禁用 + 行内提示为主；命令提交时再校验一次（防禁用态被绕过/状态残留）
- 正式面板同规则走 `schema_workspace_api` 的 Draft→Plan 校验闸

**D5 主键字段名固定 `Id`：新增字段流程不提供主键指派**
- 每表必有固定字段 `Id` 作主键（int32/int64、非 i18n、非 server_only，由模型校验 D1 + 既有类型校验保障）；添加字段弹窗**不提供「主键」checkbox**，主键维护属于表定义/固定字段编辑
- 理由：主键字段名固定，新增任意字段不可能成为主键；此前「一表一主键」的弹窗勾选模型与真实约定矛盾，移除

**D6 类型 × 角色联动：I18N 角色下类型选择器仅 `string`**
- 类型选择器按当前角色过滤候选；角色切换时若已选非法类型则回退/标错

**D7 vector 修饰符 + 内置分隔符，草稿不携带 `separator` / 可配置控件**
- 类型选择器只选基础类型 T（标量 / Enum / Record / ref），**不再提供 vector 项**；vector 由弹窗内「vector」checkbox 修饰，提交类型 = `vector<${T}>`
- 分隔符由工具内置（默认 `,`），UI 不提供输入、草稿命令不携带 `separator`；模型侧 YAML 仍可显式声明（规则见 D2）
- `excel_columns`（展开组数）仅适用于 `vector<Record>`（定长），非 vector / `vector<Scalar>` / `vector<Enum>` 声明即报错（加载期校验，见 D9）

**D8 固定字段名约定记录（Id 必有 / Code 可选）**
- 主键：字段名固定 `Id`、每表必有；不通过 `add_field` 指派，草稿命令不含 `pk`
- 代号：字段名固定 `Code`、可选增加；类型 `string`、非 `i18n`、非 `server_only`；一表至多一个；Code 索引强制非空、表内唯一（规则见 `query-indexes` spec）
- UI：弹窗提供「代号字段（Code）」开关，勾选即锁定 name=`Code`/type=`string`/role=无；已有 Code 的表阻止再次添加
- 现状核对：`ct/schema/commands.py` 仅 rename 命令，无 add_field，本约定为前瞻定义，与现有命令模型无冲突

**D9 vector 定长/变长形态**
- 形态是 Excel 录入布局，不是 FlatBuffers wire 类型：标量/Enum/string vector 可选择单格 token 变长录入，或配置 `excel_columns` 做固定列数录入；Record vector 使用展开列组。所有情况运行时仍是普通变长 vector。
- UI：勾选 vector 后显示「定长 / 变长」pill；Record 强制定长；标量/Enum/string 两种形态均可选；定长需要展开组数，变长使用内置分隔符；T=ref 仍按产品规则禁用 vector。
- 模型：`excel_columns` 允许配任意 `vector<T>`，非 vector 仍报错；reader/layout 对标量、Enum、string vector 的定长列和 Record 展开列分别处理。

## Risks / Trade-offs

- [主键 × server_only 规则可能命中存量 schema] → 任务含存量扫描（`gd/config/schemas/*.yaml`），零命中才收尾；报错信息给出字段级定位
- [移除 `req` 命令字段影响已保存草稿/命令结构] → 原型无持久化草稿，无迁移成本；正式面板接 Draft/Plan 时命令 schema 需同步（记入任务，不改变本 change 规则）
- [separator 规则误伤"无意义但无害"的存量写法] → 存量扫描确认；语义上 scalar 带 separator 本无效果，收紧属正确行为

## Migration Plan

- 无持久数据迁移。存量复核：扫描 `gd/config/schemas/*.yaml` 主键字段 `server_only` 与非 vector `separator`，确认零命中后合入主 spec
- 回滚：规则为纯加载期校验，回滚即还原校验代码 + 存量已通过，无数据残留

## Open Questions

无。方向已收敛（必填降级、主键×server_only 落模型、separator 仅 vector、固定字段名约定 Id 必有 / Code 可选、类型×角色联动），均已在 spec 与任务中固化。
