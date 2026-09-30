//! Active independent-reader preparation: immutable main inputs, native outputs.
use std::collections::{BTreeMap, HashMap};
use std::path::{Component, Path};

use anyhow::{bail, Context, Result};
use ct_domain::schema::TableResource;
use ct_export::binary::{build_canonical_bundle, build_canonical_table_bytes, BinaryBuilder};
use ct_export::{accessor_csharp::generate_csharp_accessor, accessor_model::build_accessor_model};
use serde::Deserialize;
use sha2::{Digest, Sha256};

#[derive(Deserialize)]
struct Archive {
    schema: String,
    #[serde(rename = "sourceCommit")]
    source_commit: String,
    files: BTreeMap<String, String>,
}

pub fn generate(root: &Path, out: &Path) -> Result<()> {
    let archive_dir = root.join("native/fixtures/accessor_verify");
    let manifest = std::fs::read(archive_dir.join("independent-oracles.json"))?;
    let checksum = std::fs::read_to_string(archive_dir.join("independent-oracles.json.sha256"))?;
    if format!("{:x}", Sha256::digest(&manifest)) != checksum.trim() {
        bail!("independent reader manifest checksum mismatch");
    }
    let archive: Archive = serde_json::from_slice(&manifest)?;
    if archive.schema != "ct-independent-reader/1"
        || archive.source_commit != "8dc7b81"
        || archive.files.len() != 32
    {
        bail!("independent reader archive shape mismatch (expected 32 inputs/references)");
    }
    for (relative, expected) in &archive.files {
        let path = Path::new(relative);
        if path.is_absolute()
            || path
                .components()
                .any(|c| !matches!(c, Component::Normal(_)))
        {
            bail!("unsafe independent reader path: {relative}");
        }
        let bytes = std::fs::read(root.join(path))
            .with_context(|| format!("missing oracle: {relative}"))?;
        if format!("{:x}", Sha256::digest(&bytes)) != *expected {
            bail!("independent reader oracle checksum mismatch: {relative}");
        }
    }
    // Never allow a supplied output path to replace any part of the checked source tree.
    let source = root.canonicalize()?;
    std::fs::create_dir_all(out)?;
    let out = out.canonicalize()?;
    if out.starts_with(&source) && !out.starts_with(source.join("native/target")) {
        bail!("accessor fixture outputs must be temporary or under native/target");
    }
    let table: TableResource =
        serde_json::from_slice(&std::fs::read(archive_dir.join("scalars-schema.json"))?)?;
    table.validate()?;
    let reference = root.join("test-proj/ExportAccessorVerify");
    let row_bytes = std::fs::read(reference.join("fixtures/scalars.json"))?;
    let row: serde_json::Map<String, serde_json::Value> = serde_json::from_slice(&row_bytes)?;
    let records = HashMap::new();
    let enums = HashMap::new();
    let state = BinaryBuilder {
        records: &records,
        enums: &enums,
        uniform: table.uniform,
    };
    let binary = build_canonical_bundle(&HashMap::from([(
        table.table.clone(),
        build_canonical_table_bytes(&table, &[row], &state)?,
    )]));
    let model = build_accessor_model(&table, &table.indexes, Some(&records), None, None, None);
    let accessor = generate_csharp_accessor(&model, &records);
    if binary != std::fs::read(reference.join("fixtures/scalars.bin"))? {
        bail!("native scalar Binary differs from independent main golden");
    }
    if accessor.as_bytes() != std::fs::read(reference.join("generated/ScalarsAccessor.cs"))? {
        bail!("native scalar C# differs from independent main golden");
    }
    std::fs::write(out.join("scalars.bin"), binary)?;
    std::fs::write(out.join("ScalarsAccessor.cs"), accessor)?;
    // Copy original JSON bytes, retaining signed/unsigned 64-bit boundaries without JS parsing.
    std::fs::write(out.join("scalars.json"), row_bytes)?;
    println!(
        "32 independent inputs/references verified; native Scalars Binary/C# match main golden"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn copy_archive(root: &Path) {
        let source = crate::repo_root();
        let relative = "native/fixtures/accessor_verify/independent-oracles.json";
        let bytes = std::fs::read(source.join(relative)).unwrap();
        let archive: Archive = serde_json::from_slice(&bytes).unwrap();
        for path in archive
            .files
            .keys()
            .chain([relative.to_string(), format!("{relative}.sha256")].iter())
        {
            let dest = root.join(path);
            std::fs::create_dir_all(dest.parent().unwrap()).unwrap();
            std::fs::copy(source.join(path), dest).unwrap();
        }
    }

    #[test]
    fn independent_scalars_regenerate_without_legacy_ct_and_match_main_bytes() {
        let root = tempfile::tempdir().unwrap();
        copy_archive(root.path());
        assert!(!root.path().join("ct").exists());
        let output = tempfile::tempdir().unwrap();
        for name in ["first", "second"] {
            generate(root.path(), &output.path().join(name)).unwrap();
        }
        for name in ["scalars.bin", "scalars.json", "ScalarsAccessor.cs"] {
            assert_eq!(
                std::fs::read(output.path().join("first").join(name)).unwrap(),
                std::fs::read(output.path().join("second").join(name)).unwrap()
            );
        }
    }

    #[test]
    fn missing_or_changed_independent_reference_fails_before_generation() {
        let root = tempfile::tempdir().unwrap();
        copy_archive(root.path());
        let output = tempfile::tempdir().unwrap();
        let out = output.path().join("must-not-exist");
        let fnv = root
            .path()
            .join("test-proj/ExportAccessorVerify/fixtures/fnv_vectors.tsv");
        std::fs::write(&fnv, b"corrupt\t0\n").unwrap();
        assert!(generate(root.path(), &out)
            .unwrap_err()
            .to_string()
            .contains("checksum mismatch"));
        assert!(!out.exists());
        std::fs::remove_file(fnv).unwrap();
        assert!(generate(root.path(), &out)
            .unwrap_err()
            .to_string()
            .contains("missing oracle"));
        assert!(!out.exists());
    }
}
