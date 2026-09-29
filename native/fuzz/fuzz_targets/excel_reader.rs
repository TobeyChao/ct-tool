#![no_main]

use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    // TODO（任务 1.5 之后）：接入 Excel 读取入口
    let _ = data;
});