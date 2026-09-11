// 导出级正确性校验（G3）：用**真实导出产物 + 真实生成的 accessor** 逐行逐字段读，
// 与导出的 JSON 真值比对。覆盖定宽表（Item/ItemType/Quest）与变长表（UIConfig）。
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;

public static class Program
{
    private static int _checked;
    private static int _failed;

    public static int Main()
    {
        string root = AppContext.BaseDirectory;
        var bundle = File.ReadAllBytes(Path.Combine(root, "fixtures", "data_zh.bin"));
        foreach (var t in ConfigReader.LoadBundle(bundle)) Runtime.Register(t);

        var manifests = JsonDocument.Parse(
            File.ReadAllText(Path.Combine(root, "fixtures", "manifests.json")));

        VerifyItem(root, manifests);
        VerifyItemType(root, manifests);
        VerifyQuest(root, manifests);
        VerifyUIConfig(root, manifests);
        VerifyCodeIndex(root);
        VerifyGroupIndex(root);
        VerifyFnvMatchesPython();
        VerifySparseI18n(root);
        VerifyAllScalars(root);

        Console.WriteLine();
        Console.WriteLine($"共校验 {_checked} 个字段值，不一致 {_failed}");
        return _failed == 0 ? 0 : 1;
    }

    private static JsonElement Rows(string root, string table)
    {
        var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(root, "fixtures", $"{table}_zh.json")));
        return doc.RootElement.EnumerateObject().First().Value;
    }

    private static void VerifyItem(string root, JsonDocument manifests)
    {
        bool uniform = manifests.RootElement.GetProperty("Item").GetProperty("uniform").GetBoolean();
        var rows = Rows(root, "Item");
        Console.WriteLine($"[Item] uniform={uniform}  {ItemAccessor.Count} 行");
        for (int i = 0; i < ItemAccessor.Count; i++)
        {
            var row = ItemAccessor.ByIndex(i)!.Value;
            var src = rows[i];
            Eq("Item", i, "Id", row.Id, src.GetProperty("Id").GetInt32());
            EqS("Item", i, "Name", row.Name, src.GetProperty("Name").GetString());
            EqF("Item", i, "Price", row.Price, src.GetProperty("Price").GetSingle());
            // 枚举按索引比（第 0 项 = common）
            Eq("Item", i, "Rarity", (int)row.Rarity, EnumIndex(src.GetProperty("Rarity").GetString(), "common", "rare", "epic"));
            Eq("Item", i, "ItemTypeId", row.ItemTypeId, src.GetProperty("ItemTypeId").GetInt32());
            Eq("Item", i, "DropRange.Min", row.DropRange.Min, src.GetProperty("DropRange").GetProperty("Min").GetInt32());
            Eq("Item", i, "DropRange.Max", row.DropRange.Max, src.GetProperty("DropRange").GetProperty("Max").GetInt32());
            var tags = src.GetProperty("Tags");
            Eq("Item", i, "Tags.Length", row.Tags.Length, tags.GetArrayLength());
            for (int k = 0; k < tags.GetArrayLength(); k++)
                Eq("Item", i, $"Tags[{k}]", row.Tags[k], tags[k].GetInt32());
        }
    }

    private static void VerifyItemType(string root, JsonDocument manifests)
    {
        bool uniform = manifests.RootElement.GetProperty("ItemType").GetProperty("uniform").GetBoolean();
        var rows = Rows(root, "ItemType");
        Console.WriteLine($"[ItemType] uniform={uniform}  {ItemTypeAccessor.Count} 行");
        for (int i = 0; i < ItemTypeAccessor.Count; i++)
        {
            var row = ItemTypeAccessor.ByID(rows[i].GetProperty("Id").GetInt32())!.Value;
            Eq("ItemType", i, "Id", row.Id, rows[i].GetProperty("Id").GetInt32());
            EqS("ItemType", i, "Name", row.Name, rows[i].GetProperty("Name").GetString());
            EqS("ItemType", i, "Code", row.Code, rows[i].GetProperty("Code").GetString());
        }
    }

    private static void VerifyQuest(string root, JsonDocument manifests)
    {
        bool uniform = manifests.RootElement.GetProperty("Quest").GetProperty("uniform").GetBoolean();
        var rows = Rows(root, "Quest");
        Console.WriteLine($"[Quest] uniform={uniform}  {QuestAccessor.Count} 行");
        for (int i = 0; i < QuestAccessor.Count; i++)
        {
            var row = QuestAccessor.ByIndex(i)!.Value;
            Eq("Quest", i, "Id", row.Id, rows[i].GetProperty("Id").GetInt32());
            EqS("Quest", i, "Title", row.Title, rows[i].GetProperty("Title").GetString());
            EqS("Quest", i, "Description", row.Description, rows[i].GetProperty("Description").GetString());
            Eq("Quest", i, "RewardItemId", row.RewardItemId, rows[i].GetProperty("RewardItemId").GetInt32());
            Eq("Quest", i, "RequiredLevel", row.RequiredLevel, rows[i].GetProperty("RequiredLevel").GetInt32());
        }
    }

    private static void VerifyUIConfig(string root, JsonDocument manifests)
    {
        bool uniform = manifests.RootElement.GetProperty("UIConfig").GetProperty("uniform").GetBoolean();
        var rows = Rows(root, "UIConfig");
        Console.WriteLine($"[UIConfig] uniform={uniform}  {UIConfigAccessor.Count} 行（变长基线）");
        for (int i = 0; i < UIConfigAccessor.Count; i++)
        {
            var row = UIConfigAccessor.ByIndex(i)!.Value;
            Eq("UIConfig", i, "Id", row.Id, rows[i].GetProperty("Id").GetInt32());
            Eq("UIConfig", i, "Layer", (int)row.Layer,
               EnumIndex(rows[i].GetProperty("Layer").GetString(), "Page", "Modal", "Panel", "Overlay"));
            EqS("UIConfig", i, "ResourceKey", row.ResourceKey, rows[i].GetProperty("ResourceKey").GetString());
            Eq("UIConfig", i, "BlocksRaycast", row.BlocksRaycast ? 1 : 0,
               rows[i].GetProperty("BlocksRaycast").GetBoolean() ? 1 : 0);
            Eq("UIConfig", i, "Stack", row.Stack ? 1 : 0, rows[i].GetProperty("Stack").GetBoolean() ? 1 : 0);
        }
    }

    /// <summary>B2：Code 索引（开放寻址 + 精确字符串确认）。</summary>
    private static void VerifyCodeIndex(string root)
    {
        var rows = Rows(root, "ItemType");
        Console.WriteLine($"[ItemType] Code 索引  {rows.GetArrayLength()} 行");
        for (int i = 0; i < rows.GetArrayLength(); i++)
        {
            string code = rows[i].GetProperty("Code").GetString();
            var row = ItemTypeAccessor.ByCode(code);
            if (row == null) { _failed++; Console.WriteLine($"  ✗ ByCode({code}) 未命中"); continue; }
            _checked++;
            Eq("ItemType", i, "ByCode.Id", row.Value.Id, rows[i].GetProperty("Id").GetInt32());
        }
        // 不存在的 code 必须返回 null（且不能死循环）
        _checked++;
        if (ItemTypeAccessor.ByCode("__no_such_code__") != null)
        { _failed++; Console.WriteLine("  ✗ 不存在的 code 应返回 null"); }
    }

    /// <summary>B2：Group 索引（按 key 二分取一组行，行序确定）。</summary>
    private static void VerifyGroupIndex(string root)
    {
        var rows = Rows(root, "UIConfig");
        Console.WriteLine($"[UIConfig] Group 索引(Layer)  {rows.GetArrayLength()} 行");
        var names = new[] { "Page", "Modal", "Panel", "Overlay" };
        for (int k = 0; k < names.Length; k++)
        {
            var want = new List<int>();
            for (int i = 0; i < rows.GetArrayLength(); i++)
                if (EnumIndex(rows[i].GetProperty("Layer").GetString(), names) == k)
                    want.Add(rows[i].GetProperty("Id").GetInt32());
            var got = new List<int>();
            foreach (var r in UIConfigAccessor.ByGroupKey(k)) got.Add(r.Id);
            want.Sort(); got.Sort();
            _checked++;
            if (!want.SequenceEqual(got))
            {
                _failed++;
                Console.WriteLine($"  ✗ Layer={names[k]}: got=[{string.Join(",", got)}] want=[{string.Join(",", want)}]");
            }
        }
    }

    /// <summary>运行期 FNV-1a 必须与导出器 Python 实现逐位一致（Code 索引桶下标依赖它）。</summary>
    private static void VerifyFnvMatchesPython()
    {
        // 由 prepare.py 写入的对照表（Python ct.export.index_query.fnv1a_64 的结果）
        string path = Path.Combine(AppContext.BaseDirectory, "fixtures", "fnv_vectors.tsv");
        if (!File.Exists(path)) { Console.WriteLine("[FNV] 无对照表，跳过"); return; }
        int n = 0;
        foreach (var line in File.ReadAllLines(path))
        {
            if (line.Length == 0) continue;
            var parts = line.Split('\t');
            ulong want = ulong.Parse(parts[1]);
            ulong got = WireReader.Fnv1a64(parts[0]);
            n++; _checked++;
            if (got != want)
            {
                _failed++;
                Console.WriteLine($"  ✗ FNV('{parts[0]}'): got={got} want={want}");
            }
        }
        Console.WriteLine($"[FNV] 与 Python 对照 {n} 条");
    }

    /// <summary>
    /// C：稀疏 i18n 表 + 主表多语言字段的「按下标委托读取」。
    ///   ① 只加载 data_zh.bin 时：i18n 表不存在 ⇒ 回退读主表原文
    ///   ② 加载 data_en.bin 的 i18n 表后：同一行读回英文
    ///   ③ 换成 ja 的 i18n 表：同一行读回日文（**主表不重载、行句柄仍有效**）
    /// </summary>
    private static void VerifySparseI18n(string root)
    {
        var zh = Rows(root, "Item");
        Console.WriteLine("[i18n] 稀疏表 + 按下标委托");
        // ① 只加载主表（zh 包里没有 Item_i18n）
        for (int i = 0; i < zh.GetArrayLength(); i++)
        {
            _checked++;
            var got = ItemAccessor.ByID(zh[i].GetProperty("Id").GetInt32()).Value.Name;
            var want = zh[i].GetProperty("Name").GetString();
            if (got != want)
            { _failed++; Console.WriteLine($"  ✗ 回退读原文 Id={zh[i].GetProperty("Id").GetInt32()}: got={got} want={want}"); }
        }

        // ② / ③ 用单表模式加载 i18n 表（不 Bump 世代 ⇒ 主表行句柄保持有效）
        foreach (var (lang, expect) in new[] { ("en", "Potion"), ("ja", "ポーション") })
        {
            var bundle = File.ReadAllBytes(Path.Combine(root, "fixtures", $"data_{lang}.bin"));
            foreach (var name in new[] { "Item_i18n", "ItemType_i18n", "Quest_i18n" })
            {
                // 用 RegisterI18n：切语言只前进 i18n 世代，**主表行句柄保持有效**
                try { Runtime.RegisterI18n(ConfigReader.LoadTable(bundle, name)); }
                catch (KeyNotFoundException) { }
            }
            _checked++;
            var first = ItemAccessor.ByID(zh[0].GetProperty("Id").GetInt32()).Value.Name;
            if (first != expect)
            { _failed++; Console.WriteLine($"  ✗ 切到 {lang}: got={first} want={expect}"); }
            else { Console.WriteLine($"  ✓ 切到 {lang}: Item[0].Name = {first}"); }
        }
    }

    /// <summary>N1：12 种标量都能被 C# 侧正确读出（含无符号与 64 位边界）。</summary>
    private static void VerifyAllScalars(string root)
    {
        var bundle = File.ReadAllBytes(Path.Combine(root, "fixtures", "scalars.bin"));
        foreach (var t in ConfigReader.LoadBundle(bundle)) Runtime.Register(t);
        var want = JsonDocument.Parse(
            File.ReadAllText(Path.Combine(root, "fixtures", "scalars.json"))).RootElement;
        var row = ScalarsAccessor.ByIndex(0)!.Value;
        Console.WriteLine("[Scalars] 12 种标量往返");

        Eq("Scalars", 0, "Id", row.Id, want.GetProperty("Id").GetInt32());
        Eq("Scalars", 0, "Vint8", row.Vint8, want.GetProperty("Vint8").GetSByte());
        Eq("Scalars", 0, "Vuint8", row.Vuint8, want.GetProperty("Vuint8").GetByte());
        Eq("Scalars", 0, "Vint16", row.Vint16, want.GetProperty("Vint16").GetInt16());
        Eq("Scalars", 0, "Vuint16", row.Vuint16, want.GetProperty("Vuint16").GetUInt16());
        EqU32("Scalars", 0, "Vuint32", row.Vuint32, want.GetProperty("Vuint32").GetUInt32());
        EqI64("Scalars", 0, "Vint64", row.Vint64, want.GetProperty("Vint64").GetInt64());
        EqU64("Scalars", 0, "Vuint64", row.Vuint64, want.GetProperty("Vuint64").GetUInt64());
        EqF("Scalars", 0, "Vfloat", row.Vfloat, want.GetProperty("Vfloat").GetSingle());
        EqD("Scalars", 0, "Vdouble", row.Vdouble, want.GetProperty("Vdouble").GetDouble());
        Eq("Scalars", 0, "Vbool", row.Vbool ? 1 : 0, want.GetProperty("Vbool").GetBoolean() ? 1 : 0);
        EqS("Scalars", 0, "Vstring", row.Vstring, want.GetProperty("Vstring").GetString());
    }

    private static void EqU32(string t, int row, string field, uint got, uint want)
    {
        _checked++;
        if (got != want) { _failed++; Console.WriteLine($"  ✗ {t}[{row}].{field}: got={got} want={want}"); }
    }

    private static void EqI64(string t, int row, string field, long got, long want)
    {
        _checked++;
        if (got != want) { _failed++; Console.WriteLine($"  ✗ {t}[{row}].{field}: got={got} want={want}"); }
    }

    private static void EqU64(string t, int row, string field, ulong got, ulong want)
    {
        _checked++;
        if (got != want) { _failed++; Console.WriteLine($"  ✗ {t}[{row}].{field}: got={got} want={want}"); }
    }

    private static void EqD(string t, int row, string field, double got, double want)
    {
        _checked++;
        if (Math.Abs(got - want) > 1e-6) { _failed++; Console.WriteLine($"  ✗ {t}[{row}].{field}: got={got} want={want}"); }
    }

    private static int EnumIndex(string v, params string[] names)
    {
        var i = Array.IndexOf(names, v);
        return i < 0 ? 0 : i;
    }

    private static void Eq(string t, int row, string field, int got, int want)
    {
        _checked++;
        if (got != want) { _failed++; Console.WriteLine($"  ✗ {t}[{row}].{field}: got={got} want={want}"); }
    }

    private static void EqF(string t, int row, string field, float got, float want)
    {
        _checked++;
        if (Math.Abs(got - want) > 1e-6) { _failed++; Console.WriteLine($"  ✗ {t}[{row}].{field}: got={got} want={want}"); }
    }

    private static void EqS(string t, int row, string field, string got, string want)
    {
        _checked++;
        if (got != want) { _failed++; Console.WriteLine($"  ✗ {t}[{row}].{field}: got={got ?? "<null>"} want={want ?? "<null>"}"); }
    }
}
