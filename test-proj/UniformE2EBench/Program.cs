// 定宽布局（uniform）值多少：ct-only 端到端测量。
//
// 对比同一张表、同一份数据的两种读取形态：
//   ① 偏移表版（OPT-1）：行句柄带 _off[]，构造时调 ConfigTable.OffsetsFor()
//   ② 字面量版（uniform）：行句柄只有 (row, version)，字段读 = *(T*)(row + 常量)
//
// 分层量：Raw（只拿 IntPtr，不含行句柄）→ Row（构造行句柄）→ E2E（再读字段），
// 这样能把 ConfigTable.OffsetsFor() 的成本单独暴露出来。
//
// 两张基准表：
//   ItemBench —— patch 的基准（15 字段 / 16 种 vtable），与本项目形状**不同**，会高估收益
//   OurItem   —— 本项目真实 Item 形状（7 字段含枚举 / 2 种 vtable / 填充率 92.9%）
//
// 用法： UniformE2EBench [iters] [reps]
using System;
using System.Diagnostics;
using System.Runtime.CompilerServices;

public static class Program
{
    private static int[] _ids = Array.Empty<int>();
    private static readonly int[] _idx = new int[65536];

    private static readonly string[] Labels =
    {
        "Raw:   ByID 只拿 IntPtr（无行句柄）",
        "Row:   ByID + 构造行句柄",
        "E2E:   ByID + 3 字段",
        "Row:   ByIndex + 构造行句柄",
        "E2E:   ByIndex + 6 字段",
        "Row:   ByID + 行句柄（偏移表只解析一次）",
        "E2E:   ByID + 3 字段（偏移表只解析一次）",
    };

    public static int Main(string[] args)
    {
        int iters = args.Length > 0 ? int.Parse(args[0]) : 3_000_000;
        int reps = args.Length > 1 ? int.Parse(args[1]) : 5;
        string root = AppContext.BaseDirectory;

        Console.WriteLine($"== 定宽布局端到端对比（iters={iters:N0}, best of {reps}, 预热 + 交替） ==\n");

        var ibN = File(root, "ItemBench.bundle.bin");
        var ibU = File(root, "ItemBenchUniform.bundle.bin");
        double[] n = new double[Labels.Length], u = new double[Labels.Length];
        Init(n); Init(u);
        Measure(ibN, ibU, iters, reps, n, u, ItemBenchRound, ItemBenchLiteralRound);
        Report("ItemBench（patch 基准：15 字段 / 16 种 vtable）", ibN, ibU, n, u, iters);

        var oiN = File(root, "OurItem.bundle.bin");
        var oiU = File(root, "OurItemUniform.bundle.bin");
        n = new double[Labels.Length]; u = new double[Labels.Length];
        Init(n); Init(u);
        Measure(oiN, oiU, iters, reps, n, u, OurItemRound, OurItemLiteralRound);
        Report("OurItem（本项目真实形状：7 字段含枚举 / 2 vtable / 填充率 92.9%）", oiN, oiU, n, u, iters);

        return 0;
    }

    private static byte[] File(string root, string name) =>
        System.IO.File.ReadAllBytes(System.IO.Path.Combine(root, "fixtures", name));

    private static void Init(double[] a) { for (int i = 0; i < a.Length; i++) a[i] = double.MaxValue; }

    private static void Measure(byte[] normalBundle, byte[] uniformBundle, int iters, int reps,
                                double[] nb, double[] ub,
                                Action<int, double[]> normalRound, Action<int, double[]> uniformRound)
    {
        Prepare(normalBundle); normalRound(iters, null);     // 预热两侧
        Prepare(uniformBundle); uniformRound(iters, null);

        for (int r = 0; r < reps; r++)
        {
            if (r % 2 == 0)
            {
                Prepare(normalBundle); normalRound(iters, nb);
                Prepare(uniformBundle); uniformRound(iters, ub);
            }
            else
            {
                Prepare(uniformBundle); uniformRound(iters, ub);
                Prepare(normalBundle); normalRound(iters, nb);
            }
        }
    }

