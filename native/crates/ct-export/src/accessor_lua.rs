//! Lua accessor 发射器（`ct/export/canonical_accessor.py` 的 Lua 侧）。
//!
//! 原生 `gd` 模块绑定：槽位读（GD.I32 等）；定宽表用字面量偏移（GD.I32Off）。

use crate::accessor_model::{
    record_accessor_fields, referenced_records, AccessorField, AccessorModel,
};

const ARRAY_META: &str = "ArrayMeta";

/// 客户端字段序 → vtable 字节偏移（原生按字节偏移读）。
fn lua_slot(field: &AccessorField) -> usize {
    4 + 2 * field.slot
}

/// 标量读绑定名。
fn lua_reader(field: &AccessorField) -> Option<&'static str> {
    if field.kind == "string" {
        return Some("GD.Str");
    }
    if field.kind == "enum" {
        return Some("GD.I8"); // enum 的 wire 是 byte
    }
    match field.type_text.as_str() {
        "int8" => Some("GD.I8"),
        "uint8" => Some("GD.U8"),
        "int16" => Some("GD.I16"),
        "uint16" => Some("GD.U16"),
        "int32" => Some("GD.I32"),
        "uint32" => Some("GD.U32"),
        "int64" => Some("GD.I64"),
        "uint64" => Some("GD.U64"),
        "float" => Some("GD.F32"),
        "double" => Some("GD.F64"),
        "bool" => Some("GD.I8"), // 按字节读再与 0 比较
        "string" => Some("GD.Str"),
        _ => None,
    }
}

/// 字面量偏移读绑定名（GD.I32 → GD.I32Off）。
fn lua_off_reader(field: &AccessorField) -> Option<String> {
    lua_reader(field).map(|r| format!("{r}Off"))
}

fn lua_vector_tag(element_type: &str) -> Option<&'static str> {
    Some(match element_type {
        "int8" => "i8",
        "uint8" => "u8",
        "int16" => "i16",
        "uint16" => "u16",
        "int32" => "i32",
        "uint32" => "u32",
        "int64" => "i64",
        "uint64" => "u64",
        "float" => "f32",
        "double" => "f64",
        "bool" => "b",
        "string" => "s",
        _ => return None,
    })
}

fn lua_unsupported(field: &AccessorField, why: &str) -> String {
    format!(
        "error(\"[Config] Lua 不支持 {}（{}）：{}\")",
        field.name, field.type_text, why
    )
}

/// 标量/枚举读取表达式（**返回语句**：`return x` 或 `error(...)`）。
fn lua_scalar_expr(field: &AccessorField, off: Option<u32>) -> String {
    let arg = off
        .map(|o| o.to_string())
        .unwrap_or_else(|| lua_slot(field).to_string());
    let reader = if off.is_some() {
        lua_off_reader(field)
    } else {
        lua_reader(field).map(String::from)
    };
    let Some(reader) = reader else {
        return lua_unsupported(
            field,
            &format!("原生 gd 模块没有 {} 的读取绑定", field.type_text),
        );
    };
    // 判 bool 用 type_text：0 在 Lua 里是真值，必须返回 boolean
    if field.type_text == "bool" {
        return format!("return {reader}(s, {arg}) ~= 0");
    }
    format!("return {reader}(s, {arg})")
}

/// 多语言字段：优先 i18n 表，缺失回退主表原文。
fn lua_i18n_expr(field: &AccessorField, i18n_index: usize, off: Option<u32>) -> String {
    let main_arg = off
        .map(|o| o.to_string())
        .unwrap_or_else(|| lua_slot(field).to_string());
    let main_reader = if off.is_some() { "GD.StrOff" } else { "GD.Str" };
    let i18n_slot = 4 + 2 * (1 + i18n_index); // i18n 表：slot 4 = 主键
    format!(
        "local v = GD.I18nStr(i18n_table(), s, {i18n_slot}) return v ~= nil and v or {main_reader}(s, {main_arg})"
    )
}

/// 向量：惰性视图（原生按数据指针缓存 userdata）。
fn lua_vector_body(field: &AccessorField, off: Option<u32>) -> String {
    if field.element_kind == Some("record") {
        return lua_unsupported(field, "原生 gd 模块没有 record 元素的 tag");
    }
    let tag = if field.element_kind == Some("enum") {
        Some("i8")
    } else {
        lua_vector_tag(&field.element_type)
    };
    let Some(tag) = tag else {
        return lua_unsupported(
            field,
            &format!("原生 gd 模块没有向量元素类型 {} 的 tag", field.element_type),
        );
    };
    if let Some(off) = off {
        return format!("return GD.ArrOff(s, {off}, \"{tag}\", {ARRAY_META})");
    }
    format!(
        "return GD.Arr(s, {}, \"{tag}\", {ARRAY_META})",
        lua_slot(field)
    )
}

