using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

// 正确性校验：OPT-1 的「按 vtable 解析偏移表」路径必须与旧的「每次走 vtable」路径
// 逐字段等价。ItemBench 表内存在多个不同 vtable（缺省 string/vector 按行裁剪），
// 所以这也是对「不要求整表共享 vtable」这一设计主张的实证。
public static unsafe class Verify
{
    private static readonly string FixDir = Path.Combine(AppContext.BaseDirectory, "fixtures");

    public static int Run(string[] args)
    {
        byte[] itemBin = File.ReadAllBytes(Path.Combine(FixDir, "ItemBench.bin"));
        byte[] arrBin = File.ReadAllBytes(Path.Combine(FixDir, "ArrayBench.bin"));
        TableVersion.Bump();
        var item = new ConfigTable("ItemBench", itemBin);
        var arr = new ConfigTable("ArrayBench", arrBin);
        Runtime.Register(item);
        Runtime.Register(arr);

        int failures = 0;
        int checkedFields = 0;
        var vts = new HashSet<nint>();

        // ItemBench: 15 个客户端字段，slot 4..32
        int[] slots = { 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32 };
        for (int i = 0; i < item.Count; i++)
        {
            IntPtr p = item.RowAt(i);
            int[] off = item.OffsetsFor(p, 34);
            vts.Add((nint)((byte*)p - WireReader.GetI32((byte*)p)));

            // 标量槽位 4..22（含 float slot 18、bool slot 22）
            foreach (int slot in new[] { 4, 8, 10, 12, 14, 16, 20 })
            {
                int a = WireReader.I32At(p, off[slot]);
                int b = WireReader.I32(p, slot);
                checkedFields++;
                if (a != b) { Fail(i, slot, $"I32 {a} != {b}"); failures++; }
            }
            {
                float a = WireReader.F32At(p, off[18]);
                float b = WireReader.F32(p, 18);
                checkedFields++;
                if (a != b) { Fail(i, 18, $"F32 {a} != {b}"); failures++; }
            }
            {
                bool a = WireReader.BoolAt(p, off[22]);
                bool b = WireReader.Bool(p, 22);
                checkedFields++;
                if (a != b) { Fail(i, 22, $"Bool {a} != {b}"); failures++; }
            }

            // 字符串 6 / 24 / 26：缺省时一侧为 null，另一侧也必须为 null
            foreach (int slot in new[] { 6, 24, 26 })
            {
                byte* pa = (byte*)WireReader.IndirectAt(p, off[slot]);
                byte* pb = (byte*)WireReader.Indirect(p, slot);
                string sa = pa == null ? null : Encoding.UTF8.GetString(pa + 4, WireReader.GetI32(pa));
                string sb = pb == null ? null : Encoding.UTF8.GetString(pb + 4, WireReader.GetI32(pb));
                checkedFields++;
                if (sa != sb) { Fail(i, slot, $"Str \"{Trunc(sa)}\" != \"{Trunc(sb)}\""); failures++; }
            }

            // vector<int32> slot 30：长度与逐元素
            {
                var va = new NArray<int>((byte*)WireReader.IndirectAt(p, off[30]), 0);
                int lb = WireReader.ArrLen(p, 30);
                checkedFields++;
                if (va.Length != lb) { Fail(i, 30, $"vec len {va.Length} != {lb}"); failures++; }
                else
                {
                    for (int k = 0; k < lb; k++)
                    {
                        int a = va[k];
                        int b = WireReader.ArrI32(p, 30, k);
                        checkedFields++;
                        if (a != b) { Fail(i, 30, $"vec[{k}] {a} != {b}"); failures++; break; }
                    }
                }
            }

            // vector<string> slot 28
            {
                var va = new NStructArray<NString>((byte*)WireReader.IndirectAt(p, off[28]), 0);
                int lb = WireReader.ArrLen(p, 28);
                checkedFields++;
                if (va.Length != lb) { Fail(i, 28, $"strvec len {va.Length} != {lb}"); failures++; }
            }

            // 嵌套 record slot 32
            {
                IntPtr ra = (IntPtr)WireReader.IndirectAt(p, off[32]);
                IntPtr rb = WireReader.Indirect(p, 32);
                checkedFields++;
                if (ra != rb) { Fail(i, 32, $"record ptr {ra:X} != {rb:X}"); failures++; }
            }
        }

        // ArrayBench: vector<int32> slot 10 / 12 / 14 / 16 / 18
        foreach (int slot in new[] { 10, 12, 14, 16, 18 })
        {
            for (int i = 0; i < arr.Count; i += 97)
            {
                IntPtr p = arr.RowAt(i);
                int[] off = arr.OffsetsFor(p, 20);
                var va = new NArray<int>((byte*)WireReader.IndirectAt(p, off[slot]), 0);
                int lb = WireReader.ArrLen(p, slot);
                checkedFields++;
                if (va.Length != lb) { Fail(i, slot, $"arr len {va.Length} != {lb}"); failures++; continue; }
                for (int k = 0; k < lb; k++)
                {
                    checkedFields++;
                    if (va[k] != WireReader.ArrI32(p, slot, k)) { Fail(i, slot, $"arr[{k}] 不一致"); failures++; break; }
                }
            }
        }

        // 哈希索引 vs 二分查找：全表逐行 + 未命中探测
        int hashChecked = 0, hashBad = 0;
        foreach (var tbl in new[] { item, arr })
        {
            for (int i = 0; i < tbl.Count; i++)
            {
                int key = WireReader.I32(tbl.RowAt(i), 4);
                int viaHash = tbl.HashSearch(key);
                int viaBsearch = tbl.IndexSearch(key);
                hashChecked++;
                if (viaHash != viaBsearch) { hashBad++; if (hashBad < 5) Console.WriteLine($"  哈希/二分不一致 key={key} hash={viaHash} bsearch={viaBsearch}"); }
            }
            // 未命中：确保哈希探测能正确终止
            for (int k = 0; k < 200; k++)
            {
                int missing = -1000000 - k * 7919;
                hashChecked++;
                if (tbl.HashSearch(missing) != -1 || tbl.IndexSearch(missing) != -1) { hashBad++; }
            }
        }
        Console.WriteLine($"哈希 vs 二分: 校验 {hashChecked:N0} 个 key，不一致 {hashBad}");

        // per-field 字符串缓存：同一行重复读必须返回同一实例且值正确
        int strChecked = 0, strBad = 0;
        for (int i = 0; i < item.Count; i++)
        {
            var row = ItemBenchAccessor.ByIndex(i);
            if (!row.HasValue) continue;
            string a = row.Value.DesignName;
            string b = row.Value.DesignName;          // 命中缓存
            var row2 = ItemBenchAccessor.ByIndex(i);
            string c = row2.Value.DesignName;         // 另一句柄，同一下标
            byte* raw = (byte*)WireReader.Indirect(item.RowAt(i), 6);
            string expect = raw == null ? null : Encoding.UTF8.GetString(raw + 4, WireReader.GetI32(raw));
            strChecked++;
            if (a != expect || !ReferenceEquals(a, b) || !ReferenceEquals(a, c)) { strBad++; if (strBad < 5) Console.WriteLine($"  字符串缓存不一致 row={i}"); }
        }
        Console.WriteLine($"per-field 字符串缓存: 校验 {strChecked:N0} 行，不一致 {strBad}");
        failures += hashBad + strBad;

        // 单缓冲视图路径：ConfigReader.LoadBundle（共享 pin + 切片）必须产出与
        // 单表模式逐字段一致的结果，且 Count 正确
        int viewChecked = 0, viewBad = 0;
        var bundleList = ConfigReader.LoadBundle(File.ReadAllBytes(Path.Combine(FixDir, "bench_bundle.bin")));
        ConfigTable viewItem = null, viewArr = null;
        foreach (var ct in bundleList)
        {
            if (ct.Name == "ItemBench") viewItem = ct;
            if (ct.Name == "ArrayBench") viewArr = ct;
        }
        if (viewItem == null || viewArr == null) { viewBad++; Console.WriteLine("  视图加载缺表"); }
        else
        {
            if (viewItem.Count != item.Count || viewArr.Count != arr.Count) { viewBad++; Console.WriteLine($"  Count 不一致 {viewItem.Count}/{item.Count}"); }
            for (int i = 0; i < item.Count; i++)
            {
                byte* a = (byte*)viewItem.RowAt(i);
                byte* b = (byte*)item.RowAt(i);
                for (int slot = 4; slot <= 32; slot += 2)
                {
                    viewChecked++;
                    if (WireReader.I32((IntPtr)a, slot) != WireReader.I32((IntPtr)b, slot)) { viewBad++; break; }
                }
            }
            // 视图表的 ByID / 哈希索引也要一致
            for (int i = 0; i < arr.Count; i += 53)
            {
                int key = WireReader.I32(arr.RowAt(i), 4);
                viewChecked++;
                if (viewArr.HashSearch(key) != arr.HashSearch(key)) viewBad++;
            }
        }
        Console.WriteLine($"单缓冲视图 vs 单表模式: 校验 {viewChecked:N0} 个值，不一致 {viewBad}");
        failures += viewBad;

        Console.WriteLine($"表内不同 vtable 个数: ItemBench={vts.Count}");
        Console.WriteLine($"已校验字段值: {checkedFields:N0}");
        if (failures == 0)
        {
            Console.WriteLine("[PASS] 偏移表路径与 vtable 路径逐字段等价");
            return 0;
        }
        Console.WriteLine($"[FAIL] {failures} 处不一致");
        return 1;
    }

    private static void Fail(int row, int slot, string msg)
    {
        if (__reported++ < 20) Console.WriteLine($"  row={row} slot={slot}: {msg}");
    }

    private static int __reported;

    private static string Trunc(string s) => s == null ? "<null>" : (s.Length > 20 ? s.Substring(0, 20) + "..." : s);
}
