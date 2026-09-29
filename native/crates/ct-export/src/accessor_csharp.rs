//! C# accessor 发射器（`ct/export/canonical_accessor.py` 的 C# 侧）。
//!
//! 行句柄三形态：slot（vtable 现走）/ offsets（按 vtable 记忆化偏移表）/
//! literal（定宽表级字面量偏移）。多语言字段读稀疏 i18n 表并回退主表原文。

use crate::accessor_model::{
    csharp_scalar_type, record_accessor_fields, referenced_records, AccessorField, AccessorModel,
};

const GUARD_COND: &str = "CONFIG_DEBUG || UNITY_EDITOR || DEVELOPMENT_BUILD";
const NS: &str = "GameFramework.ConfigGen";
const NS_PAD: usize = 4;

const ROW_MODE_SLOT: &str = "slot";
const ROW_MODE_OFFSETS: &str = "offsets";
const ROW_MODE_LITERAL: &str = "literal";

/// vtable 槽位 = 4 + 2*字段序。
fn vtable_slot(field: &AccessorField) -> usize {
    4 + 2 * field.slot
}

/// C# 标量读取器（槽位版）。
fn scalar_reader(type_text: &str) -> Option<&'static str> {
    Some(match type_text {
        "int8" => "WireReader.S8",
        "uint8" => "WireReader.U8",
        "int16" => "WireReader.I16",
        "uint16" => "WireReader.U16",
        "int32" => "WireReader.I32",
        "uint32" => "WireReader.U32",
        "int64" => "WireReader.I64",
        "uint64" => "WireReader.U64",
        "float" => "WireReader.F32",
        "double" => "WireReader.F64",
        "bool" => "WireReader.Bool",
        "string" => "WireReader.Str",
        _ => return None,
    })
}

/// C# 标量读取器（偏移版）。
fn at_reader(type_text: &str) -> Option<&'static str> {
    Some(match type_text {
        "int8" => "WireReader.S8At",
        "uint8" => "WireReader.U8At",
        "int16" => "WireReader.I16At",
        "uint16" => "WireReader.U16At",
        "int32" => "WireReader.I32At",
        "uint32" => "WireReader.U32At",
        "int64" => "WireReader.I64At",
        "uint64" => "WireReader.U64At",
        "float" => "WireReader.F32At",
        "double" => "WireReader.F64At",
        "bool" => "WireReader.BoolAt",
        "string" => "WireReader.StrAt",
        _ => return None,
    })
}

fn csharp_type(field: &AccessorField) -> String {
    match field.kind {
        "string" => "string".to_string(),
        "scalar" => csharp_scalar_type(&field.type_text)
            .unwrap_or("int")
            .to_string(),
        // enum 的 wire 是 byte，C# 侧暴露为具名枚举（cast 由调用点加）
        _ => "int".to_string(),
    }
}

fn string_cache_name(field_name: &str) -> String {
    format!("{field_name}Cache")
}

fn i18n_cache_name(field_name: &str) -> String {
    format!("{field_name}I18nCache")
}

fn i18n_reader_name(field_name: &str) -> String {
    format!("I18n{field_name}")
}

fn private_cache_field(name: &str) -> String {
    let mut chars = name.chars();
    let first = chars.next().unwrap().to_lowercase();
    format!("_{first}{}", chars.collect::<String>())
}

fn ctor_lines(type_name: &str, mode: &str) -> Vec<String> {
    match mode {
        ROW_MODE_OFFSETS => vec![
            format!("internal {type_name}(IntPtr row, int[] offsets, int version, int rowIndex)"),
            "{".into(),
            "    _row = row;".into(),
            "    _off = offsets;".into(),
            "    _version = version;".into(),
            "    _index = rowIndex;".into(),
            "}".into(),
        ],
        ROW_MODE_LITERAL => vec![
            format!("internal {type_name}(IntPtr row, int version, int rowIndex)"),
            "{".into(),
            "    _row = row;".into(),
            "    _version = version;".into(),
            "    _index = rowIndex;".into(),
            "}".into(),
        ],
        _ => vec![
            format!("internal {type_name}(IntPtr row, int version)"),
            "{".into(),
            "    _row = row;".into(),
            "    _version = version;".into(),
            "}".into(),
        ],
    }
}

