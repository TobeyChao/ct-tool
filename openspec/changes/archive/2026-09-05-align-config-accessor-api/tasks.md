## 1. Reader 运行时（独立项目，指针式）

- [x] 1.1 新建 reader 运行时（纯 C# + unsafe，无 Unity 依赖）：`WireReader` 指针式字段读取（`I8/I32/I64/F32/F64/Bool/Str`）
- [x] 1.2 新增 `VecBase(obj, slot)`：返回向量元素区基址；缺省返回 `IntPtr.Zero`
- [x] 1.3 新增每表查询：`Count(table)` / `ByIndex(table, i)` / `ByID(table, id)`，保留 `IndexSearch`
- [x] 1.4 新增容器：`NArray<T>`（unmanaged）、`NStructArray<T>`、`NString`；构造时调用 `VecBase`，提供 `Length`/`[i]`/`IEnumerable<T>`/`SafeGet`
- [x] 1.5 引导层：load bundle → 取表 → `VectorBase`/`Count`/`RowAt`（供 accessor 的 `ByID/ByIndex`）
- [x] 1.6 版本/epoch 守卫（对齐 harmony `pVersion`/`PointerCheck`），随表重载/切语言失效
- [x] 1.7 `NStringCache` 字符串驻留
- [x] 1.8 在 `test-proj/ConfigAccessorBench` 集成本 reader（替代临时 WireReader），跑通正确性

## 2. Accessor 模型（`canonical_accessor_model.py`）

- [x] 2.1 `AccessorField` 增加 `ref` 元数据（目标表.字段）
- [x] 2.2 携带容器类型文本（`NArray<int>`、`NStructArray<T>`）
- [x] 2.3 确保 enum 类型名 / vector 元素类型可用
- [x] 2.4 `build_accessor_model` 接收表映射，解析 ref 目标表
- [x] 2.5 改用指针式行句柄（`{Table}Row` 持 `IntPtr _row`），替代 P1#2 的 `(TableName, slot, row)` 契约

## 3. C# 生成器（`canonical_accessor.py`）

- [x] 3.1 每表 `Count/ByID/ByIndex`（有索引时含 `ByGroupKey`）
- [x] 3.2 enum → `(ItemRarity)WireReader.I8(_row, slot)`
- [x] 3.3 跨表 ref → 保留裸 id + 类型化 `{RefTable}Accessor.ByID(...)`（走 id→行缓存）
- [x] 3.4 vector\<int\> → `NArray<int>(VecBase(_row, slot), len)`；vector\<record\> → `NStructArray<T>`；vector\<string\> → `NStructArray<NString>`
- [x] 3.5 嵌套 record 子行对齐容器风格
- [x] 3.6 string 走 `NString`/`NStringCache`

## 4. Lua 生成器（`canonical_accessor.py`）

- [x] 4.1 `M.Count/M.ByID/M.ByIndex`（有索引含 `ByCode/ByGroupKey`）
- [x] 4.2 enum 类型化、跨表 ref 类型化（id→行缓存）
- [x] 4.3 vector 返回惰性表数组（基址捕获）

## 5. 导出管线

- [x] 5.1 `canonical_export.py` 把表映射传给 `build_accessor_model`（解析 ref）

## 6. 测试与产物

- [x] 6.1 更新 `tests/export/test_canonical_accessor.py` golden：指针式行句柄、容器接口、`ByID/Count/ByIndex`、ref 类型化、enum 类型化、`VecBase`
- [x] 6.2 `test-proj/ConfigAccessorBench` 用新 reader 复验正确性 + 性能（vector 大/小、标量、enum）
- [x] 6.3 重生成 `gd/output/generated/**`
- [x] 6.4 `pytest tests/export/` 全绿；`dotnet run -c Release -- Item 500000` 复验
- [x] 6.5 确认不做标量偏移缓存（design 记录）

## 7. 收尾

- [x] 7.1 `openspec validate align-config-accessor-api --strict` 通过
- [x] 7.2 决定 reader 运行时在仓库中的落位（独立项目 vs 并入 test-proj）