/// 嵌套 record：原生按数据指针缓存 userdata 并挂 meta。
fn lua_record_expr(field: &AccessorField, off: Option<u32>) -> String {
    let meta = format!("{}Meta", field.record_name().unwrap_or("?"));
    if let Some(off) = off {
        return format!("return GD.StructOff(s, {off}, {meta})");
    }
    format!("return GD.Struct(s, {}, {meta})", lua_slot(field))
}

fn lua_field_body(
    field: &AccessorField,
    i18n_index: usize,
    delegate_i18n: bool,
    off: Option<u32>,
) -> String {
    if field.kind == "vector" {
        return lua_vector_body(field, off);
    }
    if field.kind == "record" {
        return lua_record_expr(field, off);
    }
    // 只有主表 accessor 委托 i18n 表（避免自我委托）
    if field.i18n && delegate_i18n {
        return lua_i18n_expr(field, i18n_index, off);
    }
    lua_scalar_expr(field, off)
}

fn lua_member_lines(
    field: &AccessorField,
    indent: &str,
    i18n_index: Option<usize>,
    delegate_i18n: bool,
    off: Option<u32>,
) -> Vec<String> {
    let mut lines = Vec::new();
    let body = lua_field_body(field, i18n_index.unwrap_or(0), delegate_i18n, off);
    lines.push(format!("{indent}{} = function(s) {body} end,", field.name));
    if let Some(ref_table) = &field.ref_table {
        // 类型化跨表 ref：裸 id 已在上一行给出
        let arg = off
            .map(|o| o.to_string())
            .unwrap_or_else(|| lua_slot(field).to_string());
        let reader = if off.is_some() {
            lua_off_reader(field)
        } else {
            lua_reader(field).map(String::from)
        };
        if let Some(reader) = reader {
            if field.kind != "string" && field.type_text != "bool" {
                lines.push(format!(
                    "{indent}{ref_table} = function(s) return Config.{ref_table}.ByID({reader}(s, {arg})) end,"
                ));
            }
        }
    }
    lines
}

/// 每个被引用 record 一份元表。
fn emit_record_metas(
    model: &AccessorModel,
    records: &std::collections::HashMap<String, ct_domain::schema::RecordResource>,
) -> Vec<String> {
    let mut lines = Vec::new();
    for record in referenced_records(model, records) {
        let fields = record_accessor_fields(&record, Some(records));
        lines.push(format!("local {}Meta = make_meta({{", record.name));
        for field in &fields {
            lines.extend(lua_member_lines(field, "    ", None, false, None));
        }
        lines.push("})".to_string());
        lines.push(String::new());
    }
    lines
}

/// 枚举常量表（与 C# 同一套序号）。
pub fn generate_lua_enums(
    enums: &std::collections::BTreeMap<String, ct_domain::schema::EnumResource>,
) -> String {
    let mut lines = vec![
        "-- <auto-generated/> 枚举常量表（值 = schema 中的顺序序号，不要重排）".to_string(),
        "local Enums = {}".to_string(),
        String::new(),
    ];
    for (name, enum_) in enums {
        lines.push(format!("Enums.{name} = {{"));
        for (index, item) in enum_.values.iter().enumerate() {
            let comment = if item.comment.is_empty() {
                String::new()
            } else {
                format!("  -- {}", item.comment)
            };
            lines.push(format!("    {} = {index},{comment}", item.name));
        }
        lines.push("}".to_string());
    }
    lines.push(String::new());
    lines.push("return Enums".to_string());
    lines.join("\n") + "\n"
}

