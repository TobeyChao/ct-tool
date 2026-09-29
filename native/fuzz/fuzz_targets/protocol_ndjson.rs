#![no_main]

use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    // TODO（任务 1.4 之后）：接入 NDJSON 消息解析入口
    let _ = data;
});