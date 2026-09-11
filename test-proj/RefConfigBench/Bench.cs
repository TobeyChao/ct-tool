using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;

// 运行时读取基准：参考实现 原生 config runtime (xlua.dll) vs ct FlatBuffers reader。
// 同一进程、同一 GC/JIT 配置、同一台机器，两侧逐场景交替测量。
//
// 说明：
//  - 所有按下标访问的场景都走 64K 预计算索引表（i & 65535），避免 `i % count` 的整数除法
//    污染每一轮计时（6685 不是 2 的幂，除法本身就是几十个 cycle）。
//  - 索引表内容为 k % count，保持顺序访问模式（贴近遍历/扫描的真实 cache 行为）。
public static unsafe class Bench
{
    private const string RefDll =
        @"D:\dev_trunk_ref\client\Assets\Plugins\x86_64\xlua.dll";

    private const string ConfigDataDir =
        @"D:\dev_trunk_ref\client\Assets\Data\ConfigData\";

    private static readonly string FixDir =
        Path.Combine(AppContext.BaseDirectory, "fixtures");

    private static long _sink;

    private static readonly int[] _ixH = new int[65536];
    private static readonly int[] _ixC = new int[65536];
    private static readonly int[] _ixA = new int[65536];   // ArrayBench (6048 行)
    private static readonly int[] _ixS = new int[65536];   // 参考实现 Skill (6050 行)

    // ---- 参考实现 侧：真实表句柄 ----
    private static int _hItemIdx;
    private static byte*[] _hItemRows;
    private static byte* _hItemDp;
    private static int[] _hItemIds;

    private static int _hSkillIdx;
    private static byte*[] _hSkillRows;
    private static byte* _hSkillDp;

    // ---- ct 侧：基准表句柄 ----
    private static ItemBenchRow[] _ctItemRows;
    private static IntPtr[] _ctItemPtrs;
    private static int[] _ctItemIds;
    private static ArrayBenchRow[] _ctArrayRows;
    private static IntPtr[] _ctArrayPtrs;
    private static ConfigTable _ctItemTable;
    private static ItemBenchLiteralRow[] _litItemRows;
    private static ArrayBenchLiteralRow[] _litArrayRows;
    private static int[] _ctItemOffsets; // BuildFieldOffsets 预取路径

    public static int Run(string[] args)
    {
        NativeLibrary.Load(RefDll);
        int lookupIters = args.Length > 1 ? int.Parse(args[1]) : 1_000_000;
        int scanIters = args.Length > 2 ? int.Parse(args[2]) : 2_000_000;
        int reps = args.Length > 3 ? int.Parse(args[3]) : 5;

        Console.WriteLine("=== setup ===");
        SetupRef();
        SetupCt();
        for (int k = 0; k < 65536; k++)
        {
            _ixH[k] = k % _hItemRows.Length;
            _ixS[k] = k % _hSkillRows.Length;
            _ixC[k] = k % _ctItemRows.Length;
            _ixA[k] = k % _ctArrayRows.Length;
        }
        Console.WriteLine();

        Console.WriteLine($"=== scenarios (best of {reps}) ===");
        Console.WriteLine($"{"scenario",-52} {"参考实现",10} {"ct",10} {"ct/参考实现",11}");

        ScenarioLookup(lookupIters, reps);
        ScenarioLookupNoDict(lookupIters, reps);
        ScenarioLookupDirectLoad(lookupIters, reps);
        ScenarioIntFields(scanIters, reps);
        ScenarioIntFieldsPrefetchedOffset(scanIters, reps);
        ScenarioIntFieldsDirectLoad(scanIters, reps);
        ScenarioIntFieldsLiteral(scanIters, reps);
        ScenarioFloatField(scanIters, reps);
        ScenarioBoolField(scanIters, reps);
        ScenarioStringCold(reps);
        ScenarioStringWarm(scanIters, reps);
        ScenarioStringRawDecode(scanIters, reps);
        ScenarioIntVector(scanIters, reps);
        ScenarioIntVectorRawBase(scanIters, reps);
        ScenarioIntVectorLiteral(scanIters, reps);
        ScenarioFullScan(reps);
        ScenarioRowMaterialize(scanIters, reps);

        Console.WriteLine();
        Console.WriteLine($"[sink] {_sink}");
        return 0;
    }

