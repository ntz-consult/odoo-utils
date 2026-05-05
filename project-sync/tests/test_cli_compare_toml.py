import textwrap
from pathlib import Path

from shared.python.cli import OdooSyncCLI


def test_cli_compare_toml_creates_report(tmp_path):
    file1 = tmp_path / "a.toml"
    file2 = tmp_path / "b.toml"
    out = tmp_path / "report.md"

    file1.write_text(
        textwrap.dedent(
            """
        [features.a]
        description = "A"
    """
        )
    )
    file2.write_text(
        textwrap.dedent(
            """
        [features.b]
        description = "B"
    """
        )
    )

    cli = OdooSyncCLI()
    # Run command and ensure success (0)
    rc = cli.run(
        ["compare-toml", str(file1), str(file2), "--output", str(out)]
    )
    assert rc == 0
    assert out.exists()
    assert "TOML Structure Comparison" in out.read_text()
