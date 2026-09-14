## REMOVED Requirements

### Requirement: Index data preflight
**Reason**: 保存被收窄为 YAML-only 且不再扫描 Excel 数据，原「两道闸门」中的编辑器侧数据预检随 Change Plan 一起移除；保留该措辞会让主规格继续要求一个已被删除的机制。
**Migration**: 数据侧约束（CodeName 非空、精确唯一、角色与类型）仍由 validate/export 的同一读取闸门执行，错误码与定位不变，见本能力新增的 `CodeName data gate before artifacts`；结构侧约束（索引声明合法性、合格 `CodeName` 字段）仍由 `Table-level query index model` 的加载期/候选期校验负责。

## ADDED Requirements

### Requirement: CodeName data gate before artifacts
`CodeName` SHALL 为非 i18n string、**非空**且按精确原字符串在表内**唯一**，该校验 SHALL 只在 validate/export 读取数据时执行：违反时导出 SHALL 失败且**不落任何产物**，issue 带表名、Excel 行号、列与原始值（重复值还 SHALL 指出首次出现的行号），错误码 `duplicate_codename`（空值报 `type`）。YAML 保存 SHALL NOT 读取 Excel 数据，也 SHALL NOT 因数据重复、空值或类型问题失败。

> 数据闸门是必需的，而不只是「编辑器里拦一下」：导出器建桶表时对空串跳过、也**不判重**，所以没有这道校验时，两行写同一个 `CodeName` 会**静默**导出成功，而运行期 `ByCodeName()` 只命中探测序更靠前的那个 —— 另一行永远查不到且毫无提示。保存侧不再有数据预检，因此这道闸门是数据约束的唯一执行点。

#### Scenario: Duplicate CodeName blocks export
- **WHEN** 声明了 codename 索引的表里两行数据具有相同的 CodeName
- **THEN** validate/export 失败并列出两行的 Excel 行号和原始值，`output/` 不产生新产物

#### Scenario: Blank CodeName blocks export
- **WHEN** 声明了 codename 索引的表里某行 CodeName 为空（或该字段整个缺失）
- **THEN** 导出失败（该行永远查不到）

#### Scenario: Saving YAML does not scan data
- **WHEN** 用户在候选里造成重复或空 CodeName 数据并保存 YAML
- **THEN** 保存只做结构校验并成功落盘，数据问题留给 validate/export 报告

#### Scenario: Tables without the index stay unaffected
- **WHEN** 表没有声明 codename 索引，即使 CodeName 列有重复或空值
- **THEN** 校验与导出都不报错（此时它只是一个普通字段）

#### Scenario: Index field role is validated before data reading
- **WHEN** `CodeName` 带 `i18n: true`、不是 string、是 vector，或表里没有合格 `CodeName` 字段
- **THEN** 加载期/候选期校验拒绝并说明缺哪一种条件，不等到读取数据阶段
