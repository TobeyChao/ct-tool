//! 安全关闭：正常退出不得用强杀代替取消。

use std::time::Duration;

use crate::control::running_tasks;
use crate::dispatcher::Shared;

/// 等待所有写任务到达终态（发布边界由任务自身保证）。
pub fn wait_for_quiescence(shared: &Shared) {
    while running_tasks(shared) > 0 {
        std::thread::sleep(Duration::from_millis(10));
    }
}
