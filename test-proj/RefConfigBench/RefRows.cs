using System;
using System.Runtime.InteropServices;
using System.Text;

// 逐字复刻 参考实现 生成代码（client/.../Runtime/Generate/Item.cs）里的私有行结构体。
// 顺序/宽度必须与生成物一致，否则读到的就是错位的垃圾。
public static unsafe class RefRows
{
    [StructLayout(LayoutKind.Sequential)]
    public struct ItemData
    {
        public int id;
        public int designName;
        public int type;
        public int quality;
        public int param;
        public int description;
        public int iconRes;
        public int pileCount;
        public int sellPrice;
        public int useKind;
        public int page;
        public int sortOrder;
        public int redspotOnGain;
        public int SupplyCrateItemId;
        public int itemCrateQuality;
        public int supplyCratePositionID;
        public int convertToItems;
        public int boxtype;
        public int SupplyCrateDetailSound;
        public int SupplyCrate_Card;
        public int isFloatable;
        public int highQualityIconRes;
        public float priceChecker;
        public int gotoSystem;
        public int putLimit;
        public int supplyQuality;
        public int character;
        public int timeLimitType;
        public int addTime;
        public int targetTime;
        public int unAcceptIcon;
        public int useCD;
        public int bp_description;
        public int isPut;
        public int stringParams;
        public int hideInPackage;
    }

    /// <summary>参考实现 NString：2 字节长度前缀 + UTF-8。</summary>
    public static string ReadNString(byte* p)
    {
        if (p == null) return null;
        int len = *(ushort*)p;
        return Encoding.UTF8.GetString(p + sizeof(ushort), len);
    }

    /// <summary>参考实现 Config.GetI18N（lang==0 分支）：同样 2 字节长度前缀，但【不驻留】。</summary>
    public static string ReadI18NInline(byte* p)
    {
        if (p == null) return null;
        int len = *(ushort*)p;
        return Encoding.UTF8.GetString(p + sizeof(ushort), len);
    }

    /// <summary>参考实现 NArray&lt;int&gt;：4 字节长度前缀 + 连续 int32。</summary>
    public static int SumIntArray(byte* p, int cap)
    {
        if (p == null) return 0;
        int len = *(int*)p;
        if (len > cap) len = cap;
        int* basep = (int*)(p + 4);
        int sum = 0;
        for (int i = 0; i < len; i++) sum += basep[i];
        return sum;
    }
}