    // ------------------------------------------------------------------ setup

    private static void SetupRef()
    {
        RefNative.SetUseDecryptProcess(false);
        IntPtr err = RefNative.TableInit(ConfigDataDir, ConfigDataDir);
        if (err != IntPtr.Zero)
            throw new Exception("TableInit: " + Marshal.PtrToStringAnsi(err));

        _hItemIdx = RefConfig.TableIndex("Item");
        int hCount = RefConfig.Count(_hItemIdx);
        _hItemRows = new byte*[hCount];
        _hItemIds = new int[hCount];
        for (int i = 0; i < hCount; i++)
        {
            byte* dp;
            byte* p = RefConfig.ByIndex(_hItemIdx, i, out dp);
            _hItemRows[i] = p;
            _hItemDp = dp;
            _hItemIds[i] = *(int*)p;
        }

        _hSkillIdx = RefConfig.TableIndex("Skill");
        int sCount = RefConfig.Count(_hSkillIdx);
        _hSkillRows = new byte*[sCount];
        for (int i = 0; i < sCount; i++)
        {
            byte* dp;
            _hSkillRows[i] = RefConfig.ByIndex(_hSkillIdx, i, out dp);
            _hSkillDp = dp;
        }

        Console.WriteLine($"[参考实现] Item rows={hCount} idx={_hItemIdx}  Skill rows={sCount} idx={_hSkillIdx}  " +
                          $"version={RefNative.GetTableVersion()}  Skill.areas 平均长度={MeanSkillAreas():F1}");
    }


    /// <summary>Skill.areas（_Data 第 10 个 int 槽，偏移 40）的平均长度，用于向量场景归一化。</summary>
    private static double MeanSkillAreas()
    {
        long total = 0;
        for (int i = 0; i < _hSkillRows.Length; i++)
        {
            int off = *(int*)(_hSkillRows[i] + 40);
            total += *(int*)(_hSkillDp + off);
        }
        return _hSkillRows.Length == 0 ? 0 : (double)total / _hSkillRows.Length;
    }

    private static void SetupCt()
    {
        byte[] itemBin = File.ReadAllBytes(Path.Combine(FixDir, "ItemBench.bin"));
        byte[] arrBin = File.ReadAllBytes(Path.Combine(FixDir, "ArrayBench.bin"));
        TableVersion.Bump();
        _ctItemTable = new ConfigTable("ItemBench", itemBin);
        var t2 = new ConfigTable("ArrayBench", arrBin);
        Runtime.Register(_ctItemTable);
        Runtime.Register(t2);

        int n = _ctItemTable.Count;
        _ctItemRows = new ItemBenchRow[n];
        _ctItemPtrs = new IntPtr[n];
        _ctItemIds = new int[n];
        for (int i = 0; i < n; i++)
        {
            IntPtr p = _ctItemTable.RowAt(i);
            _ctItemPtrs[i] = p;
            _ctItemRows[i] = new ItemBenchRow(p, _ctItemTable.OffsetsFor(p, 34), _ctItemTable.Version, i);
            _ctItemIds[i] = WireReader.I32(p, 4);
        }
        // 预取字段偏移（ct reader 已实现但生成器未接线的快路径）
        _ctItemOffsets = WireReader.BuildFieldOffsets(_ctItemPtrs[0], 34);

        byte[] litItemBin = File.ReadAllBytes(Path.Combine(FixDir, "ItemBenchUniform.bin"));
        byte[] litArrBin = File.ReadAllBytes(Path.Combine(FixDir, "ArrayBenchUniform.bin"));
        var litItem = new ConfigTable("ItemBenchUniform", litItemBin);
        var litArr = new ConfigTable("ArrayBenchUniform", litArrBin);
        Runtime.Register(litItem);
        Runtime.Register(litArr);
        _litItemRows = new ItemBenchLiteralRow[litItem.Count];
        for (int i = 0; i < litItem.Count; i++)
            _litItemRows[i] = new ItemBenchLiteralRow(litItem.RowAt(i), litItem.Version);
        _litArrayRows = new ArrayBenchLiteralRow[litArr.Count];
        for (int i = 0; i < litArr.Count; i++)
            _litArrayRows[i] = new ArrayBenchLiteralRow(litArr.RowAt(i), litArr.Version);

        int m = t2.Count;
        _ctArrayRows = new ArrayBenchRow[m];
        _ctArrayPtrs = new IntPtr[m];
        for (int i = 0; i < m; i++)
        {
            _ctArrayPtrs[i] = t2.RowAt(i);
            _ctArrayRows[i] = new ArrayBenchRow(_ctArrayPtrs[i], t2.OffsetsFor(_ctArrayPtrs[i], 20), t2.Version, i);
        }

        Console.WriteLine($"[ct]      ItemBench rows={n} bin={itemBin.Length:N0}B   ArrayBench rows={m} bin={arrBin.Length:N0}B");
    }

