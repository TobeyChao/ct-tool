//! 同一规范化工作区的进程间排他锁（对应 Python `ct/storage/workspace_lock.py`）。
//!
//! - 锁文件固定在 `<root>/.ct/export.lock`，不随 cache_dir 变化；
//! - 进程内互斥（静态注册表）+ OS advisory lock（fs2：POSIX flock /
//!   Windows LockFileEx）；进程死亡由系统自动释放，不留残余锁；
//! - Windows 上 LockFileEx 覆盖区间含第 0 字节，与 Python msvcrt
//!   锁第 0 字节互斥（过渡期新旧进程互斥）；
//! - 冲突立即返回 busy，不静默排队；锁不可重入。

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock};

use fs2::FileExt;

use crate::journal::PRIVATE_DIRNAME;

pub const LOCK_NAME: &str = "export.lock";

#[derive(Debug, Clone)]
pub struct WorkspaceBusyError(pub String);

impl std::fmt::Display for WorkspaceBusyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for WorkspaceBusyError {}

fn registry() -> &'static Mutex<HashMap<String, Arc<Mutex<()>>>> {
    static REGISTRY: OnceLock<Mutex<HashMap<String, Arc<Mutex<()>>>>> = OnceLock::new();
    REGISTRY.get_or_init(|| Mutex::new(HashMap::new()))
}

fn normalize_root(root: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for component in root.components() {
        match component {
            std::path::Component::CurDir => {}
            std::path::Component::ParentDir => {
                out.pop();
            }
            other => out.push(other.as_os_str()),
        }
    }
    out
}

/// 工作区排他锁。Drop 即释放。
pub struct WorkspaceLock {
    root: PathBuf,
    guard: Option<std::sync::MutexGuard<'static, ()>>,
    /// 保持注册表 Mutex 存活；字段在 guard 之后声明，确保 guard 先释放。
    _in_process: Arc<Mutex<()>>,
    handle: Option<std::fs::File>,
}

impl WorkspaceLock {
    /// 尝试获取锁；被占用立即返回 busy 错误。
    pub fn acquire(root: &Path) -> Result<Self, WorkspaceBusyError> {
        let root = normalize_root(root);
        let key = root.to_string_lossy().to_lowercase();
        let in_process = {
            let mut map = registry().lock().expect("锁注册表中毒");
            map.entry(key)
                .or_insert_with(|| Arc::new(Mutex::new(())))
                .clone()
        };
        // 注册表保证同键唯一 Arc；结构体持有 Arc 保证 Mutex 存活，
        // 因此把引用延长为 'static 是安全的。
        let mutex: &'static Mutex<()> = unsafe { &*Arc::as_ptr(&in_process) };
        let guard = match mutex.try_lock() {
            Ok(guard) => guard,
            Err(_) => {
                return Err(WorkspaceBusyError(format!(
                    "工作区正在保存、导出或部署，请稍后重试：{}",
                    root.display()
                )))
            }
        };

        let path = root.join(PRIVATE_DIRNAME).join(LOCK_NAME);
        let handle = (|| {
            std::fs::create_dir_all(path.parent().unwrap()).ok()?;
            std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .create(true)
                .truncate(false)
                .open(&path)
                .ok()
        })();
        let Some(handle) = handle else {
            drop(guard);
            return Err(WorkspaceBusyError(format!(
                "无法创建锁文件 {}",
                path.display()
            )));
        };
        if handle.try_lock_exclusive().is_err() {
            drop(guard);
            return Err(WorkspaceBusyError(format!(
                "工作区正在保存、导出或部署，请稍后重试：{}",
                root.display()
            )));
        }
        Ok(WorkspaceLock {
            root,
            guard: Some(guard),
            _in_process: in_process,
            handle: Some(handle),
        })
    }

    pub fn held(&self) -> bool {
        self.handle.is_some()
    }

    pub fn lock_path(&self) -> PathBuf {
        self.root.join(PRIVATE_DIRNAME).join(LOCK_NAME)
    }
}

impl Drop for WorkspaceLock {
    fn drop(&mut self) {
        if let Some(handle) = self.handle.take() {
            let _ = fs2::FileExt::unlock(&handle);
        }
        drop(self.guard.take());
    }
}

// WorkspaceLock 持有的 MutexGuard 通过注册表共享所有权保证存活；
// 锁本身仅用于排他，不包含可跨线程移动的内部可变引用风险。
unsafe impl Send for WorkspaceLock {}

impl std::fmt::Debug for WorkspaceLock {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("WorkspaceLock")
            .field("root", &self.root)
            .field("held", &self.held())
            .finish()
    }
}
