using Google.FlatBuffers;

// Locate data_en.bin relative to the project directory.
// When run via `dotnet run` from test-proj/BinaryReaderTest/, the working
// directory is the project directory. We walk up to the repo root then into gd/.
string projectDir = AppContext.BaseDirectory; // bin/Debug/net10.0/
string binPath = Path.GetFullPath(
    Path.Combine(projectDir, "..", "..", "..", "..", "..", "gd", "output", "binary", "data_zh.bin"));

Console.WriteLine($"Binary path: {binPath}");

if (!File.Exists(binPath))
{
    Console.Error.WriteLine($"[ERROR] File not found: {binPath}");
    Environment.Exit(1);
}

GDNative.MainBinPath = binPath;

// Load and parse the DataBundle.
DataBundle bundle = LoadBundle(binPath);
Console.WriteLine($"Bundle tables: {bundle.TablesLength}");
if (bundle.TablesLength == 0)
{
    Console.Error.WriteLine("[ERROR] DataBundle has 0 tables.");
    Environment.Exit(1);
}

// Run all table tests.
int failures = 0;
failures += TestItemTable(bundle);
failures += TestItemTypeTable(bundle);
failures += TestQuestTable(bundle);
failures += TestUIConfigTable(bundle);

if (failures == 0)
    Console.WriteLine("All tests passed.");
else
    Console.WriteLine($"{failures} test(s) failed.");

Environment.Exit(failures > 0 ? 1 : 0);

// ── helpers ──────────────────────────────────────────────────────────────────

static DataBundle LoadBundle(string path)
{
    byte[] bytes = File.ReadAllBytes(path);
    var bb = new ByteBuffer(bytes);
    return DataBundle.GetRootAsDataBundle(bb);
}

static ByteBuffer? FindTable(DataBundle bundle, string name)
{
    for (int i = 0; i < bundle.TablesLength; i++)
    {
        var bt = bundle.Tables(i);
        if (bt?.Name == name)
        {
            byte[]? data = bt.Value.GetDataArray();
            if (data == null || data.Length == 0) return null;
            return new ByteBuffer(data);
        }
    }
    return null;
}

static int TestItemTable(DataBundle bundle)
{
    int failures = 0;

    var bb = FindTable(bundle, "Item");
    if (bb == null)
    {
        Console.WriteLine("[FAIL] Item table: not found in bundle");
        return 1;
    }

    var table = ItemTable.GetRootAsItemTable(bb);
    if (table.ItemsLength == 0)
    {
        Console.WriteLine("[FAIL] Item table: ItemsLength == 0");
        return 1;
    }

    var row = table.Items(0);
    if (!row.HasValue) { Console.WriteLine("[FAIL] Item table: row 0 is null"); return 1; }
    var item = row.Value;

    if (item.Id <= 0)  { Console.WriteLine($"[FAIL] Item[0].Id <= 0 (got {item.Id})"); failures++; }
    if (string.IsNullOrEmpty(item.Name)) { Console.WriteLine($"[FAIL] Item[0].Name is empty"); failures++; }
    if (item.Price < 0) { Console.WriteLine($"[FAIL] Item[0].Price < 0 (got {item.Price})"); failures++; }

    // struct: DropRange
    if (item.DropRange.HasValue)
    {
        var dr = item.DropRange.Value;
        if (dr.Min > dr.Max)
        {
            Console.WriteLine($"[FAIL] Item[0].DropRange.Min ({dr.Min}) > Max ({dr.Max})");
            failures++;
        }
    }

    // array: Tags (must not throw)
    int tagLen = item.TagsLength;
    _ = tagLen;

    if (failures == 0)
        Console.WriteLine($"[PASS] Item table  ({table.ItemsLength} rows, id={item.Id}, name={item.Name}, price={item.Price}, tags={item.TagsLength})");

    return failures;
}

static int TestItemTypeTable(DataBundle bundle)
{
    var bb = FindTable(bundle, "ItemType");
    if (bb == null) { Console.WriteLine("[FAIL] ItemType table: not found in bundle"); return 1; }

    var table = ItemTypeTable.GetRootAsItemTypeTable(bb);
    if (table.ItemsLength == 0) { Console.WriteLine("[FAIL] ItemType table: ItemsLength == 0"); return 1; }

    var row = table.Items(0);
    if (!row.HasValue) { Console.WriteLine("[FAIL] ItemType table: row 0 is null"); return 1; }
    if (row.Value.Id <= 0) { Console.WriteLine($"[FAIL] ItemType[0].Id <= 0 (got {row.Value.Id})"); return 1; }

    Console.WriteLine($"[PASS] ItemType table ({table.ItemsLength} rows, id={row.Value.Id})");
    return 0;
}

static int TestQuestTable(DataBundle bundle)
{
    var bb = FindTable(bundle, "Quest");
    if (bb == null) { Console.WriteLine("[FAIL] Quest table: not found in bundle"); return 1; }

    var table = QuestTable.GetRootAsQuestTable(bb);
    if (table.ItemsLength == 0) { Console.WriteLine("[FAIL] Quest table: ItemsLength == 0"); return 1; }

    var row = table.Items(0);
    if (!row.HasValue) { Console.WriteLine("[FAIL] Quest table: row 0 is null"); return 1; }
    if (row.Value.Id <= 0) { Console.WriteLine($"[FAIL] Quest[0].Id <= 0 (got {row.Value.Id})"); return 1; }

    Console.WriteLine($"[PASS] Quest table ({table.ItemsLength} rows, id={row.Value.Id})");
    return 0;
}

static int TestUIConfigTable(DataBundle bundle)
{
    var bb = FindTable(bundle, "UIConfig");
    if (bb == null) { Console.WriteLine("[FAIL] UIConfig table: not found in bundle"); return 1; }

    var table = UIConfigTable.GetRootAsUIConfigTable(bb);
    if (table.ItemsLength == 0) { Console.WriteLine("[FAIL] UIConfig table: ItemsLength == 0"); return 1; }

    var row = table.Items(0);
    if (!row.HasValue) { Console.WriteLine("[FAIL] UIConfig table: row 0 is null"); return 1; }
    var cfg = row.Value;

    if (cfg.Id <= 0) { Console.WriteLine($"[FAIL] UIConfig[0].Id <= 0 (got {cfg.Id})"); return 1; }
    if (string.IsNullOrEmpty(cfg.ResourceKey)) { Console.WriteLine("[FAIL] UIConfig[0].ResourceKey is empty"); return 1; }

    Console.WriteLine($"[PASS] UIConfig table ({table.ItemsLength} rows, id={cfg.Id}, layer={cfg.Layer}, key={cfg.ResourceKey})");
    return 0;
}
