## 0. 手法映射（第二层绑定）

每个阶段对应《重构》的具体手法；实施时先精读该手法小节的「做法」再动手，
每一步完成即跑测试（所有步骤均在 `cd tool && pytest` 下执行）。

| 阶段 | 手法 | 出处 |
|---|---|---|
| A 主键 int 约束 | 前置校验（行为变更，非重构） | 沿用既有 schema 加载期校验约定 |
| B traits 注册表 | 以多态取代条件表达式 10.4（闭集收敛为查表）；函数组合成类 6.9 | `references/refactorings/ch10.md` / `ch06.md` |
| C coercion 显式化 | 拆分阶段 6.11；提炼函数 6.1 | `references/refactorings/ch06.md` |

实施纪律：每步遵循「做法」的最小步骤清单；失败回退最近绿点换更小的步子；
每阶段收尾跑完整测试 + `git diff` 复核（见 design.md Migration Plan）。

## 1. 阶段 A：主键 int 约束（先补失败测试）

- [x] 1.1 新增 CLI 回归测试（`tool/tests/cli/test_schema_errors.py` 或新
      文件）：`primary: Code, type: string` 的 schema 在 `ct validate` 与
      `ct export` 下均为 exit_code != 0、无 Traceback、报错含"主键"与
      "string"；`primary: Id, type: int64` 正常加载并可通过 validate
- [x] 1.2 `TableSchema._validate_table` 增加校验：`primary_field.type`
      不在 `("int32", "int64")` 时抛
      `ValueError(f"表 {table}: 主键字段 '{primary}' 类型必须为 int32 或 int64（当前: {type}）")`
      （与"主键不在字段列表"校验同层）
- [x] 1.3 手动复跑原崩溃命令（string 主键表 + `ct export`）确认改为加载期
      友好报错；grep 确认 gd 与 tests 无 string/非 int 主键存量
- [x] 1.4 `cd tool && pytest` 全绿，提交阶段 A

## 2. 阶段 B：字段类型 traits 注册表

- [x] 2.1 新增 `tool/ct/schema/type_traits.py`：`FieldTraits` dataclass
      （coerce / validate / fbs_type / json_value / csharp_type /
      excel_annotation）+ `TYPE_TRAITS` 注册表；enum/struct/array 组合逻辑
      集中于此；新增覆盖测试遍历 `ALL_FIELD_TYPES` 断言每张分派表有 handler
- [x] 2.2 `excel/reader.py` 的 `_coerce` / `_coerce_element` 改查表（保留
      array_element 语义、bool 别名集、int 截断规则；先跑 reader/validate
      特征测试）
- [x] 2.3 `validate/types.py::_validate_field_value` 改查表
- [x] 2.4 `schema/repository.py::_resolve_field_type` 改查表（fbs 类型）
- [x] 2.5 `export/binary_writer.py` 标量槽位 / 向量 / `_build_struct` /
      `build_table_bytes` / `_build_array` 分派改查表
- [x] 2.6 `export/json_writer.py` 字段序列化改查表
- [x] 2.7 `export/csharp_accessor_generator.py` 类型映射与字段访问器分支
      改查表
- [x] 2.8 `excel/template.py` 表头类型注解改查表
- [x] 2.9 golden 测试（json / binary / fbs / csharp / lua）全绿，`git diff`
      复核产物逐字不变；`cd tool && pytest` 全绿，提交阶段 B

## 3. 阶段 C：coercion 契约显式化

- [x] 3.1 先跑 `tool/tests/validate/test_location.py` 与 `test_issues.py`
      建立错误文本基线（Change 2 规格）
- [x] 3.2 `ParsedRows` 新增 `issues: list[ValidationIssue]`；reader 转换
      失败（失败判定由 traits 显式提供，不依赖"返回原值"猜测）时产出带
      excel_row/column/value/field 的 issue
- [x] 3.3 `parse_and_validate` 汇集 `ParsedRows.issues` 与既有校验结果
      （保序、避免双报），错误文本与基线逐字一致
- [x] 3.4 `export/i18n/extractor.py` 显式跳过带 issue 的行，替代隐式
      "主键类型不符跳过"判断，行为不变
      （`test_extract_skips_rows_with_bad_primary_type` 原样通过）
- [x] 3.5 `cd tool && pytest` 全绿 + 完整功能回归（export / validate /
      i18n / gen-template 各跑一轮），提交阶段 C