/// 生成完整 Lua accessor。
pub fn generate_lua_accessor(
    model: &AccessorModel,
    records: &std::collections::HashMap<String, ct_domain::schema::RecordResource>,
) -> String {
    let table = &model.table.table;
    let delegate = model.i18n_table.is_some() && model.has_i18n();

    let mut lines: Vec<String> = Vec::new();
    lines.push(format!(
        "-- <auto-generated/> canonical Lua accessor for {table}"
    ));
    lines.push("local GD = require(\"gd\")".to_string());
    lines.push(String::new());
    lines.push("-- 表句柄：模块加载时取一次（原生固定槽位引用，跨加载有效）".to_string());
    lines.push(format!("local _tbl = GD.FindTable(\"{table}\")"));
    if delegate {
        lines.push("-- 稀疏 i18n 表句柄：按 i18n 世代**记忆**。".to_string());
        lines.push(
            "-- 用 GD.I18nGen() 而不是「nil 才重试」：切回主语言后句柄会重新变成".to_string(),
        );
        lines.push(
            "-- 不可解析，只按 nil 重试会把失效句柄一直用下去（原生 check_tbl 直接报错）。"
                .to_string(),
        );
        lines.push("local _i18nTbl, _i18nGen = nil, nil".to_string());
        lines.push("local function i18n_table()".to_string());
        lines.push("    local g = GD.I18nGen()".to_string());
        lines.push("    if g ~= _i18nGen then".to_string());
        lines.push(format!(
            "        _i18nTbl = GD.FindTableI18n(\"{}\")",
            model.i18n_table.as_deref().unwrap()
        ));
        lines.push("        _i18nGen = g".to_string());
        lines.push("    end".to_string());
        lines.push("    return _i18nTbl".to_string());
        lines.push("end".to_string());
    }
    lines.push(String::new());
    lines
        .push("-- 元表工厂：字段名 → 读取函数（分发表一次性构建，所有行共享同一元表）".to_string());
    lines.push("local function make_meta(readers)".to_string());
    lines.push("    return { __index = function(self, key)".to_string());
    lines.push("        local fn = readers[key]".to_string());
    lines.push("        if fn then return fn(self) end".to_string());
    lines.push("    end }".to_string());
    lines.push("end".to_string());
    lines.push(String::new());
    lines.push("-- 数组视图元表（**惰性视图**：不建 Lua 表、稳态零分配）".to_string());
    lines.push(format!("local {ARRAY_META} = {{"));
    lines.push("    __len   = function(v) return GD.ArrLen(v) end,".to_string());
    lines.push("    __index = function(v, i) return GD.ArrAt(v, i) end,".to_string());
    lines.push("    __pairs = ipairs,   -- 契约测试要求 for _, v in pairs(tags) 可用".to_string());
    lines.push("}".to_string());
    lines.push(String::new());

    lines.extend(emit_record_metas(model, records));

    let i18n_names: Vec<&str> = model
        .client_fields
        .iter()
        .filter(|f| f.i18n)
        .map(|f| f.name.as_str())
        .collect();
    let offsets = if model.is_uniform() {
        model.uniform_offsets.as_ref()
    } else {
        None
    };
    if offsets.is_some() {
        lines
            .push("-- ⚠️ 本表是**定宽布局**：下面全是字面量偏移读（无 vtable 走查）。".to_string());
        lines.push(
            "--    偏移由导出期 `probe_row_layout` 算出，是表级常量；改变 schema 必须重新导出。"
                .to_string(),
        );
    }
    lines.push("-- 行访问器元表（self = 行 userdata）".to_string());
    lines.push("local RowMeta = make_meta({".to_string());
    for field in &model.client_fields {
        let index = if field.i18n && i18n_names.contains(&field.name.as_str()) {
            i18n_names.iter().position(|n| *n == field.name)
        } else {
            None
        };
        let slot = lua_slot(field) as u32;
        let off = offsets.and_then(|o| o.get(&slot).copied());
        lines.extend(lua_member_lines(field, "    ", index, delegate, off));
    }
    lines.push("})".to_string());
    lines.push(String::new());
    lines.push("-- 公开 API（纯函数，无状态）".to_string());
    lines.push("local M = {}".to_string());
    lines.push("function M.Count() return GD.Count(_tbl) end".to_string());
    lines.push("function M.ByID(id) return GD.ByID(_tbl, id, RowMeta) end".to_string());
    lines.push("function M.ByIndex(i) return GD.ByIndex(_tbl, i, RowMeta) end".to_string());
    for index in &model.indexes {
        if index.kind == "codename" {
            lines.push("-- 原生 codeName 查询：FNV-1a 64 桶表 + 按字段精确字符串确认".to_string());
            lines.push(format!(
                "function M.ByCodeName(codeName) return GD.ByCodeName(_tbl, {}, codeName, RowMeta) end",
                index.slot
            ));
        }
    }
    lines.push("return M".to_string());
    lines.join("\n") + "\n"
}
