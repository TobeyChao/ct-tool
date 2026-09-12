using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

/// <summary>
/// 引导层：把 ct 导出的 DataBundle 解析为可独立读取的“表句柄”。
/// 版本 = 整套已加载配置（bin）的世代号，只在【整套边界】推进：
/// （1）ConfigReader.LoadBundle 加载新一套时 Bump 一次；
/// （2）各 ConfigTable 创建时只【捕获】当前世代（不各自 Bump）；
/// （3）Runtime.Clear 整套销毁时 Bump 一次，使任何残留旧句柄失效（防 UAF，Debug 守卫生效）。
/// 单表 Dispose 仅释放钉住句柄、不推进世代 —— bin 为原子单元，禁止整套生命周期外单独销毁单表。
/// 纯 C# + unsafe，不依赖 Unity/游戏，可在本工程独立运行。
/// </summary>
/// <summary>
/// 整套 bin 的单一托管缓冲 + 一次 pin。所有表句柄都指向它内部的切片，
/// 因此 2000 张表只需要 1 个 GCHandle（原实现每表一个，共 2000 个）。
/// 生命周期遵循「bin 是原子整套」契约：只在整套边界创建/释放。
/// </summary>
public unsafe sealed class ConfigBundle : IDisposable
{
    private readonly byte[] _bytes;
    private GCHandle _pin;

    public IntPtr Base { get; private set; }

    public ConfigBundle(byte[] bytes)
    {
        _bytes = bytes;
        _pin = GCHandle.Alloc(bytes, GCHandleType.Pinned);
        Base = _pin.AddrOfPinnedObject();
    }

    public void Dispose()
    {
        if (!_pin.IsAllocated) return;
        _pin.Free();
        Base = IntPtr.Zero;
    }
}

public unsafe sealed class ConfigTable : IDisposable
{
    private readonly byte[] _bytes;
    private readonly ConfigBundle _bundle; // 非 null 时本表是共享缓冲的视图，Dispose 不释放 pin
    private GCHandle _pin;
    private readonly int _pVersion; // 该表创建时整套 bin 的版本快照

    public string Name { get; private set; }
    public IntPtr Table { get; private set; }
    public IntPtr ItemsBase { get; private set; }
    public int Count { get; private set; }

    // index 向量在加载时预解析一次：否则每次 ByID 都要重走 root offset + vtable（实测 ~8 ns/次）
    private IntPtr _indexEntries;
    private int _indexCount;

    // 开放寻址哈希索引（导出器产出）：把 ByID 从 13 次二分探测降到 ~1.5 次哈希探测
    private IntPtr _hashSlots;
    private int _hashMask;

    // 二级查询索引（表级 `indexes:` 声明，导出器产出）
    //   Code  —— 开放寻址桶表，桶里存 rowIndex + 1（0 = 空），key = FNV-1a 64
    private IntPtr _codeSlots;
    private int _codeMask;

    public ConfigTable(string name, byte[] bytes)
    {
        Name = name;
        _bytes = bytes;
        _pin = GCHandle.Alloc(bytes, GCHandleType.Pinned);
        _pVersion = TableVersion.Current; // 捕获（不再 increase）——版本属于整 bin
        Table = _pin.AddrOfPinnedObject();
        Init();
    }

    /// <summary>共享缓冲视图：Table 指向 bundle 缓冲内的切片，不新增 pin、不拷贝。</summary>
    public ConfigTable(string name, ConfigBundle bundle, int offset, int length)
    {
        Name = name;
        _bundle = bundle;
        _pVersion = TableVersion.Current;
        Table = (IntPtr)((byte*)bundle.Base + offset);
        Init();
    }

    private void Init()
    {
        ItemsBase = WireReader.VectorBase(Table);
        Count = WireReader.Count(Table);
        byte* root = (byte*)Table + WireReader.GetI32((byte*)Table);
        byte* indexLen = (byte*)WireReader.Indirect(root, 6);
        if (indexLen != null)
        {
            _indexEntries = (IntPtr)(indexLen + 4);
            _indexCount = WireReader.GetI32(indexLen);
        }
        byte* hashVec = (byte*)WireReader.Indirect(root, 8);
        if (hashVec != null)
        {
            _hashSlots = (IntPtr)(hashVec + 4);
            _hashMask = WireReader.GetI32(hashVec) - 1;
        }
        byte* codeVec = (byte*)WireReader.Indirect(root, 10);
        if (codeVec != null)
        {
            _codeSlots = (IntPtr)(codeVec + 4);
            _codeMask = WireReader.GetI32(codeVec) - 1;
        }
    }

    /// <summary>
    /// Code 精确字符串查找，返回行下标；未找到返回 -1。
    /// ``fieldIndex`` 是**客户端字段序**（生成器传入），用于撞哈希时按字段精确确认。
    /// </summary>
    public int CodeNameSearch(int fieldIndex, string code)
    {
        if (_codeMask <= 0 || code == null) return -1;
        int* slots = (int*)_codeSlots;
        int mask = _codeMask;
        int slot = 4 + 2 * fieldIndex;          // 客户端字段序 → vtable 槽位
        int b = (int)(WireReader.Fnv1a64(code) & (uint)mask);
        while (true)
        {
            int v = slots[b];
            if (v == 0) return -1;              // 空桶 = 查找失败（开放寻址可安全提前退出）
            int row = v - 1;
            IntPtr p = WireReader.RowAt(ItemsBase, row);
            // 不同字符串可能撞同一哈希 ⇒ 必须按字段做精确比较
            if (WireReader.Str(p, slot) == code) return row;
            b = (b + 1) & mask;
        }
    }

    public int Version => _pVersion;

