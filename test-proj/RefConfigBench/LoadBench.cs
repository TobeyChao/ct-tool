using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

// 加载阶段对标：参考实现 原生 TableInit vs ct ConfigReader.LoadBundle。
//
// 两边都在一个全新进程里跑一次（加载是启动期一次性成本，缓存/世代状态必须干净）。
//   参考实现 : TableInit(<ConfigData dir>) —— 原生自行读盘 + 建索引，读 Main.bytes 与全部语言包
//   ct      : File.ReadAllBytes(bundle) + LoadBundle(bytes) —— 拆开报，便于看清各占多少
public static class LoadBench
{
    private const string RefDll =
        @"D:\dev_trunk_ref\client\Assets\Plugins\x86_64\xlua.dll";

    private const string ConfigDataDir =
        @"D:\dev_trunk_ref\client\Assets\Data\ConfigData\";

    private static readonly string FixDir = Path.Combine(AppContext.BaseDirectory, "fixtures");

    public static int Run(string[] args)
    {
        int reps = args.Length > 1 ? int.Parse(args[1]) : 3;

        Console.WriteLine("=== 加载阶段对标 (fresh process) ===");
        Console.WriteLine();

        // ---------------- 参考实现 ----------------
        NativeLibrary.Load(RefDll);
        RefNative.SetUseDecryptProcess(false);

        double bestRef = double.MaxValue;
        for (int r = 0; r < reps; r++)
        {
            if (r > 0) RefNative.TableShutdown();
            var sw = Stopwatch.StartNew();
            IntPtr err = RefNative.TableInit(ConfigDataDir, ConfigDataDir);
            sw.Stop();
            if (err != IntPtr.Zero) return Fail("TableInit: " + Marshal.PtrToStringAnsi(err));
            double ms = sw.Elapsed.TotalMilliseconds;
            if (ms < bestRef) bestRef = ms;
        }

        var files = Directory.GetFiles(ConfigDataDir, "*.bytes");
        long bytes = 0;
        foreach (var f in files) bytes += new FileInfo(f).Length;

        int tables = 0;
        long rows = 0;
        var json = File.ReadAllText(
            @"E:\Proj\ct-tool\test-proj\RefConfigBench\ref_tables.json");
        foreach (System.Text.RegularExpressions.Match m in System.Text.RegularExpressions.Regex.Matches(
                     json, "\"[^\"]+\":\\s*\\{\"index\":\\s*(\\d+),\\s*\"rows\":\\s*(\\d+)\\}"))
        {
            int idx = int.Parse(m.Groups[1].Value);
            if (idx == 0) continue;
            tables++;
            rows += int.Parse(m.Groups[2].Value);
        }

        Console.WriteLine($"[参考实现] TableInit        {bestRef,10:F1} ms   " +
                          $"tables={tables} rows={rows:N0} files={files.Length} bytes={bytes:N0} ({bytes / 1048576.0:F1} MB)");
        Console.WriteLine($"          throughput      {bytes / 1048576.0 / (bestRef / 1000.0),10:F0} MB/s   " +
                          $"{rows / (bestRef / 1000.0) / 1e6:F1} M rows/s   {bestRef * 1e6 / rows:F0} ns/row");
        Console.WriteLine();

        // ---------------- ct ----------------
        string bundlePath = Path.Combine(FixDir, "scale_corpus.bundle.bin");
        if (!File.Exists(bundlePath)) return Fail("missing " + bundlePath);
        long bundleBytes = new FileInfo(bundlePath).Length;

        double bestRead = double.MaxValue, bestParse = double.MaxValue, bestTotal = double.MaxValue;
        int ctTables = 0;
        long ctRows = 0;

        for (int r = 0; r < reps; r++)
        {
            var sw = Stopwatch.StartNew();
            byte[] raw = File.ReadAllBytes(bundlePath);
            sw.Stop();
            double readMs = sw.Elapsed.TotalMilliseconds;
            if (readMs < bestRead) bestRead = readMs;

            sw.Restart();
            TableVersion.Bump();
            var list = ConfigReader.LoadBundle(raw);
            sw.Stop();
            double parseMs = sw.Elapsed.TotalMilliseconds;
            if (parseMs < bestParse) bestParse = parseMs;
            if (readMs + parseMs < bestTotal) bestTotal = readMs + parseMs;

            ctTables = list.Count;
            ctRows = 0;
            foreach (var t in list) ctRows += t.Count;
            if (r < reps - 1) { foreach (var t in list) t.Dispose(); Runtime.Clear(); }
        }

        Console.WriteLine($"[ct]      File.ReadAllBytes {bestRead,10:F1} ms   ({bundleBytes / 1048576.0:F1} MB)");
        Console.WriteLine($"[ct]      LoadBundle       {bestParse,10:F1} ms   tables={ctTables} rows={ctRows:N0}");
        Console.WriteLine($"[ct]      total            {bestTotal,10:F1} ms   " +
                          $"throughput {bundleBytes / 1048576.0 / (bestTotal / 1000.0):F0} MB/s   " +
                          $"{ctRows / (bestTotal / 1000.0) / 1e6:F1} M rows/s   {bestTotal * 1e6 / ctRows:F0} ns/row");
        Console.WriteLine();
        Console.WriteLine($"[ratio]  total  ct/参考实现 = {bestTotal / bestRef:F2}x    " +
                          $"(bytes/row: ct={bundleBytes / (double)ctRows:F0}B  参考实现={bytes / (double)rows:F0}B)");
        Console.WriteLine($"[ratio]  parse-only ct/参考实现 = {bestParse / bestRef:F2}x");
        return 0;
    }

    private static int Fail(string msg)
    {
        Console.Error.WriteLine(msg);
        return 2;
    }
}
