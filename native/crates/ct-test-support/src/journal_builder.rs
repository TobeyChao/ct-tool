//! journal/锁夹具：各阶段中断、缺失备份。

use std::path::Path;
use std::time::{Duration, UNIX_EPOCH};

/// Frozen Python crash snapshots and Python recovery results. Loading these
/// fixtures never imports or launches Python and never derives expected output
/// from the native publisher being tested.
pub fn python_publication_cases() -> Vec<serde_json::Value> {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../../fixtures/journals/python-publication.json"
    ))
    .unwrap();
    assert_eq!(fixture["format"], "python-publication-fixtures/1");
    let cases = fixture["cases"].as_array().unwrap().clone();
    assert_eq!(cases.len(), 8);
    cases
}

pub fn install_python_publication(root: &Path, case: &serde_json::Value) {
    for (relative, file) in case["before"].as_object().unwrap() {
        let path = root.join(relative);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, file["text"].as_str().unwrap()).unwrap();
        let nanos: u64 = file["mtimeNs"].as_str().unwrap().parse().unwrap();
        std::fs::File::options()
            .write(true)
            .open(&path)
            .unwrap()
            .set_modified(UNIX_EPOCH + Duration::from_nanos(nanos))
            .unwrap();
    }
    fn expand(value: &mut serde_json::Value, root: &str) {
        match value {
            serde_json::Value::String(s) => *s = s.replace("${ROOT}", root),
            serde_json::Value::Array(items) => items.iter_mut().for_each(|v| expand(v, root)),
            serde_json::Value::Object(items) => items.values_mut().for_each(|v| expand(v, root)),
            _ => {}
        }
    }
    let mut journal = case["journal"].clone();
    expand(&mut journal, &root.to_string_lossy());
    std::fs::create_dir_all(root.join(".ct")).unwrap();
    std::fs::write(
        root.join(".ct/export-publication.json"),
        serde_json::to_vec_pretty(&journal).unwrap(),
    )
    .unwrap();
}

pub fn assert_python_publication_recovered(root: &Path, case: &serde_json::Value) {
    let after = case["after"].as_object().unwrap();
    for (relative, expected) in after {
        let path = root.join(relative);
        assert_eq!(
            std::fs::read_to_string(&path).unwrap(),
            expected["text"].as_str().unwrap(),
            "{}: {relative}",
            case["name"]
        );
        let modified = std::fs::metadata(&path)
            .unwrap()
            .modified()
            .unwrap()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
            .to_string();
        assert_eq!(
            modified,
            expected["mtimeNs"].as_str().unwrap(),
            "{}: {relative} mtime",
            case["name"]
        );
    }
    for relative in case["before"].as_object().unwrap().keys() {
        if !after.contains_key(relative) {
            assert!(
                !root.join(relative).exists(),
                "{}: stale {relative}",
                case["name"]
            );
        }
    }
    assert!(!root.join(".ct/export-publication.json").exists());
}
