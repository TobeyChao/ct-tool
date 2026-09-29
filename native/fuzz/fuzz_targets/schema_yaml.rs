#![no_main]

use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    // TODO（任务 2.1 之后）：接入 Schema YAML 解析入口
    let _ = data;
});