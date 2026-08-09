## Context

现状与动机见 proposal.md — Why。约束与已确认事实：

- CLI 正常路径输出与产物格式逐字不变（Change 2 规格 + golden 测试兜底）；
- 测试基线 166 passed；
- 全仓库（gd 四张表 + 测试 fixtures）主键均为 int32，主键约束落地后
  存量数据不受影响；
- 团队决策：主键必须是 int，不做 string 主键支持。

## Goals / Non-Goals

**Goals:**

- schema 加载期拦截非 int 主键，任何命令在数据操作前得到清晰友好报错；
- 字段类型相关分派收敛到单一注册表，"新增类型 = 注册表加一行"；
- coercion 失败显式化为带行列定位的 issue，校验与提取路径共享同一契约。

**Non-Goals:**

- 不支持 string / enum 主键（已决策 int-only）；
- 不引入字段类型多态类层次（闭集 + 注册表足够）；
- 不改 CLI 正常路径文本、不改 Excel / Binary / FBS / Accessor 产物格式；
- 不改缓存 state.json 格式（`ids` 仍是 `list[int]`，无需版本迁移）。

## Decisions

### D1 主键必须是 int32/int64：schema 加载期约束，不做 string 主键支持

做法：在 `TableSchema._validate_table`（model_validator，与"主键必须在
字段列表"同层）校验 `primary_field.type in ("int32", "int64")`，否则抛
`ValueError(f"表 {table}: 主键字段 '{primary}' 类型必须为 int32 或 int64
（当前: {type}）")`。错误经 `repository._schema_error_text` 包装为
`加载 schema 失败 [{file}]: ...`，复用现有 CLI 友好渲染路径。

为什么：主键的数值语义贯穿全链路——缓存 ids 排序、ref 跨表校验、
binary 槽位、accessor 类型、i18n PK 字段。支持 string 主键需要 ids
归一化、混合键排序、binary/accessor/i18n PK 类型分派，成本高、收益低。
参照 Luban 等配表工具：主键约束收敛在 schema 层，运行时全链路保持
int 假设。

- 备选 A（缓存 ids 改 `Union[int, str]` 支持 string 主键）：被用户决策
  否决。即使要做，pydantic smart mode 会把 `"123"` 自动转成 int，
  破坏 string 主键语义，需要显式 TaggedUnion 或字符串归一化，复杂度
  不成比例。
- 备选 B（数据校验期再报错）：太晚——导出中段缓存更新仍可能崩，且
  `gen-template` 也应拒绝非法 schema。
- 语义补充：int32 与 int64 均视为 int；float/double/bool/string/enum/
  struct/array 一律拒绝。float 拒绝是因为主键要求整数值语义，float
  会引入精度与唯一性歧义。

### D2 字段类型 traits 注册表（闭集枚举 + 查表，不用多态类）

借鉴：Orleans `CodecProvider`、Eventuous `TypeMap` 的"类型名 → handler"
注册表模式；Rust 社区对闭集枚举推荐 match/查表而非 trait 对象多态的
共识——闭集 + 无行为差异时，多态是过度设计（YAGNI）。

做法：`ct/schema/type_traits.py` 定义 `FieldTraits`（dataclass），字段：
`coerce`、`validate`、`fbs_type`、`json_value`、`csharp_type`、
`excel_annotation`（表头类型注解）；导出 `TYPE_TRAITS: dict[str, FieldTraits]`
作为唯一分派表。基础类型直接注册；enum/struct/array 是组合逻辑（enum
走 values 校验、struct 走叶子展开、array 走 element traits + separator），
在 traits 工厂中集中处理，不再散落各模块。

替换的七处分派（任务见 tasks.md 阶段 B）：reader `_coerce` /
`_coerce_element`、`validate/types.py`、`repository._resolve_field_type`、
`binary_writer`（标量槽位 / 向量 / struct 构建）、`json_writer`、
`csharp_accessor_generator`、`excel/template.py` 表头注解。

- 备选：`FieldType` 抽象基类 + 子类（Strategy pattern）——字段类型是
  YAML 字面量闭集（9 种 + array 元素子集），子类化引入文件与命名负担
  而无扩展收益。
- 安全网：注册表覆盖测试遍历 `ALL_FIELD_TYPES`，断言每张分派表都有
  handler；golden 测试（json / binary / fbs / accessor）断言产物逐字不变。

### D3 coercion 显式化：解析期产出问题列表（Parse, Don't Validate）

借鉴：*Parse, Don't Validate*——解析结果把"无效"编码进结构本身，而不是
返回原值、让下游再次推断有效性。对应到本代码：转换失败 = 解析失败，
应携带定位产出 issue。

现状：`_coerce_scalar` 失败返回原值（有意为之，避免 traceback），
`validate_table` 靠 `_validate_field_value` 兜底报错；i18n extractor
需要"跳过主键类型不符的行"的隐式约定（refactor-code-smells 已补一处，
但契约仍是隐式的）。问题：每个消费 `ParsedRows` 的新路径都必须记得
这个约定，漏了就产生脏数据。

做法：`ParsedRows` 新增 `issues: list[ValidationIssue]`；reader 在转换
失败时产出带 excel_row/column/value/field 的 issue（失败判定由 traits
提供，不依赖"返回原值"猜测）；`parse_and_validate` 将 `ParsedRows.issues`
与既有校验结果汇集（保序、避免双报，错误文本逐字不变）；extractor
改为显式过滤带 issue 的行。

- 备选：维持"返回原值 + 校验器兜底"——契约仍然隐式，每个消费路径各
  维护一份"跳过坏行"逻辑，正是本次要消除的散落。
- 风险与缓解：错误文本必须与 Change 2 规格逐字一致 → 先跑现有
  `test_location` / `test_issues` 特征测试建立基线，再动 reader；重构后
  同一组断言必须原样通过。

## Risks / Trade-offs

- [主键约束错误文本与既有错误格式不一致] → 复用现有 `_schema_error_text`
  与 CLI 渲染路径，消息沿用"表 X: ..."前缀约定；新增 CLI 回归测试断言
  具体文案。
- [type_traits 迁移中某处分派漏改导致产物漂移] → 阶段 B 每迁移一个模块
  即跑对应 golden/特征测试；注册表覆盖测试保证无遗漏 handler。
- [coercion 显式化后错误双报（reader issue + validate 兜底）] →
  `parse_and_validate` 汇集实现以现有错误文本为唯一基准，先测后改。
- [存量 string 主键 schema 被新约束拒绝] → 已核查 gd 四张表与测试
  fixtures 全部为 int32 主键；外部仓库若有 string 主键属预期行为变化，
  报错会明确指出修改点。

## Migration Plan

- 阶段 A（主键约束）→ 阶段 B（type_traits）→ 阶段 C（coercion 显式化）；
  每阶段 `cd tool && pytest` 全绿后 `git add/commit`。
- 无数据迁移：cache 格式与产物格式不变；约束只影响非法 schema，回滚
  即恢复旧行为。
- 验收线：既有 166 测试 + 新增测试全绿；`ct export` / `ct validate` /
  `ct gen-template` 正常路径文本与产物逐字不变；string 主键 schema 在
  三个命令下均为友好报错（无 traceback）。