/// 一个带开发期世代守卫的属性（永远是块体）。
fn member_lines(type_text: &str, name: &str, expr: &str, indent: usize) -> Vec<String> {
    let pad = " ".repeat(indent);
    vec![
        format!("{pad}public {type_text} {name}"),
        format!("{pad}{{"),
        format!("{pad}    get"),
        format!("{pad}    {{"),
        format!("{pad}        #if {GUARD_COND}"),
        format!("{pad}        TableVersion.Check(_version);"),
        format!("{pad}        #endif"),
        format!("{pad}        return {expr};"),
        format!("{pad}    }}"),
        format!("{pad}}}"),
    ]
}

fn indent_lines(lines: Vec<String>, width: usize) -> Vec<String> {
    let pad = " ".repeat(width);
    lines.into_iter().map(|l| format!("{pad}{l}")).collect()
}

fn literal_offset(
    field: &AccessorField,
    mode: &str,
    literal_offsets: Option<&std::collections::HashMap<u32, u32>>,
    slot: usize,
) -> String {
    if mode == ROW_MODE_LITERAL {
        let offsets = literal_offsets.expect("定宽表必须携带字面量偏移");
        return offsets
            .get(&(slot as u32))
            .unwrap_or_else(|| panic!("字段 {}（slot {slot}）缺字面量偏移", field.name))
            .to_string();
    }
    format!("_off[{slot}]")
}

