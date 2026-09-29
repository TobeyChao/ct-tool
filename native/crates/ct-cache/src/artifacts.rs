//! 生成产物缓存（对应 Python `ct/cache/artifacts.py`）。
//!
//! 内容寻址：键 = sha256([版本, 生成器名, 全部有效输入] 的规范 JSON)；
//! 缓存记录携带类型（text/bytes）与完整性校验（payload sha256），
//! 损坏/不认识/校验失败一律失效重建；只存可重建的纯函数结果，
//! 不把缓存内容反序列化为可执行对象；写入原子（临时文件 + 替换）。

use std::collections::HashSet;
use std::path::{Path, PathBuf};

use ct_domain::hashing::{sha256_hex, stable_sha256};
use ct_storage::publication::atomic_write;

/// 内容寻址生成缓存。
pub struct ArtifactCache {
    directory: PathBuf,
    version: String,
    forced: bool,
    pub hits: usize,
    pub misses: usize,
    used: HashSet<PathBuf>,
}

#[derive(Debug)]
pub enum CachePayload {
    Text(String),
    Bytes(Vec<u8>),
}

/// 把输入规范化为可哈希的 JSON（bytes 以 sha256 代替，行/模型已是 JSON 形态）。
pub fn cache_key(version: &str, name: &str, inputs: &serde_json::Value) -> String {
    stable_sha256(&serde_json::json!([version, name, inputs]))
}

impl ArtifactCache {
    pub fn new(cache_dir: &Path, version: &str, forced: bool) -> Self {
        ArtifactCache {
            directory: cache_dir.join("artifacts"),
            version: version.to_string(),
            forced,
            hits: 0,
            misses: 0,
            used: HashSet::new(),
        }
    }

    fn entry_path(&self, name: &str, key: &str) -> PathBuf {
        self.directory.join(name).join(format!("{key}.json"))
    }

    /// 读取缓存：版本+输入键命中且校验通过才返回；任何损坏都重建。
    fn read(&self, name: &str, key: &str) -> Option<CachePayload> {
        let path = self.entry_path(name, key);
        let text = std::fs::read_to_string(&path).ok()?;
        let entry: serde_json::Value = serde_json::from_str(&text).ok()?;
        let payload = base64_decode(entry.get("payload")?.as_str()?)?;
        if entry.get("sha256")?.as_str()? != sha256_hex(&payload) {
            return None;
        }
        match entry.get("kind")?.as_str()? {
            "text" => Some(CachePayload::Text(String::from_utf8(payload).ok()?)),
            "bytes" => Some(CachePayload::Bytes(payload)),
            _ => None,
        }
    }

    fn write(&self, name: &str, key: &str, payload: &[u8], kind: &str) {
        let path = self.entry_path(name, key);
        let entry = serde_json::json!({
            "kind": kind,
            "sha256": sha256_hex(payload),
            "payload": base64_encode(payload),
        });
        let _ = atomic_write(&path, serde_json::to_string(&entry).unwrap().as_bytes());
    }

    /// 只读查询（并行安全）：命中返回（值, 条目路径）。
    pub fn read_text(&self, name: &str, inputs: &serde_json::Value) -> Option<(String, PathBuf)> {
        let key = cache_key(&self.version, name, inputs);
        match self.read(name, &key) {
            Some(CachePayload::Text(text)) => Some((text, self.entry_path(name, &key))),
            _ => None,
        }
    }

    pub fn read_bytes(&self, name: &str, inputs: &serde_json::Value) -> Option<(Vec<u8>, PathBuf)> {
        let key = cache_key(&self.version, name, inputs);
        match self.read(name, &key) {
            Some(CachePayload::Bytes(bytes)) => Some((bytes, self.entry_path(name, &key))),
            _ => None,
        }
    }

    /// 写入并标记使用（合并阶段串行调用）。
    pub fn store_text(&mut self, name: &str, inputs: &serde_json::Value, value: &str) {
        let key = cache_key(&self.version, name, inputs);
        self.write(name, &key, value.as_bytes(), "text");
        self.used.insert(self.entry_path(name, &key));
    }

