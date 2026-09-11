using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

public static unsafe class Program
{
    private const string RefDll =
        @"D:\dev_trunk_ref\client\Assets\Plugins\x86_64\xlua.dll";

    private const string ConfigDataDir =
        @"D:\dev_trunk_ref\client\Assets\Data\ConfigData\";

    public static int Main(string[] args)
    {
        string mode = args.Length > 0 ? args[0] : "probe";

        // 预加载原生插件：Windows 加载器按基名复用已加载模块，后续 DllImport("xlua") 直接命中。
        NativeLibrary.Load(RefDll);

        return mode switch
        {
            "probe" => Probe(),
            "dump" => Dump(),
            "dump-tables" => DumpTables(),
            "bench" => Bench.Run(args),
            "load" => LoadBench.Run(args),
            "verify" => Verify.Run(args),
            _ => Fail($"unknown mode {mode}"),
        };
    }

    /// <summary>读真实 Item 行，验证 _Data 布局 / dataPointer 偏移语义 / NString / NArray / NStructArray 解码正确。</summary>
    private static int Dump()
    {
        RefNative.SetUseDecryptProcess(false);
        IntPtr err = RefNative.TableInit(ConfigDataDir, ConfigDataDir);
        if (err != IntPtr.Zero) return Fail("TableInit: " + Marshal.PtrToStringAnsi(err));

        int idx = RefConfig.TableIndex("Item");
        int count = RefConfig.Count(idx);
        Console.WriteLine($"[dump] Item tableIndex={idx} rows={count} lang={RefNative.GetLang()}");

        int[] probe = { 0, 1, 2, 100, 1000, count - 1 };
        foreach (int i in probe)
        {
            byte* dpi;
            byte* pi = RefConfig.ByIndex(idx, i, out dpi);
            if (pi == null) { Console.WriteLine($"[dump] ByIndex({i}) -> NULL"); continue; }
            var ri = *(RefRows.ItemData*)pi;

            byte* dp;
            byte* p = RefConfig.ByID(idx, ri.id, out dp);
            if (p == null) { Console.WriteLine($"[dump] ByID({ri.id}) -> NULL"); continue; }
            var row = *(RefRows.ItemData*)p;
            string designName = RefRows.ReadNString(dp + row.designName);
            string descr = RefRows.ReadNString(dp + row.description);
            string bpDescr = RefRows.ReadNString(dp + row.bp_description);
            Console.WriteLine(
                $"[dump] ix={i,-6} id={row.id,-10} type={row.type,-4} quality={row.quality,-4} iconRes={row.iconRes,-8} " +
                $"pile={row.pileCount,-6} sell={row.sellPrice,-8} pc={row.priceChecker:F4} " +
                $"isPut={row.isPut} hide={row.hideInPackage} strParamsOff={row.stringParams}");
            Console.WriteLine($"         designName = \"{designName}\" (len={designName?.Length ?? 0})");
            Console.WriteLine($"         descr      = \"{Trunc(descr)}\" (len={descr?.Length ?? 0})");
            Console.WriteLine($"         bp_descr   = \"{Trunc(bpDescr)}\" (len={bpDescr?.Length ?? 0})");
        }

        // 行指针是否落在连续数组里（ByIndex vs ByID 一致性）
        byte* dp0;
        byte* p0 = RefConfig.ByIndex(idx, 0, out dp0);
        byte* dp1;
        byte* p1 = RefConfig.ByIndex(idx, 1, out dp1);
        Console.WriteLine($"[dump] ByIndex(0)={((ulong)p0):X} ByIndex(1)={((ulong)p1):X} " +
                          $"stride={(long)p1 - (long)p0} dp0==dp1: {dp0 == dp1} dataPointer={((ulong)dp0):X}");

        // 表数据池大小（最后一行的行指针 - 首行行指针 只能给出近似）
        Console.WriteLine($"[dump] row0.id={((RefRows.ItemData*)p0)->id} row1.id={((RefRows.ItemData*)p1)->id}");
        Console.WriteLine($"[dump] sizeof(ItemData)={sizeof(RefRows.ItemData)} (36 x 4 = 144)");

        IntPtr dataPtr = RefNative.GetConfigDataPointer(idx);
        Console.WriteLine($"[dump] GetConfigDataPointer(idx)={((ulong)dataPtr):X} (== dp? {dataPtr == (IntPtr)dp0})");
        return 0;
    }

