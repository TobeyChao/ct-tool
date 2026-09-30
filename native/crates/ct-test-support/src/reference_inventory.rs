//! Frozen main test inventory: always checked, never discovered from a retired ct/ tree.

use std::collections::BTreeMap;
use std::path::{Component, Path};

use anyhow::{bail, Context, Result};
use serde::Deserialize;
use sha2::{Digest, Sha256};

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ReferenceInventory {
    pub schema: String,
    pub origin: Origin,
    pub files: BTreeMap<String, ReferenceFile>,
    pub total_files: usize,
    pub total_test_functions: usize,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Origin {
    pub main_web_baseline: String,
    pub fingerprint_snapshot: String,
    pub fingerprint_sha256: String,
}

#[derive(Deserialize)]
pub struct ReferenceFile {
    pub sha256: String,
    pub functions: Vec<String>,
}

pub fn valid_sha256(hash: &str) -> bool {
    hash.len() == 64 && hash.bytes().all(|byte| byte.is_ascii_hexdigit())
}

pub fn read(root: &Path) -> Result<ReferenceInventory> {
    let base = root.join("native/docs/baseline");
    let path = base.join("reference-tests.json");
    let bytes = std::fs::read(&path).context("缺少冻结 main 测试清单")?;
    let expected = std::fs::read_to_string(base.join("reference-tests.sha256"))?;
    let actual = format!("{:x}", Sha256::digest(&bytes));
    if actual != expected.trim() {
        bail!("冻结 main 测试清单 SHA-256 不匹配");
    }
    let value: ReferenceInventory = serde_json::from_slice(&bytes)?;
    if value.schema != "ct-reference-tests/1"
        || value.origin.main_web_baseline != "8dc7b81"
        || value.total_files != 85
        || value.files.len() != 85
        || value.total_test_functions != 690
        || value
            .files
            .values()
            .map(|file| file.functions.len())
            .sum::<usize>()
            != 690
    {
        bail!("冻结 main 测试清单必须保留 85 个文件和 690 个函数");
    }
    for (name, file) in &value.files {
        if !name.starts_with("ct/tests/")
            || !name.ends_with(".py")
            || Path::new(name)
                .components()
                .any(|part| !matches!(part, Component::Normal(_)))
            || !valid_sha256(&file.sha256)
            || file.functions.iter().any(|name| {
                !name.starts_with("test_")
                    || !name
                        .chars()
                        .all(|ch| ch.is_ascii_alphanumeric() || ch == '_')
            })
        {
            bail!("冻结测试来源格式非法：{name}");
        }
    }
    let snapshot = Path::new(&value.origin.fingerprint_snapshot);
    if snapshot
        .components()
        .any(|part| !matches!(part, Component::Normal(_)))
    {
        bail!("历史源码指纹路径非法");
    }
    let source = std::fs::read(root.join(snapshot)).context("缺少历史源码指纹快照")?;
    if format!("{:x}", Sha256::digest(source)) != value.origin.fingerprint_sha256 {
        bail!("历史源码指纹快照 SHA-256 不匹配");
    }
    Ok(value)
}
