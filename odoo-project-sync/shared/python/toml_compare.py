#!/usr/bin/env python3
"""TOML Structure Comparator Compares two TOML files semantically and outputs
markdown tables.

Requires Python 3.11+
"""

import tomllib
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


def load_toml_file(filepath: str) -> Dict[str, Any]:
    """Load a TOML file."""
    with open(filepath, "rb") as f:
        return tomllib.load(f)


def extract_all_data(data: Dict) -> Dict[str, Any]:
    """Extract all features, user stories, and components from TOML data."""
    result = {}

    if "features" not in data:
        return result

    for feature_name, feature_data in data["features"].items():
        user_stories = {}

        if "user_stories" in feature_data:
            for story in feature_data["user_stories"]:
                story_desc = story.get("description", "")
                components = story.get("components", [])
                user_stories[story_desc] = set(components)

        result[feature_name] = {
            "description": feature_data.get("description", ""),
            "detected_by": feature_data.get("detected_by", ""),
            "user_stories": user_stories,
        }

    return result


def generate_markdown_comparison(
    file1: str, file2: str, output_file: str = "toml_compare.md"
):
    """Generate markdown comparison tables."""

    # Load both files
    data1 = load_toml_file(file1)
    data2 = load_toml_file(file2)

    # Extract structures
    features1 = extract_all_data(data1)
    features2 = extract_all_data(data2)

    # Get all unique feature names
    all_features = sorted(set(features1.keys()) | set(features2.keys()))

    # Get file names for headers
    file1_name = Path(file1).name
    file2_name = Path(file2).name

    # Start building markdown
    md_lines = []
    md_lines.append("# TOML Structure Comparison")
    md_lines.append("")
    md_lines.append(f"**File 1:** `{file1_name}`  ")
    md_lines.append(f"**File 2:** `{file2_name}`")
    md_lines.append("")

    # Statistics
    stats1 = data1.get("statistics", {})
    stats2 = data2.get("statistics", {})

    if stats1 or stats2:
        md_lines.append("## Statistics")
        md_lines.append("")
        md_lines.append("| Metric | File 1 | File 2 |")
        md_lines.append("|--------|--------|--------|")
        md_lines.append(
            f"| Total Features | {stats1.get('total_features', 'N/A')} | {stats2.get('total_features', 'N/A')} |"
        )
        md_lines.append(
            f"| Total User Stories | {stats1.get('total_user_stories', 'N/A')} | {stats2.get('total_user_stories', 'N/A')} |"
        )
        md_lines.append(
            f"| Total Components | {stats1.get('total_components', 'N/A')} | {stats2.get('total_components', 'N/A')} |"
        )
        md_lines.append("")

    # Feature overview table
    md_lines.append("## Features Overview")
    md_lines.append("")
    md_lines.append("| Feature | " + file1_name + " | " + file2_name + " |")
    md_lines.append(
        "|---------|"
        + "-" * (len(file1_name) + 2)
        + "|"
        + "-" * (len(file2_name) + 2)
        + "|"
    )

    for feature in all_features:
        in_file1 = "✓" if feature in features1 else ""
        in_file2 = "✓" if feature in features2 else ""
        md_lines.append(f"| {feature} | {in_file1} | {in_file2} |")

    md_lines.append("")

    # Detailed comparison per feature
    md_lines.append("## Detailed Feature Comparison")
    md_lines.append("")

    for feature in all_features:
        md_lines.append(f"### {feature}")
        md_lines.append("")

        # Feature metadata
        desc1 = features1.get(feature, {}).get("description", "")
        desc2 = features2.get(feature, {}).get("description", "")

        if desc1 or desc2:
            md_lines.append("**Description:**")
            if desc1 == desc2 and desc1:
                md_lines.append(f"- {desc1}")
            else:
                if desc1:
                    md_lines.append(f"- {file1_name}: {desc1}")
                if desc2:
                    md_lines.append(f"- {file2_name}: {desc2}")
            md_lines.append("")

        # Get all user stories for this feature
        stories1 = features1.get(feature, {}).get("user_stories", {})
        stories2 = features2.get(feature, {}).get("user_stories", {})
        all_stories = sorted(set(stories1.keys()) | set(stories2.keys()))

        if not all_stories:
            md_lines.append("*No user stories found*")
            md_lines.append("")
            continue

        # Create table header
        md_lines.append(
            "| User Story / Component | "
            + file1_name
            + " | "
            + file2_name
            + " |"
        )
        md_lines.append(
            "|------------------------|"
            + "-" * (len(file1_name) + 2)
            + "|"
            + "-" * (len(file2_name) + 2)
            + "|"
        )

        for story_desc in all_stories:
            # User story row (bold)
            in_file1 = "✓" if story_desc in stories1 else ""
            in_file2 = "✓" if story_desc in stories2 else ""
            md_lines.append(
                f"| **{escape_markdown(story_desc)}** | {in_file1} | {in_file2} |"
            )

            # Get all components for this story
            components1 = stories1.get(story_desc, set())
            components2 = stories2.get(story_desc, set())
            all_components = sorted(components1 | components2)

            # Component rows (indented)
            for component in all_components:
                comp_in_file1 = "✓" if component in components1 else ""
                comp_in_file2 = "✓" if component in components2 else ""
                md_lines.append(
                    f"| → `{escape_markdown(component)}` | {comp_in_file1} | {comp_in_file2} |"
                )

        md_lines.append("")

    # Write to file
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    print(f"✓ Comparison written to: {output_file}")

    # Print summary to console
    print(f"\nSummary:")
    print(f"  Total features compared: {len(all_features)}")
    print(
        f"  Features in {file1_name} only: {len(set(features1.keys()) - set(features2.keys()))}"
    )
    print(
        f"  Features in {file2_name} only: {len(set(features2.keys()) - set(features1.keys()))}"
    )
    print(
        f"  Features in both: {len(set(features1.keys()) & set(features2.keys()))}"
    )


def escape_markdown(text: str) -> str:
    """Escape special markdown characters in text."""
    # Escape pipe characters which break tables
    text = text.replace("|", "\\|")
    return text


if __name__ == "__main__":
    import sys

    if len(sys.argv) not in [3, 4]:
        print(
            "Usage: python toml_compare.py <file1.toml> <file2.toml> [output.md]"
        )
        print("  Default output file: toml_compare.md")
        sys.exit(1)

    file1 = sys.argv[1]
    file2 = sys.argv[2]
    output_file = sys.argv[3] if len(sys.argv) == 4 else "toml_compare.md"

    try:
        generate_markdown_comparison(file1, file2, output_file)
    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
