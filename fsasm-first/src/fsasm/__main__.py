"""FS-ASM operational CLI entrypoint — dispatch to ``fsasm.cli.run_cli``.

Usage: ``python -m fsasm.cli <operation> [--input <json> | --input -] [--format human|json] [--runs-dir <path>]``

Operations: ``start_new`` | ``resume`` | ``status`` | ``signal``.
"""

import sys

from fsasm.cli import run_cli


def main() -> None:
    sys.exit(run_cli(sys.argv[1:]))


if __name__ == "__main__":
    main()
