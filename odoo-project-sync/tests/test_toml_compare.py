import tempfile
import textwrap
import tomllib
from pathlib import Path

from toml_compare import generate_markdown_comparison


def test_generate_markdown_comparison_creates_file(tmp_path):
    file1 = tmp_path / "a.toml"
    file2 = tmp_path / "b.toml"
    out = tmp_path / "out.md"

    file1.write_text(
        textwrap.dedent(
            """
        [features.foo]
        description = "Foo feature"

        [[features.foo.user_stories]]
        description = "As a user, I want foo"
        components = ["model.foo", "view.foo"]
    """
        )
    )

    file2.write_text(
        textwrap.dedent(
            """
        [features.bar]
        description = "Bar feature"

        [[features.bar.user_stories]]
        description = "As a user, I want bar"
        components = ["model.bar"]
    """
        )
    )

    generate_markdown_comparison(str(file1), str(file2), str(out))

    assert out.exists()
    content = out.read_text()
    assert "TOML Structure Comparison" in content
    assert "foo" in content
    assert "bar" in content
