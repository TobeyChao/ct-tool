# CLI 文本与产物对照（留档 Python 基线 vs 原生内核）

由 `node native/tools/parity/cli-text-diff.mjs` 生成；夹具是
`native/fixtures/export_pipeline/workspace` 的临时副本，真实 `gd/` 未被写入。

- 独立参考：冻结 CLI 留档 native/docs/baseline/cli-text-diff-python.json（校验 SHA-256，不执行 Python）
- 原生内核：`../../../../../../../../Users/tobeychao/Documents/Projects/ct-tool/native/target/debug/ct`

## 场景结果

- ct export：退出码 0/0，文本一致，正式产物 11/11 个，字节一致，生成缓存 13 条（build_canonical_bundle 2、build_canonical_table_bytes 3、generate_csharp_accessor 1、generate_csharp_enums 1、generate_lua_accessor 1、generate_lua_enums 1、json 2、table_fbs_text 1、types_fbs_text 1） vs 13 条（build_canonical_bundle 2、build_canonical_table_bytes 3、generate_csharp_accessor 1、generate_csharp_enums 1、generate_lua_accessor 1、generate_lua_enums 1、json 2、table_fbs_text 1、types_fbs_text 1）
- ct export：退出码 0/0，文本一致，正式产物 11/11 个，字节一致，生成缓存 13 条（build_canonical_bundle 2、build_canonical_table_bytes 3、generate_csharp_accessor 1、generate_csharp_enums 1、generate_lua_accessor 1、generate_lua_enums 1、json 2、table_fbs_text 1、types_fbs_text 1） vs 13 条（build_canonical_bundle 2、build_canonical_table_bytes 3、generate_csharp_accessor 1、generate_csharp_enums 1、generate_lua_accessor 1、generate_lua_enums 1、json 2、table_fbs_text 1、types_fbs_text 1）
- ct export --all：退出码 0/0，文本一致，正式产物 11/11 个，字节一致，生成缓存 13 条（build_canonical_bundle 2、build_canonical_table_bytes 3、generate_csharp_accessor 1、generate_csharp_enums 1、generate_lua_accessor 1、generate_lua_enums 1、json 2、table_fbs_text 1、types_fbs_text 1） vs 13 条（build_canonical_bundle 2、build_canonical_table_bytes 3、generate_csharp_accessor 1、generate_csharp_enums 1、generate_lua_accessor 1、generate_lua_enums 1、json 2、table_fbs_text 1、types_fbs_text 1）
- ct validate：退出码 0/0，文本一致，正式产物 11/11 个，字节一致，生成缓存 13 条（build_canonical_bundle 2、build_canonical_table_bytes 3、generate_csharp_accessor 1、generate_csharp_enums 1、generate_lua_accessor 1、generate_lua_enums 1、json 2、table_fbs_text 1、types_fbs_text 1） vs 13 条（build_canonical_bundle 2、build_canonical_table_bytes 3、generate_csharp_accessor 1、generate_csharp_enums 1、generate_lua_accessor 1、generate_lua_enums 1、json 2、table_fbs_text 1、types_fbs_text 1）
- ct status：退出码 0/0，文本一致，正式产物 11/11 个，字节一致，生成缓存 13 条（build_canonical_bundle 2、build_canonical_table_bytes 3、generate_csharp_accessor 1、generate_csharp_enums 1、generate_lua_accessor 1、generate_lua_enums 1、json 2、table_fbs_text 1、types_fbs_text 1） vs 13 条（build_canonical_bundle 2、build_canonical_table_bytes 3、generate_csharp_accessor 1、generate_csharp_enums 1、generate_lua_accessor 1、generate_lua_enums 1、json 2、table_fbs_text 1、types_fbs_text 1）
- ct i18n status：退出码 0/0，文本一致，正式产物 11/11 个，字节一致，生成缓存 13 条（build_canonical_bundle 2、build_canonical_table_bytes 3、generate_csharp_accessor 1、generate_csharp_enums 1、generate_lua_accessor 1、generate_lua_enums 1、json 2、table_fbs_text 1、types_fbs_text 1） vs 13 条（build_canonical_bundle 2、build_canonical_table_bytes 3、generate_csharp_accessor 1、generate_csharp_enums 1、generate_lua_accessor 1、generate_lua_enums 1、json 2、table_fbs_text 1、types_fbs_text 1）

## 已知且刻意保留的差异

- 控制台编码：Python 在中文 Windows 下按locale(GBK) 输出，原生内核统一 UTF-8。
  本对照按各自编码解码后再比文本，因此差异只反映内容本身。
- 生成缓存条目名是「引擎内部 canonical 键」的内容哈希，不要求跨引擎同名；
  正式产物 `output/**` 才要求逐字节一致。
- Windows 上 `output/json/Item_en.json` 一类产物名，Python 经 `os.path.normcase`
  会把大小写归一，原生内核保留原大小写；本对照按小写键比较，差异不会误报。

## 未解决差异

无。
