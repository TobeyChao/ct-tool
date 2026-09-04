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
public unsafe sealed class ConfigTable : IDisposable
{
    private readonly byte[] _bytes;
    private GCHandle _pin;
    private readonly int _pVersion; // 该表创建时整套 bin 的版本快照

    public string Name { get; private set; }
    public IntPtr Table { get; private set; }
    public IntPtr ItemsBase { get; private set; }
    public int Count { get; private set; }

    public ConfigTable(string name, byte[] bytes)
    {
        Name = name;
        _bytes = bytes;
        _pin = GCHandle.Alloc(bytes, GCHandleType.Pinned);
        _pVersion = TableVersion.Current; // 捕获（不再 increase）——版本属于整 bin
        Table = _pin.AddrOfPinnedObject();
        ItemsBase = WireReader.VectorBase(Table);
        Count = WireReader.Count(Table);
    }

    public int Version => _pVersion;

    /// <summary>按行下标取行对象指针（0-based）；越界返回 IntPtr.Zero（Release 也生效的无条件兜底）。</summary>
    public IntPtr RowAt(int index) => (uint)index >= (uint)Count ? IntPtr.Zero : WireReader.RowAt(ItemsBase, index);

    /// <summary>按主键查行；未找到返回 IntPtr.Zero。</summary>
    public IntPtr ByID(int id)
    {
        int idx = WireReader.IndexSearch(Table, id);
        return idx < 0 ? IntPtr.Zero : WireReader.RowAt(ItemsBase, idx);
    }

    /// <summary>释放钉住句柄。世代（TableVersion）只在整套边界推进（LoadBundle/Clear），此处不 Bump。</summary>
    public void Dispose()
    {
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

    /// <summary>一次性加载整套 bin：先 Bump 一次（世代前进），再为各表建句柄；所有表共享同一版本。</summary>
    public static List<ConfigTable> LoadBundle(byte[] bundle)
    {
        TableVersion.Bump(); // 一次，代表“加载了一套新配置”
        var list = new List<ConfigTable>();
        foreach (var kv in WireReader.ReadBundle(bundle))
            list.Add(new ConfigTable(kv.Key, kv.Value));
        return list;
    }
}
