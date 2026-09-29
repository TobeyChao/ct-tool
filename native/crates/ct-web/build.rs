use std::{env, fs, path::Path};
fn collect(root: &Path, dir: &Path, entries: &mut Vec<(String, String)>) {
    let mut paths: Vec<_> = fs::read_dir(dir)
        .expect("web resources")
        .map(|e| e.unwrap().path())
        .collect();
    paths.sort();
    for path in paths {
        if path.is_dir() {
            collect(root, &path, entries);
        } else {
            println!("cargo:rerun-if-changed={}", path.display());
            entries.push((
                path.strip_prefix(root)
                    .unwrap()
                    .to_string_lossy()
                    .replace('\\', "/"),
                path.to_string_lossy().into(),
            ));
        }
    }
}
fn main() {
    let root = Path::new(&env::var("CARGO_MANIFEST_DIR").unwrap())
        .join("../../../web/static")
        .canonicalize()
        .expect("web/static");
    println!("cargo:rerun-if-changed={}", root.display());
    let mut entries = Vec::new();
    collect(&root, &root, &mut entries);
    let mut source = String::from("pub static ASSETS: &[(&str, &[u8])] = &[\n");
    for (key, path) in entries {
        source.push_str(&format!("({key:?}, include_bytes!({path:?})),\n"));
    }
    source.push_str("];\n");
    fs::write(
        Path::new(&env::var("OUT_DIR").unwrap()).join("assets.rs"),
        source,
    )
    .unwrap();
}
