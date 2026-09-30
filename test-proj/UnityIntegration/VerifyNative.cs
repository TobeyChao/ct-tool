using System;
using System.IO;
using System.Linq;
using System.Reflection;
using Newtonsoft.Json.Linq;
using GameFramework.ConfigGen;

// Executed in memory by the real game Editor; no Assets import or domain reload.
public static class CtNativeUnityVerification
{
    private static int checks;
    private static int fields;
    private static int serverOnlySkipped;

    public static object Run(string output)
    {
        if (UnityEditor.EditorApplication.isPlaying || UnityEditor.EditorApplication.isCompiling)
            throw new InvalidOperationException("Editor must be idle outside Play Mode");
        if (GDNative.IsLoaded) throw new InvalidOperationException("Existing configuration must not be displaced");
        checks = fields = serverOnlySkipped = 0;
        string[] tables = Directory.GetFiles(Path.Combine(output, "generated/csharp"), "*Accessor.cs")
            .Select(p => Path.GetFileName(p).Replace("Accessor.cs", "")).OrderBy(x => x).ToArray();
        Require(tables.Length == 14, "Frozen game fixture must contain 14 tables");
        try
        {
            GDNative.InitBytes(File.ReadAllBytes(Path.Combine(output, "binary/data_zh.bin")));
            TableVersion.MarkFullReload();
            Require(ItemAccessor.ByID(1).Value.Name == "瓶装饮用水", "Independent Chinese reference");
            Require(ItemAccessor.ByID(1).Value.DropRange.Min == 1, "Independent nested record reference");
            Require(ItemAccessor.ByID(1).Value.Tags[0] == 101, "Independent vector reference");
            var held = ItemAccessor.ByID(1).Value;
            IntPtr main = GDNative.FindTable("Item");
            int generation = TableVersion.Current;
            foreach (string lang in new[] { "zh", "en", "ja", "zh" })
            {
                // Absolute path accepted by the real ConfigLoader, so no game assets are replaced.
                GameFramework.ConfigLoader.SwitchLanguageAsync(lang == "zh" ? null :
                    Path.Combine(output, "binary/data_" + lang + ".bin")).GetAwaiter().GetResult();
                Require(TableVersion.Current == generation, "Language switch preserves main generation");
                Require(GDNative.FindTable("Item") == main, "Language switch preserves main pointer");
                Require(held.Name == (lang == "en" ? "Bottled Water" :
                    lang == "ja" ? "ミネラルウォーター" : "瓶装饮用水"), "Held row reads current language");
                foreach (string table in tables) CompareTable(output, table, lang);
            }
            GameFramework.ConfigLoader.SwitchLanguageAsync(Path.Combine(output, "missing-language.bin"))
                .GetAwaiter().GetResult();
            Require(held.Name == "瓶装饮用水", "Missing language falls back to primary");
            var cached = ItemAccessor.ByID(1).Value;
            GDNative.Unload();
            GDNative.InitBytes(File.ReadAllBytes(Path.Combine(output, "binary/data_zh.bin")),
                File.ReadAllBytes(Path.Combine(output, "binary/data_en.bin")));
            TableVersion.MarkFullReload();
            bool stale = false;
            try { string old = cached.Name; }
            catch (InvalidOperationException e) { stale = e.Message.Contains("stale reader"); }
            Require(stale, "Full reload invalidates previously held rows before memory access");
            Require(ItemAccessor.ByID(1).Value.Name == "Bottled Water", "Accessor cache resolves reloaded bundle");
            Require(fields > 1000, "Complete field checks must not silently shrink");
            return new { tables = tables.Length, checks, fields, serverOnlySkipped,
                languages = new[] { "zh", "en", "ja", "zh" }, nativePlugin = "xlua/gd",
                heldRowAcrossLanguageSwitch = true, pointerAndGenerationStable = true,
                missingLanguageFallback = true, staleRowRejected = true, reloadedCacheFresh = true };
        }
        finally
        {
            GDNative.Unload();
            TableVersion.MarkFullReload();
        }
    }

    private static void CompareTable(string output, string table, string lang)
    {
        var expected = (JArray)JObject.Parse(File.ReadAllText(Path.Combine(output, "json", table + "_" + lang + ".json"))).Properties().Single().Value;
        Type accessor = typeof(ItemAccessor).Assembly.GetType("GameFramework.ConfigGen." + table + "Accessor", true);
        int count = (int)accessor.GetProperty("Count").GetValue(null);
        Require(count == expected.Count, table + " row count");
        for (int i = 0; i < count; i++)
        {
            object row = accessor.GetMethod("ByIndex").Invoke(null, new object[] { i });
            Require(row != null, table + " ByIndex");
            Require(accessor.GetMethod("ByID").Invoke(null, new object[] { (int)expected[i]["Id"] }) != null, table + " ByID");
            foreach (var field in ((JObject)expected[i]).Properties())
            {
                PropertyInfo getter = row.GetType().GetProperty(field.Name);
                if (getter == null)
                {
                    // Both fields are explicitly server_only in the copied game schemas.
                    Require((table == "Item" && field.Name == "IsActive") ||
                        (table == "Text" && field.Name == "Note"), "Unexpected missing getter " + table + "." + field.Name);
                    serverOnlySkipped++;
                    continue;
                }
                Compare(getter.GetValue(row), field.Value, table + "[" + i + "]." + field.Name);
            }
        }
        MethodInfo codeLookup = accessor.GetMethod("ByCodeName");
        if (codeLookup != null)
        {
            foreach (var row in expected)
                Require(codeLookup.Invoke(null, new object[] { (string)row["CodeName"] }) != null, table + " CodeName");
            Require(codeLookup.Invoke(null, new object[] { "__ct_native_absent__" }) == null, table + " absent CodeName");
        }
    }

    private static void Compare(object value, JToken expected, string path)
    {
        if (expected is JObject record)
        {
            foreach (var field in record.Properties())
                Compare(value.GetType().GetProperty(field.Name).GetValue(value), field.Value, path + "." + field.Name);
        }
        else if (expected is JArray array)
        {
            int length = (int)value.GetType().GetProperty("Length").GetValue(value);
            Require(length == array.Count, path + " length");
            for (int i = 0; i < length; i++)
                Compare(value.GetType().GetProperty("Item").GetValue(value, new object[] { i }), array[i], path + "[" + i + "]");
        }
        else
        {
            fields++;
            if (expected.Type == JTokenType.Boolean) Require((bool)value == (bool)expected, path);
            else if (expected.Type == JTokenType.String) Require(Convert.ToString(value) == (string)expected, path);
            else if (expected.Type == JTokenType.Float)
                Require(Math.Abs(Convert.ToDouble(value) - (double)expected) <= Math.Max(1, Math.Abs((double)expected)) * 1e-6, path);
            else if (expected.Type == JTokenType.Integer) Require(Convert.ToDecimal(value) == (decimal)expected, path);
            else throw new InvalidOperationException("Unhandled field " + path + ": " + expected.Type);
        }
    }

    private static void Require(bool condition, string message)
    {
        checks++;
        if (!condition) throw new InvalidOperationException("Native Unity verification: " + message);
    }
}
