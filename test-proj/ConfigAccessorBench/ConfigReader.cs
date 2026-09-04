using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

/// <summary>
/// 引导层：把 ct 导出的 DataBundle 解析为可独立读取的“表句柄”。
/// 用 GCHandle 钉住表缓冲，使行/字段/向量指针在 Handle 存活期间有效；
/// 配合 TableVersion 作版本守卫（表重载/切语言时 Bump 并失效缓存）。
/// 纯 C# + unsafe，不依赖 Unity/游戏，可在本工程独立运行。
/// </summary>
public unsafe sealed class ConfigTable : IDisposable
{
    private readonly byte[] _bytes;
    private GCHandle _pin;
    private int _pVersion;

    public string Name { get; private set; }
    public IntPtr Table { get; private set; }
    public IntPtr ItemsBase { get; private set; }
    public int Count { get; private set; }

    public ConfigTable(string name, byte[] bytes)
    {
        Name = name;
        _bytes = bytes;
        _pin = GCHandle.Alloc(bytes, GCHandleType.Pinned);
        _pVersion = TableVersion.Bump();
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
        if (_pin.IsAllocated) _pin.Free();
    }
}

public static unsafe class ConfigReader
{
    /// <summary>加载 bundle，返回每张表 byte[]。</summary>
    public static Dictionary<string, byte[]> ReadBundle(byte[] bundle) => WireReader.ReadBundle(bundle);

    /// <summary>加载 bundle 中指定表为可独立读取的 ConfigTable。</summary>
    public static ConfigTable LoadTable(byte[] bundle, string name)
    {
        var tables = WireReader.ReadBundle(bundle);
        if (!tables.TryGetValue(name, out var bytes))
            throw new KeyNotFoundException($"bundle 中无表 {name}；可用：{string.Join(",", tables.Keys)}");
        return new ConfigTable(name, bytes);
    }
}
