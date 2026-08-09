## Why

架构 review 定位到三个 A 档缺陷：① 主键类型没有约束——`primary` 指向
string 字段时（如 `primary: Code, type: string`）缓存层
`TableCache.ids: list[int]` 直接抛 pydantic ValidationError，`ct export`
导出中段崩溃、策划只看到 traceback；② 字段类型分派链在 reader /
validate / repository / binary_writer / json_writer / csharp / template
七个模块重复 if/elif，新增字段类型要同时改七处；③ reader coercion
失败"返回原值"、靠下游校验器兜底是隐式契约，i18n extractor 等非校验
路径需要各自记住这个约定。团队已拍板：**主键必须是 int**，问题①由此
收敛为"schema 加载期约束 + 清晰报错"，而不是支持 string 主键。

## What Changes

- **主键类型约束（行为变化）**：schema 加载阶段校验 `primary` 指向的
  字段类型必须为 `int32` 或 `int64`，否则报
  `表 {table}: 主键字段 '{primary}' 类型必须为 int32 或 int64（当前: {type}）`。
  `ct validate` / `ct export` / `ct gen-template` 一律在数据操作前友好
  失败（无 traceback），不再出现导出中段崩溃。缓存 `ids: list[int]`、
  二进制 / accessor / ref 校验继续沿用 int 主键假设，无需改动格式。
- **类型分派收敛（纯重构）**：新增 `ct/schema/type_traits.py`，提供字段
  类型 traits 注册表（coerce / validate / fbs 类型 / json 值 / C# 类型 /
  表头类型注解），七个模块的 if/elif 分派链改查表；CLI 输出文本与产物
  格式逐字不变。
- **coercion 契约显式化（纯重构）**：`ParsedRows` 携带解析期问题列表
  （excel_row / column / value / field 齐备）；reader 转换失败直接产出
  行列定位的 issue，不再静默返回原值；`parse_and_validate` 汇集消费，
  extractor 等非校验路径显式跳过坏行。错误文本与 Change 2 规格逐字一致。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `schema-management`: 新增主键类型约束——主键字段必须是 `int32` 或
  `int64`，schema 加载阶段校验并给出清晰报错。（其余两项为行为不变的
  重构，不产生 spec delta。）

## Impact

- **改动代码**：`tool/ct/schema/models.py`、`tool/ct/excel/reader.py`、
  `tool/ct/validate/types.py`、`tool/ct/schema/repository.py`、
  `tool/ct/export/binary_writer.py`、`tool/ct/export/json_writer.py`、
  `tool/ct/export/csharp_accessor_generator.py`、`tool/ct/excel/template.py`、
  `tool/ct/export/i18n/extractor.py`。
- **新增代码**：`tool/ct/schema/type_traits.py`。
- **新增测试**：string/非 int 主键友好报错（CLI 回归，覆盖 validate 与
  export）、type_traits 全类型覆盖、既有 golden 输出逐字不变。
- **无依赖变更**：不新增第三方包；缓存格式与导出产物格式不变。
