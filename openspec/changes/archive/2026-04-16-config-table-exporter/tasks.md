## 1. 项目脚手架与依赖

- [x] 1.1 初始化 Python 项目结构（`ct/` 包，`pyproject.toml`，`requirements.txt`）
- [x] 1.2 添加依赖：openpyxl、flatbuffers、typer、pydantic、pyyaml
- [x] 1.3 创建 `config/global.yaml` 示例配置（primary_lang、secondary_langs、输出路径、flatc_path）
- [x] 1.4 实现 `ct/config.py`：加载并校验 global.yaml，暴露全局配置对象

## 2. Schema 管理

- [x] 2.1 实现 `ct/schema/models.py`：Pydantic 模型（BaseFieldDef、EnumFieldDef、StructFieldDef、ArrayFieldDef、TableSchema），校验字段类型合法值，array<struct> 在加载阶段报错，禁止 i18n + server_only 同时标记
- [x] 2.2 实现 `ct/schema/loader.py`：扫描 `schemas/*.yaml`，加载所有 TableSchema，检测重复表名，计算每表 max_nesting_depth
- [x] 2.3 实现引用依赖图构建：解析所有 `ref` 字段，构建有向图
- [x] 2.4 实现拓扑排序：基于依赖图输出处理顺序，检测循环引用并报错

## 3. Excel 处理

- [x] 3.1 实现 `ct/excel/reader.py`：使用 openpyxl read_only 模式读取 Excel，根据 schema 计算头部行数（max_depth+2）并跳过，struct 多列重组为嵌套对象，array 按分隔符拆分并校验元素类型
- [x] 3.2 实现 `ct/excel/diff.py`：计算 Excel 文件 MD5 hash，与 `cache/state.json` 比对，返回变更表列表
- [x] 3.3 实现 `ct/excel/template.py`：根据 schema 计算最大嵌套深度，生成动态行数头部；struct 列水平合并、非嵌套列垂直合并；类型行标注 enum/ref/i18n/array 注解

## 4. 数据校验

- [x] 4.1 实现 `ct/validate/types.py`：按字段类型校验每行数据（含 enum 值域校验、array 元素逐个校验、struct 子字段递归校验），收集全部错误后统一报告
- [x] 4.2 实现主键唯一性校验：检测同表重复主键
- [x] 4.3 实现 `ct/validate/refs.py`：按拓扑顺序校验 ref 字段，使用已加载表或缓存 id 集合
- [x] 4.4 实现策划友好错误格式化：`[表名.xlsx] 第N行 字段名：...`，支持 `--verbose` 显示堆栈

## 5. 缓存管理

- [x] 5.1 实现 `ct/cache/state.py`：读写 `cache/state.json`（版本化格式：version、tables.{name}.hash/ids/fbs_bytes_hash/exported_at），版本不匹配时全量重建
- [x] 5.2 实现 cache 更新逻辑：只在表成功导出后更新对应条目，同时存储该表序列化后的 FlatBuffers bytes hash
- [x] 5.3 实现从 cache 读取 id 集合：供未变化被引用表的引用校验使用
- [x] 5.4 实现从 cache 复用 FlatBuffers bytes：Bundle 全量重写时，未变化表使用缓存的序列化 bytes

## 6. i18n 流水线

- [x] 6.1 实现 `ct/export/i18n/extractor.py`：从解析数据中提取 i18n 字段，生成/更新 `strings_source.json`（new/translated/stale 状态）
- [x] 6.2 实现 stale 检测：源文本变化时将对应条目状态改为 stale，删除行时移除条目
- [x] 6.3 实现 `ct/export/i18n/merger.py`：读取 `strings_{lang}.json`，将译文映射到行数据，缺失时回退主语言并 warning
- [x] 6.4 实现 `ct/export/i18n/writer.py`：导出结束后汇总 stale 条目统计，按表分组输出

## 7. JSON 导出

- [x] 7.1 实现 `ct/export/json_writer.py`：将行数据序列化为 `{ "items": [...] }` 格式，输出 `output/json/{table}_{lang}.json`
- [x] 7.2 处理 server_only 字段：JSON 包含，Binary 排除
- [x] 7.3 支持 `json_key` schema 配置项自定义根 key（默认表名加 s）

## 8. FlatBuffers 导出

- [x] 8.1 实现 `ct/export/fbs_generator.py`：从 TableSchema 生成 `.fbs` 文件；enum 生成 `enum Name: byte`；struct 生成 FlatBuffers `table`（非 struct）；array 生成 vector 类型；包含主表结构
- [x] 8.2 生成 i18n 变体结构：有 i18n 字段的表额外生成 `ItemI18nEntry` / `ItemI18nTable`
- [x] 8.3 生成 `container.fbs`：定义 `BundledTable` 和 `DataBundle`
- [x] 8.4 实现 `ct/export/binary_writer.py`：使用 flatbuffers Python builder 构建各表 Binary bytes
- [x] 8.5 实现主语言 Bundle 写入：将所有表的完整数据打包为 `DataBundle`，输出 `data_{primary}.bin`；增量导出时全量重写 Bundle（变化表重新序列化，未变化表从 cache 复用 bytes）
- [x] 8.6 实现次语言 i18n Bundle 写入：只打包有 i18n 字段的表的 I18nTable，输出 `data_{lang}.bin`；同样全量重写
- [x] 8.7 实现 flatc 调用：从 `global.yaml` 读取 `flatc_path`（相对路径），subprocess 调用 flatc 分别编译 .fbs，`--cpp` 输出 `output/generated/cpp/`，`--csharp` 输出 `output/generated/csharp/`，`--lua` 输出 `output/generated/lua/`；启动时检测 flatc 是否存在于配置路径
- [x] 8.8 实现 `ct/export/csharp_accessor_generator.py`
- [x] 8.9 实现 `ct/export/lua_accessor_generator.py`

## 9. CLI 接口

- [x] 9.1 实现 `ct/cli.py`：Typer 应用入口，注册 export / validate / gen-template / status 命令
- [x] 9.2 实现 `ct export`：增量导出主流程，串联变更检测 → 校验 → i18n → JSON/Binary → cache 更新
- [x] 9.3 实现 `ct export --all / --table / --lang` 选项
- [x] 9.4 实现 `ct validate`：只走解析和校验，不输出产物，返回正确退出码
- [x] 9.5 实现 `ct gen-template [--all / --table]`：调用 excel/template.py
- [x] 9.6 实现 `ct status`：对比当前 hash 与缓存，列出变更和未变更的表

## 10. 集成测试与示例

- [x] 10.1 创建示例 schema（item、item_type、quest），含引用、i18n、enum、struct（drop_range）、array（tags）字段
- [x] 10.2 创建对应示例 Excel 文件（含主语言数据）
- [x] 10.3 端到端测试：`ct export --all`，验证 JSON、Binary、C# Accessor、Lua Accessor 产物正确
- [x] 10.4 测试增量导出：修改一张表后再次 export，验证只重新导出变更表
- [x] 10.5 测试 i18n 流程：填写翻译文件，验证次语言 JSON 和 i18n Bundle 正确
- [x] 10.6 编写 README：安装说明、flatc 安装指引、schema 格式文档、CLI 命令说明
- [x] 10.7 提供 C++ 参考实现模板：`docs/cpp_reference/` 目录下放置 `gd_native.h` / `gd_native.cpp`（GD_Load / GD_GetMainBytes / GD_GetI18nBytes / GD_Unload）和 `gd_xlua_register.cpp`（xLua 注册代码），附使用说明；此代码为手写参考，不由工具自动生成