    /// <summary>导出全部可解析表的 name/index/rows，供基准场景选表。</summary>
    private static int DumpTables()
    {
        RefNative.SetUseDecryptProcess(false);
        IntPtr err = RefNative.TableInit(ConfigDataDir, ConfigDataDir);
        if (err != IntPtr.Zero) return Fail("TableInit: " + Marshal.PtrToStringAnsi(err));

        var sb = new StringBuilder();
        sb.Append("{\n");
        bool first = true;
        foreach (var n in LoadKlassNames())
        {
            int idx = RefConfig.TableIndex(n);
            if (idx == 0) continue;
            if (!first) sb.Append(",\n");
            first = false;
            sb.Append($"  \"{n}\": {{\"index\": {idx}, \"rows\": {RefConfig.Count(idx)}}}");
        }
        sb.Append("\n}\n");
        File.WriteAllText("ref_tables.json", sb.ToString(), new UTF8Encoding(false));
        Console.WriteLine("[dump-tables] wrote ref_tables.json");
        return 0;
    }

    private static string Trunc(string s) => s == null ? "<null>" : (s.Length > 40 ? s.Substring(0, 40) + "..." : s);

    private static int Fail(string msg)
    {
        Console.Error.WriteLine(msg);
        return 2;
    }

    private static int Probe()
    {
        Console.WriteLine($"[probe] dll      = {RefDll}");
        Console.WriteLine($"[probe] tableDir = {ConfigDataDir}");
        Console.WriteLine($"[probe] files    = {string.Join(", ", Directory.GetFiles(ConfigDataDir, "*.bytes"))}");

        // Unity 编辑器里以明文加载配置（ResourceCrypto.ProcessInPlace 之外的最简路径）
        RefNative.SetUseDecryptProcess(false);

        Console.WriteLine("[probe] TableInit ...");
        var sw = System.Diagnostics.Stopwatch.StartNew();
        IntPtr err = RefNative.TableInit(ConfigDataDir, ConfigDataDir);
        sw.Stop();
        if (err != IntPtr.Zero)
        {
            Console.WriteLine($"[probe] TableInit FAILED ({sw.Elapsed.TotalMilliseconds:F1} ms): " +
                              Marshal.PtrToStringAnsi(err));
            return 1;
        }
        Console.WriteLine($"[probe] TableInit OK in {sw.Elapsed.TotalMilliseconds:F1} ms");
        Console.WriteLine($"[probe] GetTableVersion = {RefNative.GetTableVersion()}");
        Console.WriteLine($"[probe] GetLang         = {RefNative.GetLang()}");

        // 用 ExcelRecord.json 里的 KlassName 全量探测哪些表在运行时可见
        string[] names = LoadKlassNames();
        Console.WriteLine($"[probe] candidate klass names = {names.Length}");

        var found = new List<(string name, int idx, int count)>();
        foreach (var n in names)
        {
            int idx = RefConfig.TableIndex(n);
            if (idx == 0) continue;
            int c = RefConfig.Count(idx);
            found.Add((n, idx, c));
        }
        Console.WriteLine($"[probe] resolvable tables = {found.Count}");
        long totalRows = 0;
        foreach (var f in found) totalRows += f.count;
        Console.WriteLine($"[probe] total rows        = {totalRows}");

        found.Sort((a, b) => b.count.CompareTo(a.count));
        Console.WriteLine("[probe] top 20 tables by row count:");
        for (int i = 0; i < Math.Min(20, found.Count); i++)
            Console.WriteLine($"          {found[i].name,-40} idx={found[i].idx,-6} rows={found[i].count}");

        return 0;
    }

    /// <summary>从 design-data/ExcelRecord.json 提取全部 KlassName（导表期记录的表清单）。</summary>
    private static string[] LoadKlassNames()
    {
        const string record = @"D:\dev_trunk_ref\design-data\ExcelRecord.json";
        var text = File.ReadAllText(record, Encoding.UTF8);
        var set = new SortedSet<string>(StringComparer.Ordinal);
        int i = 0;
        while (true)
        {
            int k = text.IndexOf("\"KlassName\"", i, StringComparison.Ordinal);
            if (k < 0) break;
            int colon = text.IndexOf(':', k);
            int q1 = text.IndexOf('"', colon + 1);
            int q2 = text.IndexOf('"', q1 + 1);
            if (q1 < 0 || q2 < 0) break;
            set.Add(text.Substring(q1 + 1, q2 - q1 - 1));
            i = q2;
        }
        var arr = new string[set.Count];
        set.CopyTo(arr);
        return arr;
    }
}
