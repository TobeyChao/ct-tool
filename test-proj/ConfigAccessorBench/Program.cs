using System;
using System.Diagnostics;
using System.Collections.Generic;
using System.IO;

/// <summary>
/// 独立 reader runtime 演示 + 基准（对照 harmony 读取模型）。
/// 读 ct 导出的 DataBundle（或单表 .bin），用指针式 reader + 容器 + 字符串驻留 + 版本守卫，
/// 全程不依赖 Unity/游戏，可在本工程独立运行。
/// </summary>
public static unsafe class Program
{
    // Item 表 vtable 槽位 = 4 + 2*字段序
    const int ID_SLOT = 4, NAME_SLOT = 6, PRICE_SLOT = 8, RARITY_SLOT = 10, ITEMTYPE_SLOT = 12, DROPRANGE_SLOT = 14, TAGS_SLOT = 16;

    public static void Main(string[] args)
    {
        string arg0 = args.Length > 0 ? args[0] : "Item";
        int iters = args.Length > 1 ? int.Parse(args[1]) : 200_000;
        string bundlePath = FindBundle();
        byte[] bundle = File.ReadAllBytes(bundlePath);

        // 注册所有表到 Runtime，供生成的 accessor（*Accessor.g.cs）查询
        var all = LoadAllTables(bundle);
        foreach (var t in all) Runtime.Register(t);
        ConfigTable table = all.Find(x => x.Name == arg0) ?? (arg0.EndsWith(".bin", StringComparison.OrdinalIgnoreCase)
            ? new ConfigTable(Path.GetFileNameWithoutExtension(arg0), File.ReadAllBytes(arg0))
            : ConfigReader.LoadTable(bundle, arg0));
        if (!all.Contains(table)) Runtime.Register(table);

        Console.WriteLine($"bundle={Path.GetFileName(bundlePath)}  table={table.Name}  rows={table.Count}  version={table.Version}");
        Console.WriteLine("(独立运行：纯 C# + unsafe 读 FlatBuffers，未引用 Unity/游戏)");

        RunCorrectness(table);
        Console.WriteLine();
        RunGeneratedAccessorSmoke(table);
        Console.WriteLine();
        RunBenchmark(table, iters);
        Console.WriteLine();
        RunVersionGuard(table);

        Runtime.Clear(); // 整套拆包：释放全部已注册句柄 + 世代前进一次
    }

    static List<ConfigTable> LoadAllTables(byte[] bundle) => ConfigReader.LoadBundle(bundle);

    // 生成 accessor（*Accessor.g.cs）冒烟：通过 Runtime 走 ItemAccessor.ByID 等
    static void RunGeneratedAccessorSmoke(ConfigTable t)
    {
        var item = ItemAccessor.ByID(1);
        if (!item.HasValue) { Console.WriteLine("[gen-accessor] ByID(1) miss"); return; }
        var row = item.Value;
        Console.WriteLine($"[gen-accessor] ByID(1): Id={row.Id} Name={row.Name} Price={row.Price} Rarity={row.Rarity} Tags0={row.Tags[0]} DropRange.Min={row.DropRange.Min} ItemType.Id={row.ItemType.Value.Id}");
    }

    // ---- 正确性演示：Count / ByID / ByIndex / 指针式字段 / 向量 / 字符串驻留 / 版本守卫 ----
    static void RunCorrectness(ConfigTable t)
    {
        int rows = t.Count;

        // 1) ByID / ByIndex
        IntPtr r0 = t.ByID(1);
        IntPtr ri = t.RowAt(0);
        Console.WriteLine($"ByID(1)=0x{R0(r0)}  RowAt(0)=0x{R0(ri)}  same={r0 == ri}");

        // 2) 指针式字段读取
        int id = WireReader.I32(r0, ID_SLOT);
        var nameStr = new NString((byte*)WireReader.Indirect(r0, NAME_SLOT), t.Version);
        float price = WireReader.F32(r0, PRICE_SLOT);
        byte rarity = WireReader.I8(r0, RARITY_SLOT);
        Console.WriteLine($"row: Id={id} Name={nameStr} Price={price} Rarity={rarity}");

        // 3) 跨表 ref（裸 id 快路径）
        int itemTypeId = WireReader.I32(r0, ITEMTYPE_SLOT);
        Console.WriteLine($"ref ItemTypeId={itemTypeId} (raw)");

        // 4) 嵌套 record -> 子行指针 + 读字段
        byte* drop = (byte*)WireReader.Indirect(r0, DROPRANGE_SLOT);
        int min = drop == null ? 0 : WireReader.I32((IntPtr)drop, 4); // DropRange.Min slot 4
        Console.WriteLine($"nested DropRange.Min={min}");

        // 5) 向量 -> NArray<int>（一次 VecBase，[i] 直读）
        var tags = new NArray<int>(r0, TAGS_SLOT, t.Version);
        Console.Write($"vector Tags: n={tags.Length} [");
        for (int i = 0; i < tags.Length; i++) Console.Write((i > 0 ? "," : "") + tags[i]);
        Console.WriteLine("]");

        // 6) 字符串驻留：同一行同一字段两次解码 -> 同一引用
        string a = new NString((byte*)WireReader.Indirect(r0, NAME_SLOT), t.Version);
        string b = new NString((byte*)WireReader.Indirect(r0, NAME_SLOT), t.Version);
        Console.WriteLine($"string interning: same reference={ReferenceEquals(a, b)}  value='{a}'");

    }

