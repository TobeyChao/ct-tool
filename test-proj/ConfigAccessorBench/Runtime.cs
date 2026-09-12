using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using System.Threading;

// NOTE: 本 reader 只面向【可信、工具生成、不可变】的 FlatBuffers 配置数据。
// Release（未定义 CONFIG_DEBUG）下，逐元素的版本/越界检查被编译掉（参考实现 LH_DEBUG 同款），
// 以获得 VecBase 直读的性能；调用方必须传合法下标，且只使用“当前已加载这套 bin”里的句柄。
// 仅 `_base == null`（缺失字段）做无条件安全兜底。若喂脏数据/损坏 bundle，属未定义行为。
// 并发契约：只支持【只读并发】——多线程可同时读；世代推进（LoadBundle 加载 / Clear 销毁整套）
// 只允许发生在整套边界，不得与读取并发。bin 为原子单元，无“部分更新/单表重载”语义：
// 单表重载（不经 LoadBundle）不受支持、不失效旧句柄与驻留缓存。

/// <summary>read-only 回调式 struct 读取协议（对齐 参考实现 IConfigStruct）。</summary>
public interface IConfigStruct
{
    unsafe void SetPointer(byte* p, int pVersion);
}

/// <summary>版本守卫：整套已加载配置（bin）的世代号。只在整套边界（LoadBundle/Clear）Bump；读侧 Volatile 可见。</summary>
public static unsafe class TableVersion
{
    private static int _version;
    private static int _i18nVersion;

    /// <summary>整套 bin 的世代：LoadBundle / Clear 时前进，**所有**行句柄失效。</summary>
    public static int Current => Volatile.Read(ref _version);
    public static int Bump() => Interlocked.Increment(ref _version);

    /// <summary>
    /// i18n 表的世代：**只**在切换语言（换 i18n 包）时前进。
    /// 这样切语言只失效多语言表的 accessor 缓存，**主表行句柄继续有效** ——
    /// 这是「切语言不重读 main」这条设计的运行时契约。
    /// </summary>
    public static int I18nCurrent => Volatile.Read(ref _i18nVersion);
    public static int BumpI18n() => Interlocked.Increment(ref _i18nVersion);

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

/// <summary>FlatBuffers 标量向量容器：一次 Indirect 拿基址+长度，[i] 直读（B-2b / 参考实现 NArray&lt;T&gt;）。</summary>
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

    /// <summary>已解析字段偏移的快速构造：v 为向量长度前缀地址（obj+off 处解引用后）。</summary>
    public NArray(byte* v, int pVersion)
    {
        _len = v == null ? 0 : *(int*)v;
        _base = v == null ? null : v + 4;
        _pVersion = pVersion;
    }

    public int Length => _len;

