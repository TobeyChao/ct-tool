using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;

// NOTE: 本 reader 只面向【可信、工具生成、不可变】的 FlatBuffers 配置数据。
// Release（未定义 CONFIG_DEBUG）下，逐元素的版本/越界检查被编译掉（harmony LH_DEBUG 同款），
// 以获得 VecBase 直读的性能；调用方必须传合法下标，且只使用“当前已加载这套 bin”里的句柄。
// 仅 `_base == null`（缺失字段）做无条件安全兜底。若喂脏数据/损坏 bundle，属未定义行为。

/// <summary>read-only 回调式 struct 读取协议（对齐 harmony IConfigStruct）。</summary>
public interface IConfigStruct
{
    unsafe void SetPointer(byte* p, int pVersion);
}

/// <summary>版本守卫：整套已加载配置（bin）的世代号。加载/重载/切语言/销毁【整套】时才 Bump。</summary>
public static unsafe class TableVersion
{
    private static int _version;
    public static int Current => _version;
    public static int Bump() => ++_version;

    [System.Diagnostics.Conditional("CONFIG_DEBUG")]
    public static void Check(int v)
    {
        if (v != _version)
            throw new InvalidOperationException($"[Config] stale reader (version {v} != {_version}): config set reloaded or language switched");
    }

    // 非条件断言：供版本守卫演示/诊断用（Release 下也生效）
    public static void AssertFresh(int v)
    {
        if (v != _version)
            throw new InvalidOperationException($"[Config] stale reader (version {v} != {_version}): config set reloaded or language switched");
    }
}

/// <summary>FlatBuffers 标量向量容器：一次 Indirect 拿基址+长度，[i] 直读（B-2b / harmony NArray&lt;T&gt;）。</summary>
public unsafe struct NArray<T> : IEnumerable<T> where T : unmanaged
{
    private byte* _base;
    private readonly int _len;
    private readonly int _pVersion;

    public NArray(IntPtr obj, int slot, int pVersion)
    {
        byte* v = (byte*)WireReader.Indirect(obj, slot);
        _len = v == null ? 0 : *(int*)v;
        _base = v == null ? null : v + 4;
        _pVersion = pVersion;
    }

    public int Length => _len;

    public T this[int index]
    {
        get
        {
            // 缺失字段（Indirect 返回 null）→ 无条件安全兜底，避免 Release 下解引用 null
            if (_base == null) return default;
#if CONFIG_DEBUG
            TableVersion.Check(_pVersion);
            if ((uint)index >= (uint)_len) throw new IndexOutOfRangeException($"index {index} len {_len}");
#endif
            return ((T*)_base)[index];
        }
    }

    public bool SafeGet(int index, out T value)
    {
        if ((uint)index >= (uint)_len) { value = default; return false; }
        value = this[index]; return true;
    }

    public IEnumerator<T> GetEnumerator() { for (int i = 0; i < _len; i++) yield return this[i]; }
    IEnumerator IEnumerable.GetEnumerator() { for (int i = 0; i < _len; i++) yield return this[i]; }
}

/// <summary>FlatBuffers 结构体/嵌套表向量容器：每元素为 uoffset 指向嵌套表（harmony NStructArray&lt;T&gt;）。</summary>
public unsafe struct NStructArray<T> : IEnumerable<T> where T : struct, IConfigStruct
{
    private byte* _elements;
    private readonly int _len;
    private readonly int _pVersion;

    public NStructArray(IntPtr obj, int slot, int pVersion)
    {
        byte* v = (byte*)WireReader.Indirect(obj, slot);
        _len = v == null ? 0 : *(int*)v;
        _elements = v == null ? null : v + 4;
        _pVersion = pVersion;
    }

    public int Length => _len;

    public T this[int index]
    {
        get
        {
            if (_elements == null) return default;
#if CONFIG_DEBUG
            TableVersion.Check(_pVersion);
            if ((uint)index >= (uint)_len) throw new IndexOutOfRangeException();
#endif
            byte* elt = _elements + (long)index * 4;
            byte* rec = elt + *(int*)elt; // uoffset 相对自身
            var t = default(T);
            t.SetPointer(rec, _pVersion);
            return t;
        }
    }

    public IEnumerator<T> GetEnumerator() { for (int i = 0; i < _len; i++) yield return this[i]; }
    IEnumerator IEnumerable.GetEnumerator() { for (int i = 0; i < _len; i++) yield return this[i]; }
}

/// <summary>FlatBuffers 字符串视图（4 字节长度前缀）：解码经由 NStringCache 驻留。</summary>
public unsafe struct NString : IConfigStruct
{
    private byte* _ptr;
    private int _pVersion;
    public NString(byte* ptr, int pVersion) { _ptr = ptr; _pVersion = pVersion; }
    public void SetPointer(byte* p, int pVersion) { _ptr = p; _pVersion = pVersion; }
    public int Length => _ptr == null ? 0 : *(int*)_ptr;
    public override string ToString()
    {
        TableVersion.Check(_pVersion); // 与 harmony 一致：访问字符串前先做版本检查（Release 条件编译掉）
        return NStringCache.Get(_ptr, _pVersion);
    }
    public static implicit operator string(NString ns) => ns.ToString();
}

/// <summary>
/// 字符串驻留：按字符串数据指针缓存解码结果，避免重复 UTF-8 解码。
/// 版本（整套 bin 世代）变化时【无条件清空】，既防“地址复用返回陈旧字符串”，也防无限增长。
/// 清缓存只在加载/重载/切语言/销毁整套时发生，不属于热路径。
/// </summary>
public static unsafe class NStringCache
{
    private static readonly Dictionary<nint, string> _cache = new Dictionary<nint, string>();
    private static int _lastVersion = -1;

    public static string Get(byte* ptr, int pVersion)
    {
        if (ptr == null) return null;
        if (pVersion != _lastVersion) { _cache.Clear(); _lastVersion = pVersion; }
        nint key = (nint)ptr;
        if (_cache.TryGetValue(key, out var s)) return s;
        int len = *(int*)ptr;
        s = Encoding.UTF8.GetString(ptr + 4, len);
        _cache[key] = s;
        return s;
    }
}

/// <summary>
/// 表级运行时 registry：按表名注册已加载的 ConfigTable，供生成的 accessor 查询。
/// 生命周期：先用 ConfigReader.LoadBundle 一次性加载整套 bin（版本前进一次），再 Register；
/// 覆盖同名表（重载）时释放旧句柄。独立于 Unity/游戏。
/// </summary>
public static unsafe class Runtime
{
    private static readonly Dictionary<string, ConfigTable> _tables = new Dictionary<string, ConfigTable>();

    public static void Register(ConfigTable table)
    {
        if (_tables.TryGetValue(table.Name, out var old)) old?.Dispose();
        _tables[table.Name] = table;
    }

    public static void Clear()
    {
        foreach (var t in _tables.Values) t.Dispose();
        _tables.Clear();
    }

    public static int Count(string tableName) => _tables[tableName].Count;
    public static IntPtr ByID(string tableName, int id) => _tables[tableName].ByID(id);
    public static IntPtr RowAt(string tableName, int index) => _tables[tableName].RowAt(index);
    public static int Version(string tableName) => _tables[tableName].Version;

    // 可选 Code/Group 索引（生成器仅在配置索引时调用）
    public static int ByCode(string tableName, int slot, string code) => -1;
    public static int[] GroupKey(string tableName, int slot, int value) => Array.Empty<int>();
}