/// 发射一个字段的访问器。
fn emit_field(
    field: &AccessorField,
    qualified_row: &str,
    indent: usize,
    mode: &str,
    literal_offsets: Option<&std::collections::HashMap<u32, u32>>,
    i18n_read: Option<&str>,
) -> Vec<String> {
    let slot = vtable_slot(field);

    // 多语言字段：i18n 表优先，回退主表原文（带行下标缓存）
    if let (true, Some(i18n_read)) = (field.i18n, i18n_read) {
        let pad = " ".repeat(indent);
        let off = literal_offset(field, mode, literal_offsets, slot);
        let cache = string_cache_name(&field.name);
        return vec![
            format!("{pad}public string {}", field.name),
            format!("{pad}{{"),
            format!("{pad}    get"),
            format!("{pad}    {{"),
            format!("{pad}        #if {GUARD_COND}"),
            format!("{pad}        TableVersion.Check(_version);"),
            format!("{pad}        #endif"),
            format!("{pad}        string v = {qualified_row}{i18n_read}(_index);"),
            format!("{pad}        if (v != null)"),
            format!("{pad}        {{"),
            format!("{pad}            return v;"),
            format!("{pad}        }}"),
            format!("{pad}        string[] c = {qualified_row}{cache};"),
            format!("{pad}        string s = c[_index];"),
            format!("{pad}        if (s != null)"),
            format!("{pad}        {{"),
            format!("{pad}            return s;"),
            format!("{pad}        }}"),
            format!(
                "{pad}        s = NStringCache.Decode((byte*)WireReader.IndirectAt(_row, {off}));"
            ),
            format!("{pad}        c[_index] = s;"),
            format!("{pad}        return s;"),
            format!("{pad}    }}"),
            format!("{pad}}}"),
        ];
    }

    if mode == ROW_MODE_OFFSETS || mode == ROW_MODE_LITERAL {
        let off = literal_offset(field, mode, literal_offsets, slot);
        match field.kind {
            "vector" => {
                let container =
                    if field.element_kind == Some("record") && field.record_name().is_some() {
                        format!(
                            "NStructArray<{}{}>",
                            qualified_row,
                            field.record_name().unwrap()
                        )
                    } else {
                        field
                            .container_text()
                            .unwrap_or_else(|| "NArray<int>".to_string())
                    };
                return member_lines(
                    &container,
                    &field.name,
                    &format!(
                        "new {container}((byte*)WireReader.IndirectAt(_row, {off}), _version)"
                    ),
                    indent,
                );
            }
            "record" => {
                let rn = field.record_name().unwrap();
                return member_lines(
                    &format!("{qualified_row}{rn}"),
                    &field.name,
                    &format!(
                        "new {qualified_row}{rn}((IntPtr)WireReader.IndirectAt(_row, {off}), _version)"
                    ),
                    indent,
                );
            }
            "string" => {
                let cache = string_cache_name(&field.name);
                let pad = " ".repeat(indent);
                return vec![
                    format!("{pad}public string {}", field.name),
                    format!("{pad}{{"),
                    format!("{pad}    get"),
                    format!("{pad}    {{"),
                    format!("{pad}        #if {GUARD_COND}"),
                    format!("{pad}        TableVersion.Check(_version);"),
                    format!("{pad}        #endif"),
                    format!("{pad}        string[] c = {qualified_row}{cache};"),
                    format!("{pad}        string s = c[_index];"),
                    format!("{pad}        if (s != null)"),
                    format!("{pad}        {{"),
                    format!("{pad}            return s;"),
                    format!("{pad}        }}"),
                    format!(
                        "{pad}        s = NStringCache.Decode((byte*)WireReader.IndirectAt(_row, {off}));"
                    ),
                    format!("{pad}        c[_index] = s;"),
                    format!("{pad}        return s;"),
                    format!("{pad}    }}"),
                    format!("{pad}}}"),
                ];
            }
            "enum" => {
                return member_lines(
                    &field.type_text,
                    &field.name,
                    &format!("({})WireReader.I8At(_row, {off})", field.type_text),
                    indent,
                );
            }
            _ => {
                let reader = at_reader(&field.type_text).expect("未知标量");
                return member_lines(
                    &csharp_type(field),
                    &field.name,
                    &format!("{reader}(_row, {off})"),
                    indent,
                );
            }
        }
    }

    // slot 模式（嵌套 record 子行）
    match field.kind {
        "vector" => {
            let container = if field.element_kind == Some("record") && field.record_name().is_some()
            {
                format!(
                    "NStructArray<{}{}>",
                    qualified_row,
                    field.record_name().unwrap()
                )
            } else {
                field
                    .container_text()
                    .unwrap_or_else(|| "NArray<int>".to_string())
            };
            member_lines(
                &container,
                &field.name,
                &format!("new {container}(_row, {slot}, _version)"),
                indent,
            )
        }
        "record" => {
            let rn = field.record_name().unwrap();
            member_lines(
                &format!("{qualified_row}{rn}"),
                &field.name,
                &format!("new {qualified_row}{rn}(WireReader.Indirect(_row, {slot}), _version)"),
                indent,
            )
        }
        "string" => member_lines(
            "string",
            &field.name,
            &format!("new NString((byte*)WireReader.Indirect(_row, {slot}), _version)"),
            indent,
        ),
        "enum" => {
            let reader = scalar_reader(&field.type_text).unwrap_or("WireReader.I8");
            member_lines(
                &field.type_text,
                &field.name,
                &format!("({}){}(_row, {slot})", field.type_text, reader),
                indent,
            )
        }
        _ => {
            let reader = scalar_reader(&field.type_text).expect("未知标量");
            let mut lines = member_lines(
                &csharp_type(field),
                &field.name,
                &format!("{reader}(_row, {slot})"),
                indent,
            );
            if let Some(ref_table) = &field.ref_table {
                let pad = " ".repeat(indent);
                lines.push(format!(
                    "{pad}public {ref_table}? {ref_table} => {ref_table}Accessor.ByID({});",
                    field.name
                ));
            }
            lines
        }
    }
}

