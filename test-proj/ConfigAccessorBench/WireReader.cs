using System;
using System.Collections.Generic;
using System.Text;

/// <summary>
/// 自包含的 FlatBuffers 读取器（参考 fabulous-game 的 WireReader，去掉 Unity 依赖）。
/// 协议：slot = vtable 槽位 = 4 + 2*字段序（与原生 C / Lua 读取器一致）。
/// 同时提供读取工具，用于解析 ct 导出的 DataBundle → 单表 bytes。
/// </summary>
public static unsafe class WireReader
{
    // ---- 字节拼装（小端，flatbuffers 协议固定）----
    public static ushort GetU16(byte* p) => (ushort)(p[0] | (p[1] << 8));
    public static int GetI32(byte* p) => p[0] | (p[1] << 8) | (p[2] << 16) | (p[3] << 24);
    public static long GetI64(byte* p) => (long)((ulong)(uint)GetI32(p) | ((ulong)(uint)GetI32(p + 4) << 32));
    public static float GetF32(byte* p) => BitConverter.Int32BitsToSingle(GetI32(p));
    public static double GetF64(byte* p) => BitConverter.Int64BitsToDouble(GetI64(p));

    // ---- vtable 遍历（Table.__offset 同构）----
    public static int FieldOffset(byte* obj, int slot)
    {
        byte* vt = obj - GetI32(obj);
        ushort vtLen = GetU16(vt);
        if (slot < 0 || slot >= vtLen) return 0;
        return GetU16(vt + slot);
    }

    public static byte* Indirect(byte* obj, int slot)
    {
        int off = FieldOffset(obj, slot);
        return off == 0 ? null : obj + off + GetI32(obj + off);
    }

    // ---- 表级（对任意表布局成立，槽位由生成器传入）----

    /// <summary>items 向量数据区起点（长度前缀之后）。窗口加载时预解析一次。</summary>
    public static IntPtr VectorBase(IntPtr table)
    {
        byte* b = (byte*)table;
        byte* lenp = Indirect(b + GetI32(b), 4);
        return lenp == null ? IntPtr.Zero : (IntPtr)(lenp + 4);
    }

    /// <summary>按行下标（0-based）解析行对象指针（items 向量 uoffset 元素）。</summary>
    public static IntPtr RowAt(IntPtr itemsBase, int idx)
    {
        byte* pos = (byte*)itemsBase + (long)idx * 4;
        return (IntPtr)(pos + GetI32(pos));
    }

    /// <summary>items 向量长度。</summary>
    public static int Count(IntPtr table)
    {
        byte* b = (byte*)table;
        byte* lenp = Indirect(b + GetI32(b), 4);
        return lenp == null ? 0 : GetI32(lenp);
    }

    /// <summary>index 向量二分：返回行下标（0-based），未找到返回 -1。</summary>
    public static int IndexSearch(IntPtr table, int id)
    {
        byte* b = (byte*)table;
        byte* lenp = Indirect(b + GetI32(b), 6);
        if (lenp == null) return -1;
        byte* entries = lenp + 4;
        int lo = 0, hi = GetI32(lenp) - 1;
        while (lo <= hi)
        {
            int mid = (lo + hi) / 2;
            byte* e = entries + (long)mid * 8;
            int midId = GetI32(e);
            if (midId == id) return GetI32(e + 4);
            if (midId < id) lo = mid + 1;
            else hi = mid - 1;
        }
        return -1;
    }

    /// <summary>间接字段（string/嵌套 table/vector）：uoffset 相对自身。缺省返回 null。</summary>
    public static IntPtr Indirect(IntPtr obj, int slot) => (IntPtr)Indirect((byte*)obj, slot);

    // ---- 字段读（obj = 行/嵌套结构体指针；缺省返回类型默认值）----

    public static byte I8(IntPtr obj, int slot)
    {
        int o = FieldOffset((byte*)obj, slot);
        return o == 0 ? (byte)0 : (byte)((byte*)obj)[o];
    }

    public static int I32(IntPtr obj, int slot)
    {
        int o = FieldOffset((byte*)obj, slot);
        return o == 0 ? 0 : GetI32((byte*)obj + o);
    }

    public static long I64(IntPtr obj, int slot)
    {
        int o = FieldOffset((byte*)obj, slot);
        return o == 0 ? 0L : GetI64((byte*)obj + o);
    }

    public static float F32(IntPtr obj, int slot)
    {
        int o = FieldOffset((byte*)obj, slot);
        return o == 0 ? 0f : GetF32((byte*)obj + o);
    }

    public static double F64(IntPtr obj, int slot)
    {
        int o = FieldOffset((byte*)obj, slot);
        return o == 0 ? 0d : GetF64((byte*)obj + o);
    }

    public static bool Bool(IntPtr obj, int slot)
    {
        int o = FieldOffset((byte*)obj, slot);
        return o != 0 && ((byte*)obj)[o] != 0;
    }

