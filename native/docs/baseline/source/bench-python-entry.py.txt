"""在 venv 的 python 进程内直接运行现行 CLI（任务 1.2/6.5 的配对测量入口）。

`ct/.venv/Scripts/ct.exe` 只是控制台脚本存根：它的峰值工作集会少算真正的解释器内存，
所以基准用 `python.exe <本脚本> export ...` 让被测代码留在同一个进程里，
再用 `Process.PeakWorkingSet64` 采样。两者跑的是同一份 `ct.cli:app`。
"""

import sys

from ct.cli import app

if __name__ == "__main__":
    app()
