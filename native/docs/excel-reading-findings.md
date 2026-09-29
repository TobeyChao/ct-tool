# Excel 读取选型结论（rust-native-core 任务 1.5）

日期：2026-09-17。基线：openpyxl 3.1.5（`read_only=True, data_only=True`，
与 `ct/excel/canonical_reader.py` 相同打开方式）。候选：calamine 0.36。

**结论：calamine 作为读取实现通过全部对照项，选型成立。**

## 对照方法与夹具

`fixtures/excel/generate.py`（ct/.venv 运行）生成 6 个夹具并用 openpyxl
导出期望值到 `expected/*.json`；`tests/compat/tests/excel_edge.rs` 用
`ct_excel::reader::probe_xlsx` 逐项对照（sheet 列表、活跃 Sheet、日期系统、
全部非空单元格的坐标/类型/值）。

| 对照项 | 夹具 | 结果 |
|---|---|---|
| 活跃 Sheet（非首个） | active_sheet.xlsx（活跃=第 2 个） | ✅ 一致 |
| 稀疏行/空单元格 | active_sheet.xlsx（空行 3/8/9、尾部行 10） | ✅ 一致，坐标 1-based 对齐 |
| 空串 vs 缺失 | active_sheet.xlsx A5 | ✅ openpyxl 写空串不落盘，读回 None；calamine 同样为空 |
| Unicode/Emoji | active_sheet.xlsx A6 | ✅ 一致 |
| 浮点/0/bool | active_sheet.xlsx | ✅ 一致（数值按 f64 比较） |
| 日期 1900 系 | dates_1900.xlsx（含闰日边界） | ✅ serial→ISO 一致 |
| 日期 1904 系 | dates_1904.xlsx（workbookPr date1904） | ✅ 一致 |
| 公式缓存值 | formula_cache.xlsx（数值/字符串缓存、无缓存） | ✅ 有缓存读缓存，无缓存读为空 |
| 错误值 | errors.xlsx（#DIV/0! #N/A #VALUE! #REF!） | ✅ 一致 |
| 富文本表头 | rich_text.xlsx（多 run 共享字符串） | ✅ 拼接为纯文本，与 openpyxl 一致 |
| 固定 vector | active_sheet.xlsx B10 `[1, 2, 3]` | ✅ 读取层为原始文本，拆分在 canonical 层 |

## calamine 缺口与对策

1. **不暴露活跃 Sheet 与工作区日期系统**。`Reader` trait 无 activeTab API，
   `Data::DateTime` 只携带单元格级 is_1904。对策：直接解包读
   `xl/workbook.xml` 的 `workbookView activeTab` 与 `workbookPr date1904`
   （`reader.rs::workbook_view_flags`，zip + 属性扫描）。升级为完整 XML
   解析时行为必须保持。
2. **DateTimeIso / DurationIso**（ISO 串形态的日期/时长）按文本透传，
   与 openpyxl 行为一致；夹具未覆盖，出现差异时再专项处理。
3. **数值无 int/float 区分**：openpyxl 按文本形态分 int/float，calamine
   对 xlsx 统一解析为浮点；对照按 f64 比较。canonical 的整数标量值域
   校验（`_coerce_scalar`）本身就是「float 先转 int 再查值域」，不受影响。
4. `CellErrorType` 恰好 8 个变体且非 non_exhaustive：映射表穷举，
   上游新增变体时编译失败，显式决定映射。

## 制作夹具时确认的 openpyxl 行为（Rust 侧已规避）

- read_only 模式依赖 `<dimension>` 元素定界，缺省读为空；cell 的 `r`
  属性与所在 `<row>` 不一致时单元格被静默丢弃。Rust 侧按 cell 坐标读取，
  不受此影响，但模板生成（任务 1.6）必须写出规范的 dimension/坐标，
  否则依赖 dimension 的读取器（如 openpyxl read_only）读不回。
- 空串 `""` 不落盘（读回 None）。模板不得依赖空串与缺失的区分。
- serial→日期以 1899-12-30 为基（含 1900 闰年 bug 兼容）：serial 1 得
  1899-12-31 而非 Excel 显示的 1900-01-01，serial 61 起与显示一致。
  Rust 转换（`serial_to_iso`）按此语义实现。