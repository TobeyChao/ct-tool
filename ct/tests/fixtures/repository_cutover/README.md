# repository-cutover fixture（canonical 工作区输入）

供 export/e2e 集成测试与 Web 浏览器测试作为工作区**输入**：

- `config/` `excel/` `i18n/` —— canonical 工作区输入源（4 张表 schema + `config/types/` 具名类型 + Excel + 翻译），测试拷贝到临时工作区后直接导出。

已收口为 canonical-only：无 legacy→canonical 转换环节，无落库输出产物。输出一律由测试在临时工作区重新生成。
