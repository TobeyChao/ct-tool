# 测试夹具

测试仅使用这里的小型冻结输入和临时工作区，不使用真实 `gd/`。
大规模基准由 `xtask bench-fixtures` 写入 `target/` 或显式输出目录，不提交生成结果。

## 独立参考数据与再生

`compat-manifest.json` 固定 binary、excel、export_pipeline、fingerprints、schema_state、template
六类共 129 个输入/参考文件的 SHA-256、验收目标和历史来源。
历史生成器的七份文本快照保存在 `native/docs/baseline/source/`；它们仅供追溯，不执行。
原 `.py` 文件待 G1/G2/G3 全部通过后才退役。

在仓库根目录运行：

```sh
cargo run --manifest-path native/Cargo.toml -p ct-xtask --locked -- compat-fixtures
cargo test --manifest-path native/Cargo.toml -p ct-tests-compat --locked
```

第一条命令先验证全部冻结输入、期望值和来源快照，再把 `excel/source/` 的独立 OOXML
部件打包为六个工作簿，默认写入 `native/target/compat-fixtures/excel/`。
支持 `--out /tmp/ct-excel-inputs`，输出不能覆盖冻结夹具目录。
`excel_edge` 测试在临时目录自动再生这六个输入，覆盖活跃工作表、1900/1904 日期系统、
公式缓存、错误单元格与富文本；期望 JSON 保持原 openpyxl 探针结果。
源文件摘要不符或场景缺失会明确失败，不缩减测试。

其他领域的 Schema、数据工作簿、成功账本及 golden 是版本化的独立输入和期望值，
无需执行旧生成器。测试在临时目录生成原生实际结果，再与冻结期望比较。
禁止用被测内核生成新的期望值来修复失败；契约变更需独立确定新期望并记录出处。

| 领域 | 原生验收目标 |
|---|---|
| Binary | `binary_golden` |
| Excel 读取 | `excel_edge` |
| 导出流水线 | `export_pipeline` |
| 指纹 | `fingerprints` |
| Schema 状态/草稿/保存 | `schema_parity`、`schema_draft`、`schema_save` |
| 模板/布局/JSON/FBS/Accessor | `template_semantics`、`layout_manifest`、`canonical_read`、`json_export`、`fbs_export`、`accessor_golden` |

`template_semantics` 使用独立 XML/ZIP 读取器完整比较原生模板与冻结 openpyxl 语义，
包括单元格值、填充、富文本、合并、冻结、数据验证、批注、列宽、行高和自定义属性。
它也读取历史工作簿，验证读取器本身与独立参考一致；故意损坏表头必须被检出。
仅归一化既有参考允许的时间戳、颜色编码、列宽编码差异及行高舍入。

手动比较已生成的模板：

```sh
cargo run --manifest-path native/Cargo.toml -p ct-xtask --locked -- template-compare /tmp/template.xlsx native/fixtures/template/expected/template_v1.semantics.json
```

`workspaces/`、`journals/`、`protocol/` 和 Web 冻结夹具有各自的验收目标；
此六类清单不替代整个工作区、HTTP 或浏览器验收。
