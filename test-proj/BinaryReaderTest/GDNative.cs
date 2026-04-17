// Provides binary data from the filesystem for testing purposes.
// GDNative.GetMainBytes() is the interface expected by *Accessor classes.
// Primary language is zh, so the main bundle is data_zh.bin.

using System;
using System.IO;

public static class GDNative
{
    // Resolved at startup by Program.cs before any Accessor.Preload() calls.
    public static string MainBinPath { get; set; } = "";

    public static byte[] GetMainBytes()
    {
        if (!File.Exists(MainBinPath))
            throw new FileNotFoundException($"Main binary not found: {MainBinPath}");
        return File.ReadAllBytes(MainBinPath);
    }

    public static byte[] GetI18nBytes() => Array.Empty<byte>();
}
