//! 最小 FlatBuffers 构建器：逐行为对齐 Python `flatbuffers.Builder`
//! （Prep/Pad/vtable 去重/共享字符串/Finish 无语义之外的字节差异）。
//!
//! 产物字节一致性由 `tests/compat/tests/binary_golden.rs` 与 golden/*.bin
//! 对照保证。不支持 size prefix、file identifier、force_defaults 等
//! Python 侧同样未用的特性。

use std::collections::HashMap;

/// 偏移量以「距缓冲区末尾的距离」计量（与 Python Builder.Offset() 一致）。
pub type UOffset = u32;

/// 生成 `prepend_*_slot`：值 == 默认值时省略槽位。
macro_rules! scalar_slot {
    ($name:ident, $prepend:ident, $t:ty) => {
        pub fn $name(&mut self, slot: usize, v: $t, default: $t) {
            if v != default {
                self.$prepend(v);
                self.slot(slot);
            }
        }
    };
}

pub struct Builder {
    buf: Vec<u8>,
    head: usize,
    minalign: usize,
    current_vtable: Option<Vec<u32>>,
    object_end: u32,
    /// 裁剪后 vtable 内容 → 已写出 vtable 的 offset。
    vtables: HashMap<Vec<u16>, u32>,
    shared_strings: HashMap<String, u32>,
    vector_num_elems: usize,
}

impl Builder {
    pub fn new(capacity: usize) -> Self {
        let cap = capacity.max(1);
        Builder {
            head: cap,
            buf: vec![0; cap],
            minalign: 1,
            current_vtable: None,
            object_end: 0,
            vtables: HashMap::new(),
            shared_strings: HashMap::new(),
            vector_num_elems: 0,
        }
    }

    /// 距缓冲区末尾的距离（Python `Offset()`）。
    pub fn offset(&self) -> u32 {
        (self.buf.len() - self.head) as u32
    }

    /// 已产出字节视图。
    pub fn output(&self) -> &[u8] {
        &self.buf[self.head..]
    }

    fn grow(&mut self) {
        let new_size = (self.buf.len() * 2).max(1);
        let mut next = vec![0u8; new_size];
        let diff = new_size - self.buf.len();
        next[diff..].copy_from_slice(&self.buf);
        self.buf = next;
        self.head += diff;
    }

    /// Python `Pad(n)`：写 n 个零字节。
    pub fn pad(&mut self, n: usize) {
        if n == 0 {
            return;
        }
        self.head -= n;
        self.buf[self.head..self.head + n].fill(0);
    }

    /// Python `Prep(size, additional)`。
    pub fn prep(&mut self, size: usize, additional: usize) {
        if size > self.minalign {
            self.minalign = size;
        }
        let used = self.buf.len() - self.head;
        let align = (0usize.wrapping_sub(used + additional)) & (size - 1);
        while self.head < align + size + additional {
            self.grow();
        }
        self.pad(align);
    }

    fn place(&mut self, bytes: &[u8]) {
        self.head -= bytes.len();
        self.buf[self.head..self.head + bytes.len()].copy_from_slice(bytes);
    }

    /// 在绝对位置（自缓冲区头部计）覆写。
    fn write_at(&mut self, pos: usize, bytes: &[u8]) {
        self.buf[pos..pos + bytes.len()].copy_from_slice(bytes);
    }

    pub fn slot(&mut self, n: usize) {
        let offset = self.offset();
        if let Some(vt) = &mut self.current_vtable {
            vt[n] = offset;
        }
    }

    // ---- 标量 prepend ----

    pub fn prepend_u8(&mut self, v: u8) {
        self.prep(1, 0);
        self.place(&[v]);
    }
    pub fn prepend_bool(&mut self, v: bool) {
        self.prepend_u8(u8::from(v));
    }
    pub fn prepend_i8(&mut self, v: i8) {
        self.prep(1, 0);
        self.place(&v.to_le_bytes());
    }
    pub fn prepend_u16(&mut self, v: u16) {
        self.prep(2, 0);
        self.place(&v.to_le_bytes());
    }
    pub fn prepend_i16(&mut self, v: i16) {
        self.prep(2, 0);
        self.place(&v.to_le_bytes());
    }
    pub fn prepend_u32(&mut self, v: u32) {
        self.prep(4, 0);
        self.place(&v.to_le_bytes());
    }
    pub fn prepend_i32(&mut self, v: i32) {
        self.prep(4, 0);
        self.place(&v.to_le_bytes());
    }
    pub fn prepend_u64(&mut self, v: u64) {
        self.prep(8, 0);
        self.place(&v.to_le_bytes());
    }
    pub fn prepend_i64(&mut self, v: i64) {
        self.prep(8, 0);
        self.place(&v.to_le_bytes());
    }
    pub fn prepend_f32(&mut self, v: f32) {
        self.prep(4, 0);
        self.place(&v.to_le_bytes());
    }
    pub fn prepend_f64(&mut self, v: f64) {
        self.prep(8, 0);
        self.place(&v.to_le_bytes());
    }

    /// Python `PrependUOffsetTRelative`。
    pub fn prepend_uoffset(&mut self, off: UOffset) {
        self.prep(4, 0);
        assert!(off <= self.offset(), "offset arithmetic error");
        let rel = self.offset() - off + 4;
        self.place(&rel.to_le_bytes());
    }

