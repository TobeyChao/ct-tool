using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

/// <summary>
/// 引导层：把 ct 导出的 DataBundle 解析为可独立读取的“表句柄”。
/// 版本属于【整套已加载配置（bin）】：（1）ConfigReader.LoadBundle 一次性整套加载时 Bump 一次；
/// （2）各 ConfigTable 创建时只【捕获】当前版本，不再各自 Bump —— 避免“建第 2 张表就误判第 1 张 stale”。
/// （3）Dispose（销毁）一套时 Bump，使旧句柄失效（防 UAF，Debug 守卫生效）。
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

    /// <summary>按行下标取行对象指针（0-based）。</summary>
    public IntPtr RowAt(int index) => WireReader.RowAt(ItemsBase, index);

    /// <summary>按主键查行；未找到返回 IntPtr.Zero。</summary>
    public IntPtr ByID(int id)
    {
        int idx = WireReader.IndexSearch(Table, id);
        return idx < 0 ? IntPtr.Zero : WireReader.RowAt(ItemsBase, idx);
    }

    public void Dispose()
    {
        if (!_pin.IsAllocated) return;
        _pin.Free();
        TableVersion.Bump(); // 销毁（一套）→ 世代前进 → 旧句柄失效（Debug 守卫触发）
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