    // ---- 性能：before（Count+At 每元素重解析基址） vs after（NArray 捕获基址直读）----
    static void RunBenchmark(ConfigTable t, int iters)
    {
        int rows = t.Count;
        long sink = 0;
        int warm = Math.Min(2000, iters);

        for (int i = 0; i < warm; i++) { sink += SumBefore(t, rows); sink += SumAfter(t, rows); }

        var sw = Stopwatch.StartNew();
        for (int i = 0; i < iters; i++) sink += SumBefore(t, rows);
        double before = sw.Elapsed.TotalMilliseconds;

        sw.Restart();
        for (int i = 0; i < iters; i++) sink += SumAfter(t, rows);
        double after = sw.Elapsed.TotalMilliseconds;

        Console.WriteLine();
        Console.WriteLine($"iters={iters} (每轮读 {rows} 行)");
        Console.WriteLine($"before   (Count+At, 每元素重复解析基址): {before,8:F1} ms");
        Console.WriteLine($"after    (NArray 捕获基址直读)          : {after,8:F1} ms");
        Console.WriteLine($"ratio    after/before = {after / before,6:F3}   (<1 更快)");
        Console.WriteLine($"sink={sink} (防优化)");
    }

    static long SumBefore(ConfigTable t, int rows)
    {
        long sum = 0;
        for (int r = 0; r < rows; r++)
        {
            IntPtr row = t.RowAt(r);
            int n = WireReader.ArrLen(row, TAGS_SLOT);
            for (int i = 0; i < n; i++) sum += WireReader.ArrI32(row, TAGS_SLOT, i);
        }
        return sum;
    }

    static long SumAfter(ConfigTable t, int rows)
    {
        long sum = 0;
        for (int r = 0; r < rows; r++)
        {
            IntPtr row = t.RowAt(r);
            var arr = new NArray<int>(row, TAGS_SLOT, t.Version);
            for (int i = 0; i < arr.Length; i++) sum += arr[i];
        }
        return sum;
    }

    // 版本守卫演示：表“重载/切语言”后（Bump），旧的 NArray 句柄访问应被拦截
    static void RunVersionGuard(ConfigTable t)
    {
        IntPtr row = t.RowAt(0);
        var stale = new NArray<int>(row, TAGS_SLOT, t.Version);
        Console.WriteLine($"before Bump: tags[0]={stale[0]} (version {t.Version})");
        TableVersion.Bump();
        try { TableVersion.AssertFresh(t.Version); Console.WriteLine("version guard: NOT triggered (bug)"); }
        catch (InvalidOperationException) { Console.WriteLine("after Bump: stale access blocked OK  (切语言/重载后旧指针失效)"); }
    }

    static string FindBundle()
    {
        foreach (string c in new[] { "data_zh.bin", "gd/output/binary/data_zh.bin", "../../../gd/output/binary/data_zh.bin" })
            if (File.Exists(c)) return Path.GetFullPath(c);
        var dir = new DirectoryInfo(Environment.CurrentDirectory);
        while (dir != null)
        {
            string cand = Path.Combine(dir.FullName, "gd", "output", "binary", "data_zh.bin");
            if (File.Exists(cand)) return cand;
            dir = dir.Parent;
        }
        throw new FileNotFoundException("找不到 data_zh.bin，请先 ct export 生成产物");
    }

    static string R0(IntPtr p) => ((long)p).ToString("x");
}
