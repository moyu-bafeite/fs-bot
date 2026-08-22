"""统一入口：python app.py <type> [args]

自动发现 modules/ 下所有注册了 register() 的领域模块。
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil

from dotenv import load_dotenv


def _discover_modules(parser: argparse.ArgumentParser) -> None:
    """扫描 modules/ 下所有子包，调用 register(subparsers) 注册子命令。"""
    import modules

    subparsers = parser.add_subparsers(dest="type")

    for module_info in pkgutil.iter_modules(modules.__path__):
        try:
            cli_mod = importlib.import_module(f"modules.{module_info.name}.cli")
        except ImportError:
            continue
        if hasattr(cli_mod, "register"):
            cli_mod.register(subparsers)


def main() -> None:
    parser = argparse.ArgumentParser(description="港股数据工具链", add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="dev",
        help="环境（dev=.env.dev, prod=.env.prod）",
    )

    args, remaining = parser.parse_known_args()
    load_dotenv(f".env.{args.env}")

    # 构建完整 parser（含子命令）
    full_parser = argparse.ArgumentParser(description="港股数据工具链")
    full_parser.add_argument(
        "--env", choices=["dev", "prod"], default="dev", help="环境"
    )
    _discover_modules(full_parser)

    if args.help:
        if not remaining:
            full_parser.print_help()
        else:
            full_parser.parse_args(remaining + ["--help"])
        return

    if not remaining:
        full_parser.print_help()
        return

    parsed = full_parser.parse_args(remaining)
    if hasattr(parsed, "func"):
        parsed.func(parsed)
    else:
        full_parser.print_help()


if __name__ == "__main__":
    main()