    /// <summary>字符串字段：长度前缀 + UTF-8 解码。缺省返回 null。</summary>
    public static string Str(IntPtr obj, int slot)
    {
        byte* s = Indirect((byte*)obj, slot);
        if (s == null) return null;
        return Encoding.UTF8.GetString(s + 4, GetI32(s));
    }

    // ---- 数组（每元素重复解析基址：before 路径）----

    public static int ArrLen(IntPtr obj, int slot)
    {
        byte* v = Indirect((byte*)obj, slot);
        return v == null ? 0 : GetI32(v);
    }

    public static int ArrI32(IntPtr obj, int slot, int i)
    {
        byte* v = CheckElem(obj, slot, i);
        return v == null ? 0 : GetI32(v + (long)i * 4);
    }

    public static string ArrStr(IntPtr obj, int slot, int i)
    {
        byte* v = CheckElem(obj, slot, i);
        if (v == null) return null;
        byte* sp = v + (long)i * 4;
        byte* s = sp + GetI32(sp);
        return Encoding.UTF8.GetString(s + 4, GetI32(s));
    }

    private static byte* CheckElem(IntPtr obj, int slot, int i)
    {
        byte* v = Indirect((byte*)obj, slot);
        if (v == null) return null;
        int len = GetI32(v);
        if ((uint)i >= (uint)len) throw new ArgumentOutOfRangeException(nameof(i), $"[Config] array index {i} out of range (len {len})");
        return v + 4;
    }

    // ---- 向量基址（after B-2b 路径：一次解析，之后直读）----

    /// <summary>返回向量基址（长度前缀之后）；缺省返回 IntPtr.Zero。</summary>
    public static IntPtr VecBase(IntPtr obj, int slot)
    {
        byte* v = Indirect((byte*)obj, slot);
        return v == null ? IntPtr.Zero : (IntPtr)(v + 4);
    }

    public static int VecLen(IntPtr obj, int slot) => ArrLen(obj, slot);

    // ---- 字段偏移缓存（一次解析 vtable，之后 obj+offset 直读）----

    /// <summary>按当前表的 vtable 一次性解析字段偏移表（0 表示字段缺省）。所有行共享同一 vtable 布局。</summary>
    public static int[] BuildFieldOffsets(IntPtr obj, int maxSlot)
    {
        byte* b = (byte*)obj;
        int[] off = new int[maxSlot];
        for (int slot = 0; slot < maxSlot; slot++) off[slot] = FieldOffset(b, slot);
        return off;
    }

    public static byte I8At(IntPtr obj, int off) => off == 0 ? (byte)0 : ((byte*)obj)[off];
    public static int I32At(IntPtr obj, int off) => off == 0 ? 0 : GetI32((byte*)obj + off);
    public static long I64At(IntPtr obj, int off) => off == 0 ? 0L : GetI64((byte*)obj + off);
    public static float F32At(IntPtr obj, int off) => off == 0 ? 0f : GetF32((byte*)obj + off);
    public static double F64At(IntPtr obj, int off) => off == 0 ? 0d : GetF64((byte*)obj + off);
    public static bool BoolAt(IntPtr obj, int off) => off != 0 && ((byte*)obj)[off] != 0;

    /// <summary>间接字段（string/嵌套 table/vector）用预取偏移：obj+off 处是 uoffset，再加相对得到目标。</summary>
    public static byte* IndirectAt(IntPtr obj, int off)
    {
        if (off == 0) return null;
        byte* b = (byte*)obj;
        return b + off + GetI32(b + off);
    }

    public static string StrAt(IntPtr obj, int off)
    {
        byte* s = IndirectAt(obj, off);
        if (s == null) return null;
        return Encoding.UTF8.GetString(s + 4, GetI32(s));
    }

    // ---- DataBundle 解析：tables 向量 → 每张 BundledTable(name + data) ----

    public static Dictionary<string, byte[]> ReadBundle(byte[] bytes)
    {
        var result = new Dictionary<string, byte[]>();
        fixed (byte* p = bytes)
        {
            byte* root = p + GetI32(p); // FlatBuffers 根表在 buffer + rootOffset
            byte* tables = Indirect(root, 4); // slot 0: tables vector
            if (tables == null) return result;
            int n = GetI32(tables);
            byte* entries = tables + 4;
            for (int i = 0; i < n; i++)
            {
                byte* entry = entries + (long)i * 4;
                entry += GetI32(entry);
                // BundledTable: slot0=name(string), slot1=data([ubyte])
                byte* nameStr = Indirect(entry, 4);
                string name = nameStr == null ? "" : Encoding.UTF8.GetString(nameStr + 4, GetI32(nameStr));
                byte* dataVec = Indirect(entry, 6);
                if (dataVec == null) continue;
                int dataLen = GetI32(dataVec);
                byte* data = dataVec + 4;
                byte[] copy = new byte[dataLen];
                for (int b = 0; b < dataLen; b++) copy[b] = data[b];
                result[name] = copy;
            }
        }
        return result;
    }
}