/// 表级 string 字段的 per-field 行下标缓存（按主表世代整体重建）。
fn emit_string_caches(model: &AccessorModel) -> Vec<String> {
    let names: Vec<String> = model
        .client_fields
        .iter()
        .filter(|f| f.kind == "string")
        .map(|f| string_cache_name(&f.name))
        .collect();
    if names.is_empty() {
        return vec![];
    }
    let epoch = "TableVersion.Current";
    let mut lines: Vec<String> = Vec::new();
    lines
        .push("    // ---- per-field 字符串缓存（行下标索引，整套 bin 换代时整体重建）----".into());
    for n in &names {
        lines.push(format!(
            "    private static string[] {};",
            private_cache_field(n)
        ));
    }
    lines.push("    private static int _strCacheVersion = -1;".into());
    lines.push("".into());
    lines.push("    [MethodImpl(MethodImplOptions.NoInlining)]".into());
    lines.push("    private static void ResetStringCaches()".into());
    lines.push("    {".into());
    lines.push("        int n = Table.Count;".into());
    for n in &names {
        lines.push(format!(
            "        {} = new string[n];",
            private_cache_field(n)
        ));
    }
    lines.push(format!("        _strCacheVersion = {epoch};"));
    lines.push("    }".into());
    for n in &names {
        let private = private_cache_field(n);
        lines.push("".into());
        lines.push(format!("    internal static string[] {n}"));
        lines.push("    {".into());
        lines.push("        [MethodImpl(MethodImplOptions.AggressiveInlining)]".into());
        lines.push("        get".into());
        lines.push("        {".into());
        lines.push(format!("            string[] c = {private};"));
        lines.push(format!(
            "            if (c != null && _strCacheVersion == {epoch})"
        ));
        lines.push("            {".into());
        lines.push("                return c;".into());
        lines.push("            }".into());
        lines.push("            ResetStringCaches();".into());
        lines.push(format!("            return {private};"));
        lines.push("        }".into());
        lines.push("    }".into());
    }
    lines
}

/// 稀疏 i18n 表里第 i18n_index 个多语言字段的读取表达式（`p` 是 i18n 行指针）。
fn i18n_read_expr(model: &AccessorModel, i18n_index: usize) -> String {
    let slot = 4 + 2 * (1 + i18n_index);
    match &model.i18n_uniform_offsets {
        None => format!("WireReader.Indirect(p, {slot})"),
        Some(offsets) => format!(
            "WireReader.IndirectAt(p, {})",
            offsets
                .get(&(slot as u32))
                .unwrap_or_else(|| panic!("i18n 字段序 {i18n_index}（slot {slot}）缺字面量偏移"))
        ),
    }
}