    private static void Report(string title, byte[] nb0, byte[] ub0, double[] nb, double[] ub, int iters)
    {
        Console.WriteLine(new string('=', 82));
        Console.WriteLine(title);
        Console.WriteLine($"  非定宽 {nb0.Length,10:N0} B     定宽 {ub0.Length,10:N0} B"
                          + $"     膨胀 {ub0.Length / (double)nb0.Length:F3}x");
        Console.WriteLine(new string('=', 82));
        Console.WriteLine($"  {"场景",-34}{"偏移表",12}{"字面量",12}{"倍数",9}{"每次省下",13}");
        Console.WriteLine("  " + new string('-', 80));
        for (int i = 0; i < Labels.Length; i++)
        {
            double a = nb[i] * 1e6 / iters, b = ub[i] * 1e6 / iters;
            Console.WriteLine($"  {Labels[i],-34}{a,10:F2}ns{b,10:F2}ns{b / a,9:F3}{(a - b),10:F2} ns");
        }
        Console.WriteLine();
    }

    // ---------------------------------------------------------------- ItemBench
    private static void ItemBenchRound(int iters, double[] best)
    {
        var t = Runtime.Table("ItemBench");
        Rec(0, Run(() => { long s = 0; for (int k = 0; k < iters; k++) s += t.ByID(_ids[_idx[k & 65535]]).ToInt64() & 1; return s; }), best);
        Rec(1, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = ItemBenchAccessor.ByID(_ids[_idx[k & 65535]]); if (r.HasValue) s += 1; } return s; }), best);
        Rec(2, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = ItemBenchAccessor.ByID(_ids[_idx[k & 65535]]); if (r.HasValue) { var v = r.Value; s += v.Id + v.Type + v.Quality; } } return s; }), best);
        Rec(3, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = ItemBenchAccessor.ByIndex(_idx[k & 65535] % 6685); if (r.HasValue) s += 1; } return s; }), best);
        Rec(4, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = ItemBenchAccessor.ByIndex(_idx[k & 65535] % 6685); if (r.HasValue) { var v = r.Value; s += v.Id + v.Type + v.Quality + v.IconRes + v.PileCount + v.SellPrice; } } return s; }), best);
        Rec(5, Run(() => { long s = 0; var ft = t.RowAt(0); int[] c = t.OffsetsFor(ft, 34); for (int k = 0; k < iters; k++) { var p2 = t.ByID(_ids[_idx[k & 65535]], out int ix); if (p2 != IntPtr.Zero) { var v = new ItemBenchRow(p2, c, t.Version, ix); s += 1; } } return s; }), best);
        Rec(6, Run(() => { long s = 0; var ft = t.RowAt(0); int[] c = t.OffsetsFor(ft, 34); for (int k = 0; k < iters; k++) { var p2 = t.ByID(_ids[_idx[k & 65535]], out int ix); if (p2 != IntPtr.Zero) { var v = new ItemBenchRow(p2, c, t.Version, ix); s += v.Id + v.Type + v.Quality; } } return s; }), best);
    }

    private static void ItemBenchLiteralRound(int iters, double[] best)
    {
        Rec(0, Run(() => { long s = 0; var t = Runtime.Table("ItemBench"); for (int k = 0; k < iters; k++) s += t.ByID(_ids[_idx[k & 65535]]).ToInt64() & 1; return s; }), best);
        Rec(1, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = ItemBenchLiteralAccessor.ByID(_ids[_idx[k & 65535]]); if (r.HasValue) s += 1; } return s; }), best);
        Rec(2, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = ItemBenchLiteralAccessor.ByID(_ids[_idx[k & 65535]]); if (r.HasValue) { var v = r.Value; s += v.Id + v.Type + v.Quality; } } return s; }), best);
        Rec(3, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = ItemBenchLiteralAccessor.ByIndex(_idx[k & 65535] % 6685); if (r.HasValue) s += 1; } return s; }), best);
        Rec(4, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = ItemBenchLiteralAccessor.ByIndex(_idx[k & 65535] % 6685); if (r.HasValue) { var v = r.Value; s += v.Id + v.Type + v.Quality + v.IconRes + v.PileCount + v.SellPrice; } } return s; }), best);
        Rec(5, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = ItemBenchLiteralAccessor.ByID(_ids[_idx[k & 65535]]); if (r.HasValue) s += 1; } return s; }), best);
        Rec(6, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = ItemBenchLiteralAccessor.ByID(_ids[_idx[k & 65535]]); if (r.HasValue) { var v = r.Value; s += v.Id + v.Type + v.Quality; } } return s; }), best);
    }

    // ------------------------------------------------------------------ OurItem
    private static void OurItemRound(int iters, double[] best)
    {
        var t = Runtime.Table("OurItem");
        Rec(0, Run(() => { long s = 0; for (int k = 0; k < iters; k++) s += t.ByID(_ids[_idx[k & 65535]]).ToInt64() & 1; return s; }), best);
        Rec(1, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = OurItemAccessor.ByID(_ids[_idx[k & 65535]]); if (r.HasValue) s += 1; } return s; }), best);
        Rec(2, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = OurItemAccessor.ByID(_ids[_idx[k & 65535]]); if (r.HasValue) { var v = r.Value; s += v.Id + (int)v.Rarity + v.ItemTypeId; } } return s; }), best);
        Rec(3, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = OurItemAccessor.ByIndex(_idx[k & 65535] % 6685); if (r.HasValue) s += 1; } return s; }), best);
        Rec(4, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = OurItemAccessor.ByIndex(_idx[k & 65535] % 6685); if (r.HasValue) { var v = r.Value; s += v.Id + (int)v.Rarity + v.ItemTypeId + (int)v.Price + v.Tags.Length; } } return s; }), best);
        // 对照：偏移表只解析一次（OurItem 真实 MaxSlot = 4 + 2*7 = 18）
        var ft0 = t.RowAt(0);
        int[] c0 = t.OffsetsFor(ft0, 18);
        Rec(5, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var p2 = t.ByID(_ids[_idx[k & 65535]], out int ix); if (p2 != IntPtr.Zero) { var v = new OurItemRow(p2, c0, t.Version, ix); s += 1; } } return s; }), best);
        Rec(6, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var p2 = t.ByID(_ids[_idx[k & 65535]], out int ix); if (p2 != IntPtr.Zero) { var v = new OurItemRow(p2, c0, t.Version, ix); s += v.Id + (int)v.Rarity + v.ItemTypeId; } } return s; }), best);
    }

    private static void OurItemLiteralRound(int iters, double[] best)
    {
        Rec(0, Run(() => { long s = 0; var t = Runtime.Table("OurItem"); for (int k = 0; k < iters; k++) s += t.ByID(_ids[_idx[k & 65535]]).ToInt64() & 1; return s; }), best);
        Rec(1, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = OurItemLiteralAccessor.ByID(_ids[_idx[k & 65535]]); if (r.HasValue) s += 1; } return s; }), best);
        Rec(2, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = OurItemLiteralAccessor.ByID(_ids[_idx[k & 65535]]); if (r.HasValue) { var v = r.Value; s += v.Id + (int)v.Rarity + v.ItemTypeId; } } return s; }), best);
        Rec(3, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = OurItemLiteralAccessor.ByIndex(_idx[k & 65535] % 6685); if (r.HasValue) s += 1; } return s; }), best);
        Rec(4, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = OurItemLiteralAccessor.ByIndex(_idx[k & 65535] % 6685); if (r.HasValue) { var v = r.Value; s += v.Id + (int)v.Rarity + v.ItemTypeId + (int)v.Price + v.Tags.Length; } } return s; }), best);
        Rec(5, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = OurItemLiteralAccessor.ByID(_ids[_idx[k & 65535]]); if (r.HasValue) s += 1; } return s; }), best);
        Rec(6, Run(() => { long s = 0; for (int k = 0; k < iters; k++) { var r = OurItemLiteralAccessor.ByID(_ids[_idx[k & 65535]]); if (r.HasValue) { var v = r.Value; s += v.Id + (int)v.Rarity + v.ItemTypeId; } } return s; }), best);
    }

    // ------------------------------------------------------------------- 工具
    private static void Prepare(byte[] bundle)
    {
        var tables = ConfigReader.LoadBundle(bundle);
        foreach (var t in tables) Runtime.Register(t);
        var t0 = tables[0];
        int n = Math.Min(4096, t0.Count);
        var arr = new int[n];
        int j = 0;
        for (int i = 0; i < n; i++)
        {
            var row = t0.RowAt((int)((long)i * t0.Count / n));
            if (row == IntPtr.Zero) continue;
            arr[j++] = WireReader.I32(row, 4);      // slot 0 = 主键
        }
        var outArr = new int[j];
        Array.Copy(arr, outArr, j);
        _ids = outArr;
        for (int i = 0; i < _idx.Length; i++) _idx[i] = i % _ids.Length;
    }

    private static void Rec(int i, double ms, double[] best) { if (best != null) best[i] = Math.Min(best[i], ms); }

    private static double Run(Func<long> body)
    {
        var sw = Stopwatch.StartNew();
        long sink = body();
        sw.Stop();
        GC.KeepAlive(sink);
        return sw.Elapsed.TotalMilliseconds;
    }
}