    public T this[int index]
    {
        get
        {
            // 空值兜底只在构造期做（_len == 0 → 调用方不会进入循环）。
            // 索引器内保留无条件分支会阻断 JIT 对 sum 循环的自动向量化（实测约 2×）。
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

/// <summary>FlatBuffers 结构体/嵌套表向量容器：每元素为 uoffset 指向嵌套表（参考实现 NStructArray&lt;T&gt;）。</summary>
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

    /// <summary>已解析字段偏移的快速构造：v 为向量长度前缀地址。</summary>
    public NStructArray(byte* v, int pVersion)
    {
        _len = v == null ? 0 : *(int*)v;
        _elements = v == null ? null : v + 4;
        _pVersion = pVersion;
    }

    public int Length => _len;

    public T this[int index]
    {
        get
        {
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
        TableVersion.Check(_pVersion); // 与 参考实现 一致：访问字符串前先做版本检查（Release 条件编译掉）
        return NStringCache.Get(_ptr, _pVersion);
    }
    public static implicit operator string(NString ns) => ns.ToString();
}

/// <summary>
/// 字符串驻留：按字符串数据指针缓存解码结果，避免重复 UTF-8 解码。
/// 版本（整套 bin 世代）变化时【无条件清空】，既防“地址复用返回陈旧字符串”，也防无限增长。
/// 只读并发安全：多线程可同时读；清缓存（ConcurrentDictionary.Clear）只发生在整套边界，不与读并发。
/// </summary>
public static unsafe class NStringCache
{
    // 冷路径（首次扫过 N 个不同字符串）用普通 Dictionary + 仅在 miss 时加锁。
    // 原实现用 ConcurrentDictionary.GetOrAdd：默认并发级别 = 4*CPU，6685 次插入要跨几十个
    // 锁/桶反复 rehash，实测冷扫 208 ns/行 vs 参考实现 40 ns/行。
    // 并发契约不变：多线程可同时读；缓存整体替换只发生在整套 bin 换代边界。
    private static Dictionary<nint, string> _cache = new Dictionary<nint, string>();
    private static readonly object _gate = new object();
    private static int _lastVersion = -1;

    /// <summary>直接解码，不走全局字典。per-field 行下标缓存的解码入口。</summary>
    public static string Decode(byte* ptr)
    {
        if (ptr == null) return null;
        return Encoding.UTF8.GetString(ptr + 4, *(int*)ptr);
    }

    public static string Get(byte* ptr, int pVersion)
    {
        if (ptr == null) return null;
        if (Volatile.Read(ref _lastVersion) != pVersion)
        {
            lock (_gate)
            {
                _cache = new Dictionary<nint, string>(1024);
                Volatile.Write(ref _lastVersion, pVersion);
            }
        }
        Dictionary<nint, string> cache = _cache;
        nint key = (nint)ptr;
        if (cache.TryGetValue(key, out string cached)) return cached;
        int len = *(int*)ptr;
        string s = Encoding.UTF8.GetString(ptr + 4, len);
        lock (_gate) { cache[key] = s; }
        return s;
    }
}

/// <summary>
/// 表级运行时 registry：按表名注册已加载的 ConfigTable，供生成的 accessor 查询。
/// 生命周期：先用 ConfigReader.LoadBundle 一次性加载整套 bin（世代前进一次），再 Register 全部；
/// 覆盖同名表时释放旧句柄（不推进世代）；整套销毁走 Clear（释放全部 + 世代前进一次）。
/// 只读并发：多线程可同时查询；Register/Clear 只发生在整套边界，不与读取并发。独立于 Unity/游戏。
/// </summary>
public static unsafe class Runtime
{
    private static readonly Dictionary<string, ConfigTable> _tables = new Dictionary<string, ConfigTable>();

    /// <summary>
    /// 注册一张**稀疏 i18n 表**并前进 i18n 世代（切语言）。
    /// 与 Register 的区别：不动全局世代，主表行句柄与主表 accessor 缓存全部保留。
    /// </summary>
    public static void RegisterI18n(ConfigTable table)
    {
        if (_tables.TryGetValue(table.Name, out var old)) old?.Dispose();
        _tables[table.Name] = table;
        TableVersion.BumpI18n();
    }

    public static void Register(ConfigTable table)
    {
        // 只替换句柄并释放旧 pin；世代由整套边界（LoadBundle/Clear）负责，此处不 Bump
        if (_tables.TryGetValue(table.Name, out var old)) old?.Dispose();
        _tables[table.Name] = table;
    }

    public static void Clear()
    {
        foreach (var t in _tables.Values) t.Dispose();
        _tables.Clear();
        TableVersion.Bump(); // 整套销毁 → 世代前进一次 → 任何残留旧句柄失效（Debug 守卫触发）
    }

    public static int Count(string tableName) => _tables[tableName].Count;
    public static IntPtr ByID(string tableName, int id) => _tables[tableName].ByID(id);
    public static IntPtr RowAt(string tableName, int index) => _tables[tableName].RowAt(index);
    public static int Version(string tableName) => _tables[tableName].Version;

    /// <summary>取表句柄。生成代码应在 accessor 内缓存该结果，避免每次调用都查字符串字典。</summary>
    public static ConfigTable Table(string tableName) => _tables[tableName];

    /// <summary>
    /// 取表句柄，不存在返回 null。
    /// 稀疏 i18n 表（``Item_i18n``）只在加载了对应语言包时存在，读多语言字段必须先问它有没有。
    /// </summary>
    public static ConfigTable TryTable(string tableName) =>
        _tables.TryGetValue(tableName, out var table) ? table : null;

    // 可选 CodeName 索引（生成器仅在表声明了 indexes 时调用）
    /// <summary>按 CodeName 精确查找，返回行下标；未找到返回 -1。slot = 客户端字段序（0-based）。</summary>
    public static int ByCodeName(string tableName, int slot, string codeName) =>
        _tables[tableName].CodeNameSearch(slot, codeName);
}