/// 多语言支撑：i18n 表句柄 + 译文缓存 + 逐字段私有读取方法。
fn emit_i18n_support(model: &AccessorModel) -> Vec<String> {
    if model.i18n_fields.is_empty() || model.i18n_table.is_none() {
        return vec![];
    }
    let mut lines: Vec<String> = Vec::new();
    lines.push(
        "    // ---- 多语言字段：当前语言的稀疏 i18n 表（按行下标读，与主表同序）----".into(),
    );
    lines.push(
        "    // 该表只在加载了对应语言包时存在；缺席时读回 null，由字段 getter 回退主表原文。"
            .into(),
    );
    lines.push(format!(
        "    private const string I18nTableName = \"{}\";",
        model.i18n_table.as_deref().unwrap()
    ));
    lines.push("    private static ConfigTable _i18nTable;".into());
    lines.push("    private static int _i18nTableVersion = -1;".into());
    lines.push("".into());
    lines.push("    [MethodImpl(MethodImplOptions.NoInlining)]".into());
    lines.push("    private static void ResolveI18nTable()".into());
    lines.push("    {".into());
    lines.push("        _i18nTable = Runtime.TryTable(I18nTableName);".into());
    lines.push("        _i18nTableVersion = TableVersion.I18nCurrent;".into());
    lines.push("    }".into());
    lines.push("".into());
    lines.push("    internal static ConfigTable I18nTable".into());
    lines.push("    {".into());
    lines.push("        get".into());
    lines.push("        {".into());
    lines.push("            ConfigTable t = _i18nTable;".into());
    lines
        .push("            // ⚠️ 表**缺席**时也要认这个世代。只判 `t != null` 的话，主语言".into());
    lines.push(
        "            //    （＝默认发布形态，根本不加载 i18n 包）每读一个多语言字段都要重走".into(),
    );
    lines.push("            //    一遍 TryTable（字典查找 + 字符串哈希）。".into());
    lines.push("            if (_i18nTableVersion == TableVersion.I18nCurrent)".into());
    lines.push("            {".into());
    lines.push("                return t;".into());
    lines.push("            }".into());
    lines.push("            ResolveI18nTable();".into());
    lines.push("            return _i18nTable;".into());
    lines.push("        }".into());
    lines.push("    }".into());

    let fields = &model.i18n_fields;
    let names: Vec<String> = fields.iter().map(|f| i18n_cache_name(&f.name)).collect();
    lines.push("".into());
    lines.push("    // 译文缓存：按 **i18n 世代**整体重建（切语言即失效）".into());
    for n in &names {
        lines.push(format!(
            "    private static string[] {};",
            private_cache_field(n)
        ));
    }
    lines.push("    private static int _i18nStrCacheVersion = -1;".into());
    lines.push("".into());
    lines.push("    [MethodImpl(MethodImplOptions.NoInlining)]".into());
    lines.push("    private static void ResetI18nStringCaches()".into());
    lines.push("    {".into());
    lines.push("        ConfigTable t = I18nTable;".into());
    lines.push("        int n = t == null ? 0 : t.Count;".into());
    for n in &names {
        lines.push(format!(
            "        {} = new string[n];",
            private_cache_field(n)
        ));
    }
    lines.push("        _i18nStrCacheVersion = TableVersion.I18nCurrent;".into());
    lines.push("    }".into());
    for (index, field) in fields.iter().enumerate() {
        let name = &names[index];
        let private = private_cache_field(name);
        lines.push("".into());
        lines.push(format!("    private static string[] {name}"));
        lines.push("    {".into());
        lines.push("        [MethodImpl(MethodImplOptions.AggressiveInlining)]".into());
        lines.push("        get".into());
        lines.push("        {".into());
        lines.push(format!("            string[] c = {private};"));
        lines.push(
            "            if (c != null && _i18nStrCacheVersion == TableVersion.I18nCurrent)".into(),
        );
        lines.push("            {".into());
        lines.push("                return c;".into());
        lines.push("            }".into());
        lines.push("            ResetI18nStringCaches();".into());
        lines.push(format!("            return {private};"));
        lines.push("        }".into());
        lines.push("    }".into());
        lines.push("".into());
        lines.push(format!(
            "    /// <summary>{}：当前语言译文；表/行缺失或该字段无译文时返回 null。</summary>",
            field.name
        ));
        lines.push(format!(
            "    internal static unsafe string {}(int index)",
            i18n_reader_name(&field.name)
        ));
        lines.push("    {".into());
        lines.push("        ConfigTable t = I18nTable;".into());
        lines.push("        if (t == null)".into());
        lines.push("        {".into());
        lines.push("            return null;".into());
        lines.push("        }".into());
        lines.push(format!("        string[] c = {name};"));
        lines.push("        if (index < 0 || index >= c.Length)".into());
        lines.push("        {".into());
        lines.push("            return null;".into());
        lines.push("        }".into());
        lines.push("        IntPtr p = t.RowAt(index);".into());
        lines.push("        if (p == IntPtr.Zero)".into());
        lines.push("        {".into());
        lines.push("            return null;".into());
        lines.push("        }".into());
        lines.push("        string s = c[index];".into());
        lines.push("        if (s != null)".into());
        lines.push("        {".into());
        lines.push("            return s;".into());
        lines.push("        }".into());
        lines.push(format!(
            "        s = NStringCache.Decode((byte*){});",
            i18n_read_expr(model, index)
        ));
        lines.push("        c[index] = s;".into());
        lines.push("        return s;".into());
        lines.push("    }".into());
    }
    lines
}

