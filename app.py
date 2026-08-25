"""统一入口：python app.py <command> [args]

自动发现 modules/ 下所有导出 app 对象的领域模块。

环境变量:
  HK_BOT_ENV  环境标识 (dev/prod)，默认 dev
              对应加载 .env.{HK_BOT_ENV} 文件
"""

from __future__ import annotations

import importlib
import os
import pkgutil

import typer
from dotenv import load_dotenv


def _discover_modules(app: typer.Typer) -> None:
    """扫描 modules/ 下所有子包，注册 typer 子命令。"""
    import modules

    for module_info in pkgutil.iter_modules(modules.__path__):
        try:
            cli_mod = importlib.import_module(f"modules.{module_info.name}.cli")
        except ImportError:
            continue

        if hasattr(cli_mod, "app"):
            app.add_typer(cli_mod.app, name=module_info.name.replace("_", "-"))


if __name__ == "__main__":
    env = os.environ.get("HK_BOT_ENV", "dev")
    load_dotenv(f".env.{env}")

    app = typer.Typer(help="港股数据工具链", no_args_is_help=True)
    _discover_modules(app)
    app()
