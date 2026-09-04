# repository-cutover fixture（canonical 输入源）

供 cutover 集成测试与 Web 浏览器测试作为工作区**输入**：

- `config/` `excel/` `i18n/` —— 输入源（4 张表 schema + Excel + 翻译），测试拷贝到临时工作区后做 canonical 转换/导出。

输出产物一律由测试在临时工作区重新导出，**不落库**。旧格式产物快照（`output/generated|fbs|binary|json`、`baseline.json`、`tests/fixtures/accessor/*.golden`）已随 canonical-only 收口删除。