/// Count/ByID/ByIndex（+ByCodeName）。
fn emit_query_api(model: &AccessorModel) -> Vec<String> {
    let table = &model.table.table;
    let max_slot = 4 + 2 * model.client_fields.len();
    let literal = model.is_uniform();
    // ⚠️ 每个查询 API 的行下标变量名不同：ByID → idx、ByIndex → i、ByCodeName → row
    let row_args = |var: &str| -> (String, String) {
        (
            format!("p, t.OffsetsFor(p, MaxSlot), t.Version, {var}"),
            format!("p, t.Version, {var}"),
        )
    };
    let (offsets_by, literal_by) = row_args("idx");
    let (offsets_i, literal_i) = row_args("i");
    let (offsets_row, literal_row) = row_args("row");

    let mut lines: Vec<String> = Vec::new();
    lines.push(format!("    private const string TableName = \"{table}\";"));
    if !literal {
        lines.push(format!("    private const int MaxSlot = {max_slot};"));
    }
    lines.push("    private static ConfigTable _table;".into());
    lines.push("    private static int _tableVersion = -1;".into());
    lines.push("".into());
    lines.push(
        "    /// <summary>解析并缓存表句柄；整套 bin 换代后 Runtime 会重建表对象。</summary>"
            .into(),
    );
    lines.push("    [MethodImpl(MethodImplOptions.NoInlining)]".into());
    lines.push("    private static void Resolve()".into());
    lines.push("    {".into());
    lines.push("        _table = Runtime.Table(TableName);".into());
    lines.push("        _tableVersion = TableVersion.Current;".into());
    lines.push("    }".into());
    lines.push("".into());
    lines.push("    internal static ConfigTable Table".into());
    lines.push("    {".into());
    lines.push("        get".into());
    lines.push("        {".into());
    lines.push("            ConfigTable t = _table;".into());
    lines.push(
        "            // 世代守卫：整套 bin 换代（LoadBundle/Clear）后必须重新取句柄，".into(),
    );
    lines.push("            // 否则会继续用已被 Dispose 的旧表缓冲（悬垂指针）。".into());
    lines.push("            if (t != null && _tableVersion == TableVersion.Current)".into());
    lines.push("            {".into());
    lines.push("                return t;".into());
    lines.push("            }".into());
    lines.push("            Resolve();".into());
    lines.push("            return _table;".into());
    lines.push("        }".into());
    lines.push("    }".into());
    lines.push("".into());
    lines.push("    /// <summary>行数。</summary>".into());
    lines.push("    public static int Count => Table.Count;".into());
    lines.push("".into());
    lines.push("    /// <summary>按主键查行；未找到返回 null。</summary>".into());
    lines.push(format!("    public static {table}? ByID(int id)"));
    lines.push("    {".into());
    lines.push("        ConfigTable t = Table;".into());
    lines.push("        int idx;".into());
    lines.push("        IntPtr p = t.ByID(id, out idx);".into());
    lines.push("        if (p == IntPtr.Zero)".into());
    lines.push("        {".into());
    lines.push("            return null;".into());
    lines.push("        }".into());
    lines.push("        else".into());
    lines.push("        {".into());
    lines.push(format!(
        "            return new {table}({});",
        if literal { &literal_by } else { &offsets_by }
    ));
    lines.push("        }".into());
    lines.push("    }".into());
    lines.push("".into());
    lines.push("    /// <summary>按 Excel 序行下标取行；越界返回 null。</summary>".into());
    lines.push(format!("    public static {table}? ByIndex(int i)"));
    lines.push("    {".into());
    lines.push("        ConfigTable t = Table;".into());
    lines.push("        IntPtr p = t.RowAt(i);".into());
    lines.push("        if (p == IntPtr.Zero)".into());
    lines.push("        {".into());
    lines.push("            return null;".into());
    lines.push("        }".into());
    lines.push("        else".into());
    lines.push("        {".into());
    lines.push(format!(
        "            return new {table}({});",
        if literal { &literal_i } else { &offsets_i }
    ));
    lines.push("        }".into());
    lines.push("    }".into());
    for index in &model.indexes {
        if index.kind == "codename" {
            lines.push("".into());
            lines.push("    /// <summary>Exact-string CodeName lookup; returns null when missing.</summary>".into());
            lines.push(format!(
                "    public static {table}? ByCodeName(string codeName)"
            ));
            lines.push("    {".into());
            lines.push("        ConfigTable t = Table;".into());
            lines.push(format!(
                "        int row = Runtime.ByCodeName(TableName, {}, codeName);",
                index.slot
            ));
            lines.push("        if (row < 0)".into());
            lines.push("        {".into());
            lines.push("            return null;".into());
            lines.push("        }".into());
            lines.push("        else".into());
            lines.push("        {".into());
            lines.push("            IntPtr p = t.RowAt(row);".into());
            lines.push(format!(
                "            return new {table}({});",
                if literal { &literal_row } else { &offsets_row }
            ));
            lines.push("        }".into());
            lines.push("    }".into());
        }
    }
    lines
}

