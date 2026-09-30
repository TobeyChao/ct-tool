//! Repackage frozen, independently authored OOXML inputs without using ct-excel.
//! Expected JSON stays immutable and is verified before any generated output is written.

use std::collections::BTreeMap;
use std::io::{Cursor, Write};
use std::path::{Component, Path};

use anyhow::{bail, Context, Result};
use serde::Deserialize;
use sha2::{Digest, Sha256};

const READER_FIXTURES: &[&str] = &[
    "active_sheet",
    "dates_1900",
    "dates_1904",
    "errors",
    "formula_cache",
    "rich_text",
];

#[derive(Deserialize)]
struct Manifest {
    schema: String,
    workbooks: BTreeMap<String, Workbook>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Workbook {
    expected_sha256: String,
    members: BTreeMap<String, String>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct CompatManifest {
    schema: String,
    groups: BTreeMap<String, CompatGroup>,
    source_references: Vec<SourceReference>,
}

#[derive(Deserialize)]
struct CompatGroup {
    files: BTreeMap<String, String>,
}

#[derive(Deserialize)]
struct SourceReference {
    snapshot: String,
    sha256: String,
}

fn safe_relative(path: &str) -> Result<&Path> {
    let path = Path::new(path);
    if path
        .components()
        .any(|part| !matches!(part, Component::Normal(_)))
    {
        bail!("冻结夹具清单路径非法");
    }
    Ok(path)
}

pub fn verify_compat(fixtures: &Path) -> Result<usize> {
    let manifest: CompatManifest =
        serde_json::from_slice(&std::fs::read(fixtures.join("compat-manifest.json"))?)?;
    let required = [
        "binary",
        "excel",
        "export_pipeline",
        "fingerprints",
        "schema_state",
        "template",
    ];
    if manifest.schema != "ct-compat-oracles/1"
        || manifest
            .groups
            .keys()
            .map(String::as_str)
            .collect::<Vec<_>>()
            != required
        || manifest.source_references.len() != 7
    {
        bail!("兼容夹具清单缺少必要领域或七份历史来源");
    }
    let mut count = 0;
    for (group, spec) in manifest.groups {
        let root = fixtures.join(group);
        let mut files = BTreeMap::new();
        collect(&root, &root, &mut files)?;
        files.retain(|name, _| {
            !matches!(
                Path::new(name).extension().and_then(|ext| ext.to_str()),
                Some("py" | "md")
            )
        });
        if files.keys().collect::<Vec<_>>() != spec.files.keys().collect::<Vec<_>>() {
            bail!("冻结兼容夹具文件集合改变：{}", root.display());
        }
        for (name, hash) in spec.files {
            let path = root.join(safe_relative(&name)?);
            check_hash(&files[&name], &hash, &path)?;
            count += 1;
        }
    }
    let native = fixtures.parent().context("夹具目录缺少 native 父目录")?;
    for source in manifest.source_references {
        let path = native.join(safe_relative(&source.snapshot)?);
        check_hash(&std::fs::read(&path)?, &source.sha256, &path)?;
    }
    Ok(count)
}

fn collect(root: &Path, base: &Path, files: &mut BTreeMap<String, Vec<u8>>) -> Result<()> {
    for entry in std::fs::read_dir(root)? {
        let entry = entry?;
        let kind = entry.file_type()?;
        if kind.is_symlink() {
            bail!("夹具源不可包含符号链接");
        }
        if kind.is_dir() {
            collect(&entry.path(), base, files)?;
        } else if kind.is_file() {
            let path = entry.path();
            let relative = path
                .strip_prefix(base)?
                .to_string_lossy()
                .replace('\\', "/");
            files.insert(relative, std::fs::read(path)?);
        } else {
            bail!("夹具源包含非普通文件");
        }
    }
    Ok(())
}

fn check_hash(bytes: &[u8], expected: &str, path: &Path) -> Result<()> {
    let actual = format!("{:x}", Sha256::digest(bytes));
    if actual != expected {
        bail!("夹具源 SHA-256 不匹配：{}", path.display());
    }
    Ok(())
}

pub fn regenerate_excel(fixtures: &Path, out: &Path) -> Result<Vec<String>> {
    let manifest: Manifest =
        serde_json::from_slice(&std::fs::read(fixtures.join("source/manifest.json"))?)?;
    if manifest.schema != "ct-excel-fixture-source/1"
        || manifest
            .workbooks
            .keys()
            .map(String::as_str)
            .collect::<Vec<_>>()
            != READER_FIXTURES
    {
        bail!("Excel 夹具源清单格式或六个必要场景不完整");
    }
    let mut outputs = BTreeMap::new();
    for (stem, workbook) in &manifest.workbooks {
        let source = fixtures.join("source").join(stem);
        let expected = fixtures.join("expected").join(format!("{stem}.json"));
        check_hash(
            &std::fs::read(&expected)?,
            &workbook.expected_sha256,
            &expected,
        )?;
        let mut files = BTreeMap::new();
        collect(&source, &source, &mut files)?;
        if files.keys().collect::<Vec<_>>() != workbook.members.keys().collect::<Vec<_>>() {
            bail!("Excel 夹具 {stem} 的 OOXML 部件集合改变");
        }
        let mut writer = zip::ZipWriter::new(Cursor::new(Vec::new()));
        let options = zip::write::SimpleFileOptions::default()
            .compression_method(zip::CompressionMethod::Deflated);
        for (name, bytes) in files {
            if Path::new(&name)
                .components()
                .any(|part| !matches!(part, Component::Normal(_)))
            {
                bail!("OOXML 部件路径非法");
            }
            check_hash(&bytes, &workbook.members[&name], &source.join(&name))?;
            writer.start_file(name, options)?;
            writer.write_all(&bytes)?;
        }
        outputs.insert(format!("{stem}.xlsx"), writer.finish()?.into_inner());
    }
    std::fs::create_dir_all(out)?;
    if out.canonicalize()?.starts_with(fixtures.canonicalize()?) {
        bail!("再生输出必须位于冻结夹具目录之外");
    }
    let names = outputs.keys().cloned().collect();
    for (name, bytes) in outputs {
        std::fs::write(out.join(name), bytes).context("写入再生工作簿失败")?;
    }
    Ok(names)
}
