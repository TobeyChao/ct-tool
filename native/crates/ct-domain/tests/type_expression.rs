//! 类型表达式文法对照（`ct/schema/type_expression.py`）。

use ct_domain::types::{TypeExpr, PRIMARY_KEY_TYPE};

#[test]
fn scalars_all_parse() {
    for name in [
        "int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64", "float",
        "double", "bool", "string",
    ] {
        let expr = TypeExpr::parse(name).unwrap();
        assert_eq!(expr, TypeExpr::Scalar(name.to_string()));
        assert_eq!(expr.to_text(), name);
    }
}

#[test]
fn named_bare_and_prefixed() {
    let bare = TypeExpr::parse("ItemRarity").unwrap();
    assert_eq!(bare.to_text(), "ItemRarity");

    let record = TypeExpr::parse("record:DropReward").unwrap();
    let TypeExpr::Named(named) = &record else {
        panic!()
    };
    assert!(named.resolved());
    assert_eq!(named.name(), "DropReward");

    // 裸名 resolve 绑定前缀
    let TypeExpr::Named(bare_ref) = &bare else {
        panic!()
    };
    assert!(!bare_ref.resolved());
    assert_eq!(
        bare_ref
            .resolve(ct_domain::types::NamedKind::Enum)
            .resource_id(),
        "enum:ItemRarity"
    );
}

#[test]
fn vector_grammar() {
    let expr = TypeExpr::parse("vector<int32>").unwrap();
    assert_eq!(expr.to_text(), "vector<int32>");
    // 空白容错
    assert_eq!(
        TypeExpr::parse("vector< DropReward >").unwrap().to_text(),
        "vector<DropReward>"
    );
}

#[test]
fn grammar_errors() {
    let cases = [
        ("", "类型表达式为空"),
        ("int32 x", "多余内容"),
        ("vector int32", "vector 后缺少"),
        ("vector<>", "元素类型不能为空"),
        ("vector<int32", "缺少配对"),
        ("vector<vector<int32>>", "vector<vector<T>>"),
        ("vector", "vector 后缺少"),
        ("vector<>x", "元素类型不能为空"),
    ];
    for (input, fragment) in cases {
        let err = TypeExpr::parse(input).unwrap_err();
        assert!(err.0.contains(fragment), "{input:?}: {err}");
    }
}

#[test]
fn named_validation() {
    for (input, fragment) in [
        ("int32x", "首字符必须大写"),
        ("_Item", "不能以 _ 开头或结尾"),
        ("Item_", "不能以 _ 开头或结尾"),
        ("record:int32", "保留类型名"),
        ("table:Item", "必须为 record:<Name> 或 enum:<Name>"),
        ("record:A:B", "必须为 record:<Name> 或 enum:<Name>"),
    ] {
        let err = TypeExpr::parse(input).unwrap_err();
        assert!(err.0.contains(fragment), "{input:?}: {err}");
    }
}

#[test]
fn primary_key_type_is_int32() {
    assert_eq!(PRIMARY_KEY_TYPE, "int32");
}