fn wrap_namespace(body: &[String]) -> Vec<String> {
    let pad = " ".repeat(NS_PAD);
    let mut out = vec![format!("namespace {NS}"), "{".to_string()];
    for line in body {
        if line.is_empty() {
            out.push(String::new());
        } else {
            out.push(format!("{pad}{line}"));
        }
    }
    out.push("}".to_string());
    out
}

/// 枚举类型声明（值 = schema 顺序序号，第 0 项是默认值）。
pub fn generate_csharp_enums(
    enums: &std::collections::BTreeMap<String, ct_domain::schema::EnumResource>,
) -> String {
    let mut body: Vec<String> = vec![
        "// <auto-generated/> 枚举声明（wire 为 byte，值 = schema 中的顺序序号）".into(),
        "// 顺序即 wire 序号：第 0 项是默认值（导出时该槽位不写，读回 0）。不要重排。".into(),
        "".into(),
    ];
    for (name, enum_) in enums {
        body.push(format!("public enum {name} : byte"));
        body.push("{".into());
        for (index, item) in enum_.values.iter().enumerate() {
            let comment = if item.comment.is_empty() {
                String::new()
            } else {
                format!("   // {}", item.comment)
            };
            body.push(format!("    {} = {index},{comment}", item.name));
        }
        body.push("}".into());
        body.push("".into());
    }
    let text = wrap_namespace(&body).join("\n");
    format!("{}\n", text.trim_end_matches('\n'))
}

/// 生成完整 C# accessor。
pub fn generate_csharp_accessor(
    model: &AccessorModel,
    records: &std::collections::HashMap<String, ct_domain::schema::RecordResource>,
) -> String {
    let table = &model.table.table;
    let mut body: Vec<String> = Vec::new();
    body.push(format!("public static partial class {table}Accessor"));
    body.push("{".into());
    body.extend(emit_query_api(model));
    let string_caches = emit_string_caches(model);
    if !string_caches.is_empty() {
        body.push("".into());
        body.extend(string_caches);
    }
    let i18n_support = emit_i18n_support(model);
    if !i18n_support.is_empty() {
        body.push("".into());
        body.extend(i18n_support);
    }
    // record 结构体
    let mut record_lines = Vec::new();
    for record in referenced_records(model, records) {
        let fields = record_accessor_fields(&record, Some(records));
        record_lines.push(format!("    public unsafe readonly struct {}", record.name));
        record_lines.push("    {".into());
        record_lines.push("        private readonly IntPtr _row;".into());
        record_lines.push("        private readonly int _version;".into());
        record_lines.extend(indent_lines(ctor_lines(&record.name, ROW_MODE_SLOT), 8));
        for field in &fields {
            record_lines.extend(emit_field(field, "", 8, ROW_MODE_SLOT, None, None));
        }
        record_lines.push("    }".into());
        record_lines.push("".into());
    }
    if !record_lines.is_empty() {
        body.push("".into());
        body.extend(record_lines);
    }
    body.push("}".into());
    body.push("".into());
    let mode = if model.is_uniform() {
        ROW_MODE_LITERAL
    } else {
        ROW_MODE_OFFSETS
    };
    body.push(format!("public unsafe readonly struct {table}"));
    body.push("{".into());
    body.push("    private readonly IntPtr _row;".into());
    if mode == ROW_MODE_OFFSETS {
        body.push("    private readonly int[] _off;".into());
    }
    body.push("    private readonly int _version;".into());
    body.push("    private readonly int _index;".into());
    body.extend(indent_lines(ctor_lines(table, mode), 4));
    let qualified = format!("{table}Accessor.");
    for field in &model.client_fields {
        body.extend(emit_field(
            field,
            &qualified,
            4,
            mode,
            model.uniform_offsets.as_ref(),
            if field.i18n {
                Some(i18n_reader_name(&field.name))
            } else {
                None
            }
            .as_deref(),
        ));
    }
    body.push("}".into());

    let mut lines: Vec<String> = vec![
        "// <auto-generated/>".into(),
        format!("// Canonical C# accessor for {table}"),
        "using System;".into(),
        "using System.Collections.Generic;".into(),
        "using System.Runtime.CompilerServices;".into(),
        "".into(),
    ];
    lines.extend(wrap_namespace(&body));
    lines.join("\n") + "\n"
}