    pub fn store_bytes(&mut self, name: &str, inputs: &serde_json::Value, value: &[u8]) {
        let key = cache_key(&self.version, name, inputs);
        self.write(name, &key, value, "bytes");
        self.used.insert(self.entry_path(name, &key));
    }

    /// 标记条目被本次导出使用（prune 依据）。
    pub fn mark_used(&mut self, path: PathBuf) {
        self.used.insert(path);
    }

    /// 命中计数（并行合并阶段使用）。
    pub fn mark_hit(&mut self, path: PathBuf) {
        self.used.insert(path);
        self.hits += 1;
    }

    /// 未命中计数（并行合并阶段使用）。
    pub fn mark_miss(&mut self) {
        self.misses += 1;
    }

    /// 纯函数生成：命中返回缓存，否则执行并落缓存。
    pub fn call_text(
        &mut self,
        name: &str,
        inputs: &serde_json::Value,
        generate: impl FnOnce() -> Result<String, String>,
    ) -> Result<String, String> {
        let key = cache_key(&self.version, name, inputs);
        self.used.insert(self.entry_path(name, &key));
        if !self.forced {
            if let Some(CachePayload::Text(text)) = self.read(name, &key) {
                self.hits += 1;
                return Ok(text);
            }
        }
        let result = generate()?;
        self.write(name, &key, result.as_bytes(), "text");
        self.misses += 1;
        Ok(result)
    }

    pub fn call_bytes(
        &mut self,
        name: &str,
        inputs: &serde_json::Value,
        generate: impl FnOnce() -> Result<Vec<u8>, String>,
    ) -> Result<Vec<u8>, String> {
        let key = cache_key(&self.version, name, inputs);
        self.used.insert(self.entry_path(name, &key));
        if !self.forced {
            if let Some(CachePayload::Bytes(bytes)) = self.read(name, &key) {
                self.hits += 1;
                return Ok(bytes);
            }
        }
        let result = generate()?;
        self.write(name, &key, &result, "bytes");
        self.misses += 1;
        Ok(result)
    }

    /// 全量导出成功后清理未被本次使用的条目。
    pub fn prune(&self) {
        let Ok(entries) = std::fs::read_dir(&self.directory) else {
            return;
        };
        for entry in entries.flatten() {
            let dir = entry.path();
            if !dir.is_dir() {
                continue;
            }
            if let Ok(files) = std::fs::read_dir(&dir) {
                for file in files.flatten() {
                    let path = file.path();
                    if path.extension().is_some_and(|e| e == "json") && !self.used.contains(&path) {
                        let _ = std::fs::remove_file(&path);
                    }
                }
            }
        }
    }
}

// ---- base64（缓存内部格式，与 Python base64 标准编码一致） ----

const B64: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

fn base64_encode(data: &[u8]) -> String {
    let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
    for chunk in data.chunks(3) {
        let b = [
            chunk[0],
            *chunk.get(1).unwrap_or(&0),
            *chunk.get(2).unwrap_or(&0),
        ];
        let n = ((b[0] as u32) << 16) | ((b[1] as u32) << 8) | b[2] as u32;
        out.push(B64[(n >> 18) as usize & 63] as char);
        out.push(B64[(n >> 12) as usize & 63] as char);
        out.push(if chunk.len() > 1 {
            B64[(n >> 6) as usize & 63] as char
        } else {
            '='
        });
        out.push(if chunk.len() > 2 {
            B64[n as usize & 63] as char
        } else {
            '='
        });
    }
    out
}

fn base64_decode(text: &str) -> Option<Vec<u8>> {
    let mut table = [0xFFu8; 256];
    for (i, &c) in B64.iter().enumerate() {
        table[c as usize] = i as u8;
    }
    let bytes: Vec<u8> = text.bytes().filter(|b| *b != b'=').collect();
    if text.len() % 4 != 0 {
        return None;
    }
    let mut out = Vec::with_capacity(bytes.len() * 3 / 4);
    let mut acc: u32 = 0;
    let mut bits = 0u32;
    for &b in &bytes {
        let v = table[b as usize];
        if v == 0xFF {
            return None;
        }
        acc = (acc << 6) | v as u32;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push((acc >> bits) as u8);
        }
    }
    Some(out)
}
