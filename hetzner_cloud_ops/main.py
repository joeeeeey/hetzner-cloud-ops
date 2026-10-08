from __future__ import annotations

from .command_router import CommandRouter


def main(argv: list[str]) -> int:
    return CommandRouter().run(argv)
