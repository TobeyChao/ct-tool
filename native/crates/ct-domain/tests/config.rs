//! 配置加载对照（`ct/config.py`）。

use std::path::Path;

use ct_domain::config::GlobalConfig;

#[test]
fn custom_dirs_resolve_against_root() {
    let config = GlobalConfig::from_yaml(
        "primary_lang: zh\nschemas_dir: my/schemas\noutput_dir: dist\n",
        Path::new("/ws"),
    )
    .unwrap();
    assert_eq!(config.resolve("schemas_dir"), Path::new("/ws/my/schemas"));
    assert_eq!(config.resolve("output_dir"), Path::new("/ws/dist"));
    // 未配置目录取默认
    assert_eq!(config.resolve("excel_dir"), Path::new("/ws/excel"));
    assert_eq!(config.all_langs(), vec!["zh".to_string()]);
}

#[test]
fn rejects_empty_primary_lang_and_unknown_keys() {
    let err = GlobalConfig::from_yaml("primary_lang: \"  \"\n", Path::new("/ws")).unwrap_err();
    assert!(err.contains("primary_lang"), "{err}");

    let err = GlobalConfig::from_yaml("primary_lang: zh\nnope: 1\n", Path::new("/ws")).unwrap_err();
    assert!(err.contains("nope"), "{err}");
}

#[test]
fn deploy_targets_expand() {
    let config = GlobalConfig::from_yaml(
        "primary_lang: zh\nsecondary_langs: [en, ja]\ndeploy:\n  enabled: true\n  unity_project: ../Game\n  targets:\n    - source: output/json\n      dest: Assets/Data\n  build_targets:\n    - source: output/binary\n      dest: Assets/Bin\n",
        Path::new("/ws"),
    )
    .unwrap();
    let normal = config.resolve_deploy_targets(false);
    assert_eq!(normal.len(), 1);
    let with_build = config.resolve_deploy_targets(true);
    assert_eq!(with_build.len(), 2);
    assert_eq!(
        with_build[1].1,
        Path::new("/ws").join("../Game").join("Assets/Bin")
    );
    assert_eq!(config.all_langs().len(), 3);

    // 未启用 → 空
    let off = GlobalConfig::from_yaml("primary_lang: zh\n", Path::new("/ws")).unwrap();
    assert!(off.resolve_deploy_targets(true).is_empty());
}
