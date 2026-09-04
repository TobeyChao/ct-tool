# repository-cutover fixture（canonical 输入源）

供 cutover 集成测试与 Web 浏览器测试作为工作区输入：

- `config/` `excel/` `i18n/` —— 输入源（4 张表 schema + Excel + 翻译），测试拷贝到临时工作区后做 canonical 转换/导出。
- `output/json/*` —— JSON 语义 golden：`test_canonical_export_parity_with_pregolden` 用其对拍 canonical 导出结果。

旧格式产物快照（`output/generated|fbs|binary`、`baseline.json`、`tests/fixtures/accessor/*.golden`）已随 canonical-only 收口删除；输出产物一律由测试在临时工作区重新导出，不再落库。
