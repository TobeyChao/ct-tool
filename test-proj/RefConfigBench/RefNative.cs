using System;
using System.Runtime.InteropServices;

// P/Invoke 层：忠实复刻 参考实现 客户端
// client/Assets/Scripts/Frameworks/Configs/Runtime/Config/NativeAPI/*.cs 的声明。
// 原生实现位于 Unity 插件 xlua.dll（x86_64 桌面版），本工程独立于 Unity 运行。
public static unsafe class RefNative
{
    public const string DllName = "xlua";

    [DllImport(DllName, CallingConvention = CallingConvention.Cdecl)]
    public static extern IntPtr TableInit(string tablePath, string patchTablePath);

    [DllImport(DllName, EntryPoint = "TableShutdown", CallingConvention = CallingConvention.Cdecl)]
    public static extern void TableShutdown();

    [DllImport(DllName, CallingConvention = CallingConvention.Cdecl)]
    public static extern void SetUseDecryptProcess([MarshalAs(UnmanagedType.I1)] bool useDecryptProcess);

    [DllImport(DllName, CallingConvention = CallingConvention.Cdecl)]
    public static extern int GetTableIndex(string tableName);

    [DllImport(DllName, CallingConvention = CallingConvention.Cdecl)]
    public static extern IntPtr GetConfigDataPointer(int tableIndex);

    [DllImport(DllName, CallingConvention = CallingConvention.Cdecl)]
    public static extern IntPtr ConfigByID(int tableIndex, int id, out IntPtr dp);

    [DllImport(DllName, CallingConvention = CallingConvention.Cdecl)]
    public static extern IntPtr ConfigByStringID(int tableIndex, IntPtr utf16String, int stringLength, out IntPtr dp);

    [DllImport(DllName, CallingConvention = CallingConvention.Cdecl)]
    public static extern int GetConfigCount(int tableIndex);

    [DllImport(DllName, CallingConvention = CallingConvention.Cdecl)]
    public static extern IntPtr ConfigByIndex(int tableIndex, int index, out IntPtr dp);

    [DllImport(DllName, CallingConvention = CallingConvention.Cdecl)]
    public static extern IntPtr ConfigByGroupKey(int tableIndex, int id);

    [DllImport(DllName, CallingConvention = CallingConvention.Cdecl)]
    public static extern int GetTableVersion();

    [DllImport(DllName, CallingConvention = CallingConvention.Cdecl)]
    public static extern IntPtr GetI18N(int i18nKlassHash, int id);

    [DllImport(DllName, CallingConvention = CallingConvention.Cdecl)]
    public static extern void SetLang(int lang, string langName);

    [DllImport(DllName, CallingConvention = CallingConvention.Cdecl)]
    public static extern int GetLang();

    [DllImport(DllName, CallingConvention = CallingConvention.Cdecl)]
    public static extern IntPtr LoadVTable(string name);

    [DllImport(DllName, CallingConvention = CallingConvention.Cdecl)]
    public static extern IntPtr VTableFind(IntPtr vTable, IntPtr utf16Key, int keyLen, void** dataPointer);
}

/// <summary>参考实现 Config.cs 的托管镜像（仅保留本基准用到的部分）。</summary>
public static unsafe class RefConfig
{
    public static int TableIndex(string name) => RefNative.GetTableIndex(name);
    public static int Count(int tableIndex) => RefNative.GetConfigCount(tableIndex);

    /// <summary>对齐 参考实现 Config.ByID&lt;T&gt;：原生二分 + 行指针 + dataPointer + 版本快照。</summary>
    public static byte* ByID(int tableIndex, int id, out byte* dataPointer)
    {
        IntPtr dp;
        byte* p = (byte*)RefNative.ConfigByID(tableIndex, id, out dp);
        dataPointer = (byte*)dp;
        return p;
    }

    public static byte* ByIndex(int tableIndex, int index, out byte* dataPointer)
    {
        IntPtr dp;
        byte* p = (byte*)RefNative.ConfigByIndex(tableIndex, index, out dp);
        dataPointer = (byte*)dp;
        return p;
    }

    /// <summary>指针版 ConfigByID（与本仓库其它 unsafe 代码风格一致）。</summary>
    public static byte* ConfigByIDPtr(int tableIndex, int id, out byte* dataPointer)
    {
        IntPtr dp;
        byte* p = (byte*)RefNative.ConfigByID(tableIndex, id, out dp);
        dataPointer = (byte*)dp;
        return p;
    }
}
