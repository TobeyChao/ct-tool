"""PyInstaller 冻结入口：完整 ct CLI（含 panel 子命令）。"""

from ct.cli import app

if __name__ == "__main__":
    app()