    /// Python `PrependSOffsetTRelative`。
    pub fn prepend_soffset(&mut self, off: u32) {
        self.prep(4, 0);
        assert!(off <= self.offset(), "offset arithmetic error");
        let rel = (self.offset() - off + 4) as i32;
        self.place(&rel.to_le_bytes());
    }

    // ---- *Slot：值 == 默认值时省略槽位 ----

    pub fn prepend_uoffset_slot(&mut self, slot: usize, off: UOffset, default: UOffset) {
        if off != default {
            self.prepend_uoffset(off);
            self.slot(slot);
        }
    }

    scalar_slot!(prepend_i8_slot, prepend_i8, i8);
    scalar_slot!(prepend_u8_slot, prepend_u8, u8);
    scalar_slot!(prepend_i16_slot, prepend_i16, i16);
    scalar_slot!(prepend_u16_slot, prepend_u16, u16);
    scalar_slot!(prepend_i32_slot, prepend_i32, i32);
    scalar_slot!(prepend_u32_slot, prepend_u32, u32);
    scalar_slot!(prepend_i64_slot, prepend_i64, i64);
    scalar_slot!(prepend_u64_slot, prepend_u64, u64);
    scalar_slot!(prepend_f32_slot, prepend_f32, f32);
    scalar_slot!(prepend_f64_slot, prepend_f64, f64);
    scalar_slot!(prepend_bool_slot, prepend_bool, bool);

    // ---- table ----

    pub fn start_object(&mut self, num_fields: usize) {
        self.current_vtable = Some(vec![0; num_fields]);
        self.object_end = self.offset();
    }

    /// Python `WriteVtable`：含裁剪与内容去重。
    pub fn end_object(&mut self) -> UOffset {
        let current = self.current_vtable.take().expect("start_object 未调用");

        // 占位 soffset，稍后覆写
        self.prepend_soffset(0);
        let object_offset = self.offset();

        // 去重键：反向遍历、仅裁尾随零、相对偏移 + 对象大小
        let mut key: Vec<u16> = Vec::with_capacity(current.len() + 1);
        let mut trim = true;
        for &elem in current.iter().rev() {
            if elem == 0 {
                if trim {
                    continue;
                }
                key.push(0);
            } else {
                key.push((object_offset - elem) as u16);
                trim = false;
            }
        }
        let object_size = (object_offset - self.object_end) as u16;
        key.push(object_size);

        if let Some(&existing) = self.vtables.get(&key) {
            // 复用已写出的 vtable：丢弃占位 prepend 并就地改写 soffset。
            let object_start = self.buf.len() - object_offset as usize;
            self.head = object_start;
            let rel = existing as i64 - object_offset as i64;
            let bytes = (rel as i32).to_le_bytes();
            self.write_at(self.head, &bytes);
            return object_offset;
        }

        // 写出新 vtable（逆序）
        let mut trailing = 0usize;
        let mut trim = true;
        for &elem in current.iter().rev() {
            if elem == 0 {
                if trim {
                    trailing += 1;
                    continue;
                }
                self.prepend_u16(0);
            } else {
                self.prepend_u16((object_offset - elem) as u16);
                trim = false;
            }
        }
        self.prepend_u16(object_size);
        let vbytes = ((current.len() - trailing + 2) * 2) as u16;
        self.prepend_u16(vbytes);

        let object_start = self.buf.len() - object_offset as usize;
        let rel = (self.offset() - object_offset) as i32;
        self.write_at(object_start, &rel.to_le_bytes());

        self.vtables.insert(key, self.offset());
        object_offset
    }

    // ---- vector ----

    pub fn start_vector(&mut self, elem_size: usize, num_elems: usize, alignment: usize) {
        self.vector_num_elems = num_elems;
        self.prep(4, elem_size * num_elems);
        self.prep(alignment, elem_size * num_elems);
    }

    pub fn end_vector(&mut self) -> UOffset {
        let n = self.vector_num_elems as u32;
        self.place(&n.to_le_bytes());
        self.offset()
    }

    // ---- string / bytes ----

    pub fn create_string(&mut self, s: &str) -> UOffset {
        let bytes = s.as_bytes();
        self.prep(4, bytes.len() + 1);
        self.place(&[0]); // null 终止符
        self.head -= bytes.len();
        self.buf[self.head..self.head + bytes.len()].copy_from_slice(bytes);
        self.vector_num_elems = bytes.len();
        self.end_vector()
    }

    /// Python `CreateSharedString`：内容去重。
    pub fn create_shared_string(&mut self, s: &str) -> UOffset {
        if let Some(&off) = self.shared_strings.get(s) {
            return off;
        }
        let off = self.create_string(s);
        self.shared_strings.insert(s.to_string(), off);
        off
    }

    /// Python `CreateByteVector`。
    pub fn create_byte_vector(&mut self, bytes: &[u8]) -> UOffset {
        self.prep(4, bytes.len());
        self.head -= bytes.len();
        self.buf[self.head..self.head + bytes.len()].copy_from_slice(bytes);
        self.place(&(bytes.len() as u32).to_le_bytes());
        self.offset()
    }

    // ---- finish ----

    /// Python `Finish`（无 size prefix / file identifier）。
    pub fn finish(&mut self, root: UOffset) {
        self.prep(self.minalign, 4);
        self.prepend_uoffset(root);
    }
}