    // ---------------------------------------------------------------- harness

    private static void Report(string name, double h, double c, string unit)
    {
        string hn = h > 0 ? h.ToString("F2") : "-";
        string cn = c > 0 ? c.ToString("F2") : "-";
        string ratio = (h > 0 && c > 0) ? (c / h).ToString("F3") + "x" : "-";
        Console.WriteLine($"{(name + " [" + unit + "]"),-52} {hn,10} {cn,10} {ratio,11}");
    }

    private static double TimeNs(int iters, int reps, Action body)
    {
        body();
        double best = double.MaxValue;
        for (int r = 0; r < reps; r++)
        {
            var sw = Stopwatch.StartNew();
            body();
            sw.Stop();
            double ns = sw.Elapsed.TotalMilliseconds * 1_000_000.0 / iters;
            if (ns < best) best = ns;
        }
        return best;
    }

    // -------------------------------------------------------------- scenarios

    private static void ScenarioLookup(int iters, int reps)
    {
        var rnd = new Random(12345);
        int[] probe = new int[iters];
        for (int i = 0; i < iters; i++) probe[i] = _hItemIds[rnd.Next(_hItemIds.Length)];

        double h = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++)
            {
                byte* dp;
                byte* p = RefConfig.ConfigByIDPtr(_hItemIdx, probe[i], out dp);
                acc += p == null ? 0 : 1;
            }
            _sink += acc;
        });

        double c = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++)
            {
                IntPtr p = Runtime.ByID("ItemBench", probe[i]);
                acc += p == IntPtr.Zero ? 0 : 1;
            }
            _sink += acc;
        });

        Report("ByID lookup (int key, 6685 rows)", h, c, "ns/lookup");
    }

    /// <summary>ct 去掉每次调用的 Dictionary&lt;string,ConfigTable&gt; 查表，隔离「字符串字典」成本。</summary>
    private static void ScenarioLookupNoDict(int iters, int reps)
    {
        var rnd = new Random(12345);
        int[] probe = new int[iters];
        for (int i = 0; i < iters; i++) probe[i] = _hItemIds[rnd.Next(_hItemIds.Length)];

        double c = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++) acc += _ctItemTable.ByID(probe[i]) == IntPtr.Zero ? 0 : 1;
            _sink += acc;
        });

        Report("  ct only: ByID via cached table ref", 0, c, "ns/lookup");
    }

    private static void ScenarioIntFields(int iters, int reps)
    {
        double h = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++)
            {
                var row = (RefRows.ItemData*)_hItemRows[_ixH[i & 65535]];
                acc += row->type + row->quality + row->iconRes + row->pileCount + row->sellPrice + row->sortOrder;
            }
            _sink += acc;
        });

        double c = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++)
            {
                var row = _ctItemRows[_ixC[i & 65535]];
                acc += row.Type + row.Quality + row.IconRes + row.PileCount + row.SellPrice + row.IsPut;
            }
            _sink += acc;
        });

        Report("6 x int32 field reads (generated accessor)", h / 6.0, c / 6.0, "ns/field");
    }

    /// <summary>ct 快路径：预取字段偏移 + 原始行指针直读（reader 已实现，生成器未接线）。</summary>
    private static void ScenarioIntFieldsPrefetchedOffset(int iters, int reps)
    {
        int[] off = _ctItemOffsets;

        double c = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++)
            {
                IntPtr row = _ctItemPtrs[_ixC[i & 65535]];
                acc += WireReader.I32At(row, off[8]) + WireReader.I32At(row, off[10])
                     + WireReader.I32At(row, off[12]) + WireReader.I32At(row, off[14])
                     + WireReader.I32At(row, off[16]) + WireReader.I32At(row, off[20]);
            }
            _sink += acc;
        });

        Report("  ct only: 6 x int32 via prefetched offset", 0, c / 6.0, "ns/field");
    }

    /// <summary>诊断：预取偏移 + 单条非对齐 32 位加载（绕开 GetI32 的逐字节拼装）。</summary>
    private static void ScenarioIntFieldsDirectLoad(int iters, int reps)
    {
        int[] off = _ctItemOffsets;

        double c = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++)
            {
                byte* row = (byte*)_ctItemPtrs[_ixC[i & 65535]];
                acc += *(int*)(row + off[8]) + *(int*)(row + off[10])
                     + *(int*)(row + off[12]) + *(int*)(row + off[14])
                     + *(int*)(row + off[16]) + *(int*)(row + off[20]);
            }
            _sink += acc;
        });

        Report("  ct only: 6 x int32 via offset + direct load", 0, c / 6.0, "ns/field");
    }

    /// <summary>诊断：ByID 二分改成单条非对齐加载，隔离 GetI32 对查找路径的影响。</summary>
    private static void ScenarioLookupDirectLoad(int iters, int reps)
    {
        var rnd = new Random(12345);
        int[] probe = new int[iters];
        for (int i = 0; i < iters; i++) probe[i] = _hItemIds[rnd.Next(_hItemIds.Length)];
        IntPtr table = _ctItemTable.Table;
        IntPtr itemsBase = _ctItemTable.ItemsBase;
        // ConfigTable.Table 是整段 buffer 起点，root table 需再加一次 root offset
        byte* root = (byte*)table + WireReader.GetI32((byte*)table);
        byte* indexLen = (byte*)WireReader.Indirect(root, 6);
        if (indexLen == null) { Report("  ct only: ByID binary search, direct load", 0, -1, "ns/lookup"); return; }
        byte* indexEntries = indexLen + 4;
        int indexCount = *(int*)indexLen;

        double c = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++)
            {
                int lo = 0, hi = indexCount - 1;
                int id = probe[i];
                while (lo <= hi)
                {
                    int mid = (lo + hi) >> 1;
                    byte* e = indexEntries + (long)mid * 8;
                    int midId = *(int*)e;
                    if (midId == id)
                    {
                        byte* pos = (byte*)itemsBase + (long)(*(int*)(e + 4)) * 4;
                        acc += *(int*)pos;
                        break;
                    }
                    if (midId < id) lo = mid + 1; else hi = mid - 1;
                }
            }
            _sink += acc;
        });

        Report("  ct only: ByID binary search, direct load", 0, c, "ns/lookup");
    }

    /// <summary>诊断：定宽布局 + 字面量偏移（无偏移表间接层，与 参考实现 的 p->field 同构）。</summary>
    private static void ScenarioIntFieldsLiteral(int iters, int reps)
    {
        double c = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++)
            {
                var row = _litItemRows[_ixC[i & 65535]];
                acc += row.Type + row.Quality + row.IconRes + row.PileCount + row.SellPrice + row.IsPut;
            }
            _sink += acc;
        });

        Report("  ct only: 6 x int32 via literal offset", 0, c / 6.0, "ns/field");
    }

    /// <summary>诊断：定宽布局 + 字面量偏移的向量求和。</summary>
    private static void ScenarioIntVectorLiteral(int iters, int reps)
    {
        double c = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++)
            {
                var arr = _litArrayRows[_ixA[i & 65535]].Areas;
                int len = arr.Length;
                int s = 0;
                for (int k = 0; k < len; k++) s += arr[k];
                acc += s;
            }
            _sink += acc;
        });

        Report("  ct only: vector sum via literal offset", 0, c, "ns/row");
    }

    private static void ScenarioFloatField(int iters, int reps)
    {
        double h = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++) acc += (long)((RefRows.ItemData*)_hItemRows[_ixH[i & 65535]])->priceChecker;
            _sink += acc;
        });

        double c = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++) acc += (long)_ctItemRows[_ixC[i & 65535]].PriceChecker;
            _sink += acc;
        });

        Report("float32 field read", h, c, "ns/read");
    }

    private static void ScenarioBoolField(int iters, int reps)
    {
        double h = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++) acc += ((RefRows.ItemData*)_hItemRows[_ixH[i & 65535]])->isFloatable != 0 ? 1 : 0;
            _sink += acc;
        });

        double c = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++) acc += _ctItemRows[_ixC[i & 65535]].Hidden ? 1 : 0;
            _sink += acc;
        });

        Report("bool field read", h, c, "ns/read");
    }

    /// <summary>冷读一遍全部行：参考实现 每次 UTF-8 解码（无缓存）；ct 首次也解码并写入驻留缓存。</summary>
    private static void ScenarioStringCold(int reps)
    {
        int hn = _hItemRows.Length, cn = _ctItemRows.Length;
        double h = 0, c = 0;

        for (int r = 0; r < reps; r++)
        {
            var sw = Stopwatch.StartNew();
            long acc = 0;
            for (int i = 0; i < hn; i++)
            {
                var row = (RefRows.ItemData*)_hItemRows[i];
                acc += RefRows.ReadI18NInline(_hItemDp + row->designName).Length;
            }
            sw.Stop();
            _sink += acc;
            double ns = sw.Elapsed.TotalMilliseconds * 1_000_000.0 / hn;
            if (r == 0 || ns < h) h = ns;

            ReloadCtTables(); // 世代前进 → 驻留缓存整体失效，保证下一轮是真冷启动
            sw.Restart();
            acc = 0;
            for (int i = 0; i < cn; i++) acc += ((string)_ctItemRows[i].DesignName).Length;
            sw.Stop();
            _sink += acc;
            ns = sw.Elapsed.TotalMilliseconds * 1_000_000.0 / cn;
            if (r == 0 || ns < c) c = ns;
        }

        Report("string field, cold pass (6685 distinct)", h, c, "ns/row");
    }

    private static void ScenarioStringWarm(int iters, int reps)
    {
        double h = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++)
            {
                var row = (RefRows.ItemData*)_hItemRows[_ixH[i & 65535]];
                acc += RefRows.ReadI18NInline(_hItemDp + row->designName).Length;
            }
            _sink += acc;
        });

        double c = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++) acc += ((string)_ctItemRows[_ixC[i & 65535]].DesignName).Length;
            _sink += acc;
        });

        Report("string field, warm (repeat access)", h, c, "ns/read");
    }

    /// <summary>ct 绕过驻留缓存，纯 UTF-8 解码对齐（4 字节长度前缀）。</summary>
    private static void ScenarioStringRawDecode(int iters, int reps)
    {
        double h = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++)
            {
                var row = (RefRows.ItemData*)_hItemRows[_ixH[i & 65535]];
                acc += RefRows.ReadI18NInline(_hItemDp + row->designName).Length;
            }
            _sink += acc;
        });

        double c = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++)
            {
                byte* s = (byte*)WireReader.Indirect(_ctItemPtrs[_ixC[i & 65535]], 6);
                acc += Encoding.UTF8.GetString(s + 4, WireReader.GetI32(s)).Length;
            }
            _sink += acc;
        });

        Report("string decode, ct cache bypassed", h, c, "ns/read");
    }

    private static void ScenarioIntVector(int iters, int reps)
    {
        // 参考实现 Skill.areas = _Data 第 10 个 int 槽 → 偏移 40
        double h = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++)
            {
                byte* row = _hSkillRows[_ixS[i & 65535]];
                int off = *(int*)(row + 40);
                byte* arr = _hSkillDp + off;
                int len = *(int*)arr;
                int* basep = (int*)(arr + 4);
                int s = 0;
                for (int k = 0; k < len; k++) s += basep[k];
                acc += s;
            }
            _sink += acc;
        });

        double c = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++)
            {
                var arr = _ctArrayRows[_ixA[i & 65535]].Areas;
                int len = arr.Length;
                int s = 0;
                for (int k = 0; k < len; k++) s += arr[k];
                acc += s;
            }
            _sink += acc;
        });

        Report("vector<int32> construct + sum", h, c, "ns/row");
    }

    /// <summary>诊断：直接拿向量基址 + 无 indexer 空值分支求和（对齐 参考实现 的裸指针循环）。</summary>
    private static void ScenarioIntVectorRawBase(int iters, int reps)
    {
        IntPtr[] bases = new IntPtr[_ctArrayRows.Length];
        int[] lens = new int[_ctArrayRows.Length];
        for (int i = 0; i < _ctArrayRows.Length; i++)
        {
            byte* v = (byte*)WireReader.Indirect(_ctArrayPtrs[i], 10); // ArrayBench.Areas = slot 10
            if (v == null) { bases[i] = IntPtr.Zero; lens[i] = 0; continue; }
            bases[i] = (IntPtr)(v + 4);
            lens[i] = *(int*)v;
        }

        double c = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++)
            {
                int k = _ixC[i & 65535] % _ctArrayRows.Length;
                int* basep = (int*)bases[k];
                int len = lens[k];
                int s = 0;
                for (int j = 0; j < len; j++) s += basep[j];
                acc += s;
            }
            _sink += acc;
        });

        Report("  ct only: vector sum via raw base ptr", 0, c, "ns/row");
    }

    private static void ScenarioFullScan(int reps)
    {
        double h = 0, c = 0;
        int hn = _hItemRows.Length, cn = _ctItemRows.Length;

        for (int r = 0; r < reps; r++)
        {
            var sw = Stopwatch.StartNew();
            long acc = 0;
            for (int i = 0; i < hn; i++)
            {
                byte* dp;
                byte* p = RefConfig.ByIndex(_hItemIdx, i, out dp);
                acc += *(int*)p;
            }
            sw.Stop();
            _sink += acc;
            double ns = sw.Elapsed.TotalMilliseconds * 1_000_000.0 / hn;
            if (r == 0 || ns < h) h = ns;

            sw.Restart();
            acc = 0;
            for (int i = 0; i < cn; i++) acc += Runtime.RowAt("ItemBench", i).ToInt64();
            sw.Stop();
            _sink += acc;
            ns = sw.Elapsed.TotalMilliseconds * 1_000_000.0 / cn;
            if (r == 0 || ns < c) c = ns;
        }

        Report("full sequential scan by index", h, c, "ns/row");
    }

    private static void ScenarioRowMaterialize(int iters, int reps)
    {
        var rnd = new Random(999);
        int[] probe = new int[iters];
        for (int i = 0; i < iters; i++) probe[i] = _hItemIds[rnd.Next(_hItemIds.Length)];

        double h = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++)
            {
                byte* dp;
                byte* p = RefConfig.ConfigByIDPtr(_hItemIdx, probe[i], out dp);
                if (p != null)
                {
                    var row = (RefRows.ItemData*)p;
                    acc += row->type + row->pileCount + row->sellPrice;
                }
            }
            _sink += acc;
        });

        double c = TimeNs(iters, reps, () =>
        {
            long acc = 0;
            for (int i = 0; i < iters; i++)
            {
                var row = ItemBenchAccessor.ByID(probe[i]);
                if (row.HasValue)
                {
                    var v = row.Value;
                    acc += v.Type + v.PileCount + v.SellPrice;
                }
            }
            _sink += acc;
        });

        Report("ByID + 3 field reads (end to end)", h, c, "ns/row");
    }

    private static void ReloadCtTables()
    {
        byte[] itemBin = File.ReadAllBytes(Path.Combine(FixDir, "ItemBench.bin"));
        TableVersion.Bump();
        _ctItemTable = new ConfigTable("ItemBench", itemBin);
        Runtime.Register(_ctItemTable);
        int n = _ctItemTable.Count;
        for (int i = 0; i < n; i++)
        {
            IntPtr p = _ctItemTable.RowAt(i);
            _ctItemPtrs[i] = p;
            _ctItemRows[i] = new ItemBenchRow(p, _ctItemTable.OffsetsFor(p, 34), _ctItemTable.Version, i);
        }
    }
}