    /// <summary>按行下标取行对象指针（0-based）；越界返回 IntPtr.Zero（Release 也生效的无条件兜底）。</summary>
    public IntPtr RowAt(int index) => (uint)index >= (uint)Count ? IntPtr.Zero : WireReader.RowAt(ItemsBase, index);

    /// <summary>按主键查行；未找到返回 IntPtr.Zero。有哈希索引走哈希，否则退化为二分。</summary>
    public IntPtr ByID(int id) => ByID(id, out _);

    /// <summary>按主键查行，并回传行下标（供 per-field 缓存按行下标索引）。</summary>
    public IntPtr ByID(int id, out int rowIndex)
    {
        rowIndex = _hashMask > 0 ? HashSearch(id) : IndexSearch(id);
        return rowIndex < 0 ? IntPtr.Zero : WireReader.RowAt(ItemsBase, rowIndex);
    }

    /// <summary>开放寻址哈希查找，返回行下标；未找到返回 -1。桶里存 index 位置 + 1。</summary>
    public int HashSearch(int id)
    {
        int* slots = (int*)_hashSlots;
        int* index = (int*)_indexEntries;
        int mask = _hashMask;
        uint h = (uint)id * 2654435761u;
        int b = (int)h & mask;
        while (true)
        {
            int v = slots[b];
            if (v == 0) return -1;
            int pos = v - 1;
            if (index[pos * 2] == id) return index[pos * 2 + 1];
            b = (b + 1) & mask;
        }
    }

    /// <summary>在预解析的 index 向量上二分，返回行下标；未找到返回 -1。</summary>
    public int IndexSearch(int id)
    {
        byte* entries = (byte*)_indexEntries;
        int lo = 0, hi = _indexCount - 1;
        while (lo <= hi)
        {
            int mid = (lo + hi) >> 1;
            byte* e = entries + (long)mid * 8;
            int midId = WireReader.GetI32(e);
            if (midId == id) return WireReader.GetI32(e + 4);
            if (midId < id) lo = mid + 1;
            else hi = mid - 1;
        }
        return -1;
    }

    // ---- 字段偏移表：按 vtable 身份记忆化 ----
    // 同一张表的所有行共享同一份 vtable 布局时，只需解析一次；flatbuffers 会对相同布局
    // 去重 vtable，故真实表通常只有 1~4 个不同 vtable。这里用极小的线性表缓存，
    // 命中成本 = 1 次 vtable 指针读 + 1~4 次比较，换来每次字段读省掉 3 次依赖加载。
    private (nint Vtable, int[] Offsets)[] _vtCache;
    private int _vtCount;

    /// <summary>取该行所属 vtable 的 slot→offset 表（slot = 4 + 2*字段序）。</summary>
    public int[] OffsetsFor(IntPtr row, int maxSlot)
    {
        nint vt = (nint)((byte*)row - WireReader.GetI32((byte*)row));
        var cache = _vtCache;
        if (cache != null)
        {
            for (int i = 0; i < _vtCount; i++)
            {
                if (cache[i].Vtable == vt) return cache[i].Offsets;
            }
        }
        int[] offsets = WireReader.BuildFieldOffsets(row, maxSlot);
        if (cache == null)
        {
            cache = new (nint, int[])[4];
            _vtCache = cache;
        }
        if (_vtCount == cache.Length)
        {
            var grown = new (nint, int[])[cache.Length * 2];
            Array.Copy(cache, grown, cache.Length);
            _vtCache = cache = grown;
        }
        cache[_vtCount++] = (vt, offsets);
        return offsets;
    }

    /// <summary>
    /// 释放钉住句柄。共享缓冲视图下为空操作 —— pin 由 ConfigBundle 持有，
    /// 生命周期由 ConfigReader 在整套边界统一管理。此处不 Bump 世代（同原契约）。
    /// </summary>
    public void Dispose()
    {
        if (_bundle != null) return;
        if (!_pin.IsAllocated) return;
        _pin.Free();
    }
}

public static unsafe class ConfigReader
{
    /// <summary>加载 bundle，返回每张表 byte[]。</summary>
    public static Dictionary<string, byte[]> ReadBundle(byte[] bundle) => WireReader.ReadBundle(bundle);

    /// <summary>加载 bundle 中指定表为可独立读取的 ConfigTable（单表，不新增世代）。</summary>
    public static ConfigTable LoadTable(byte[] bundle, string name)
    {
        var tables = WireReader.ReadBundle(bundle);
        if (!tables.TryGetValue(name, out var bytes))
            throw new KeyNotFoundException($"bundle 中无表 {name}；可用：{string.Join(",", tables.Keys)}");
        return new ConfigTable(name, bytes);
    }

    private static ConfigBundle _current;

    /// <summary>
    /// 一次性加载整套 bin：先 Bump 一次（世代前进），再为各表建**视图句柄**；所有表共享同一版本、
    /// 同一份 pin 住的缓冲。上一套的 pin 在此释放（整套边界语义）。
    /// </summary>
    public static List<ConfigTable> LoadBundle(byte[] bundle)
    {
        TableVersion.Bump(); // 一次，代表“加载了一套新配置”
        var views = WireReader.ReadBundleViews(bundle);
        var shared = new ConfigBundle(bundle);
        _current?.Dispose();
        _current = shared;
        var list = new List<ConfigTable>(views.Count);
        foreach (var v in views)
            list.Add(new ConfigTable(v.Name, shared, v.Offset, v.Length));
        return list;
    }

    /// <summary>整套销毁：释放共享缓冲。（Runtime.Clear 会先 Dispose 各表句柄，视图 Dispose 为空操作。）</summary>
    public static void Unload()
    {
        _current?.Dispose();
        _current = null;
    }
}
