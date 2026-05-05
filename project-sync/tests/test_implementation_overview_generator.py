"""Tests for Implementation Overview Generator."""

import pytest
from pathlib import Path
from implementation_overview_generator import ImplementationOverviewGenerator


def test_implementation_overview_generator_basic(tmp_path):
    """Test basic HTML generation from TOML data."""
    # Create a sample TOML file
    toml_content = """
[metadata]
generated_at = "2025-12-20T10:00:00"

[statistics]
total_features = 1
total_user_stories = 1
total_components = 3

[features."Test Feature"]
description = "A test feature"
sequence = 1

user_stories = [
    { name = "Test Story", description = "Test", sequence = 1, components = [
        { ref = "field.sale_order.x_test", complexity = "simple", time_estimate = "1:30", completion = "100%" },
        { ref = "view.sale_order.Test View", complexity = "medium", time_estimate = "3:00", completion = "50%" },
        { ref = "server_action.sale_order.Test Action", complexity = "complex", time_estimate = "5:30", completion = "0%" },
    ] },
]
"""
    toml_file = tmp_path / "feature_user_story_map.toml"
    toml_file.write_text(toml_content)
    
    # Generate HTML
    html = ImplementationOverviewGenerator.generate_from_toml(toml_file)
    
    # Verify HTML contains expected elements
    assert "Implementation Overview" in html
    assert "Component Type Summary" in html
    assert "Detailed Component Lists" in html
    
    # Verify table structure
    assert "<table" in html
    assert "<thead" in html
    assert "<tbody" in html
    
    # Verify component types are present
    assert "Fields" in html
    assert "Views" in html
    assert "Server Actions" in html
    
    # Verify time format (HH:MM)
    assert "01:30" in html
    assert "03:00" in html
    assert "05:30" in html
    
    # Verify totals row exists
    assert "TOTAL" in html
    assert "10:00" in html  # 1:30 + 3:00 + 5:30 = 10:00


def test_component_type_extraction():
    """Test component type extraction from ref strings."""
    generator = ImplementationOverviewGenerator(Path("dummy.toml"))
    
    assert generator._extract_component_type("field.sale_order.x_test") == "field"
    assert generator._extract_component_type("view.product_product.List") == "view"
    assert generator._extract_component_type("server_action.mrp_bom.Action") == "server_action"
    assert generator._extract_component_type("no_dots_here") == "custom"


def test_time_parsing_and_formatting():
    """Test time parsing and formatting."""
    generator = ImplementationOverviewGenerator(Path("dummy.toml"))
    
    # Test parsing
    assert generator._parse_time_estimate("1:30") == 90
    assert generator._parse_time_estimate("0:15") == 15
    assert generator._parse_time_estimate("10:00") == 600
    assert generator._parse_time_estimate("invalid") == 0
    
    # Test formatting
    assert generator._format_time(90) == "01:30"
    assert generator._format_time(15) == "00:15"
    assert generator._format_time(600) == "10:00"
    assert generator._format_time(0) == "00:00"


def test_complexity_colors():
    """Test complexity color coding."""
    generator = ImplementationOverviewGenerator(Path("dummy.toml"))
    
    assert generator._get_complexity_color("simple") == "#afece7"  # Icy Aqua (palette)
    assert generator._get_complexity_color("medium") == "#99c5b5"  # Muted Teal 2 (palette)
    assert generator._get_complexity_color("complex") == "#af2e00"  # Rusty Spice (palette)
    assert generator._get_complexity_color("unknown") == "#899e8b"  # Muted Teal (palette)


def test_empty_toml_handling(tmp_path):
    """Test handling of empty TOML file."""
    toml_content = """
[metadata]
generated_at = "2025-12-20T10:00:00"

[features]
"""
    toml_file = tmp_path / "feature_user_story_map.toml"
    toml_file.write_text(toml_content)
    
    # Should not raise an error
    html = ImplementationOverviewGenerator.generate_from_toml(toml_file)
    
    assert "Implementation Overview" in html
    assert "TOTAL" in html
    assert "00:00" in html


def test_overall_totals_table(tmp_path):
    """Test overall totals table with estimates and actuals."""
    toml_content = """
[metadata]
generated_at = "2025-12-20T10:00:00"

[features."Feature 1"]
description = "Test feature 1"
sequence = 1
task_id = 100

user_stories = [
    { name = "Story 1", description = "Test", sequence = 1, task_id = 101, components = [
        { ref = "field.sale_order.x_test1", complexity = "simple", loc = 10, time_estimate = "1:30", completion = "100%" },
        { ref = "view.sale_order.Test View 1", complexity = "medium", loc = 20, time_estimate = "3:00", completion = "50%" },
    ] },
]

[features."Feature 2"]
description = "Test feature 2"
sequence = 2
task_id = 200

user_stories = [
    { name = "Story 2", description = "Test", sequence = 1, task_id = 201, components = [
        { ref = "field.sale_order.x_test2", complexity = "simple", loc = 15, time_estimate = "2:00", completion = "100%" },
        { ref = "server_action.sale_order.Test Action", complexity = "complex", loc = 50, time_estimate = "5:30", completion = "0%" },
    ] },
]
"""
    toml_file = tmp_path / "feature_user_story_map.toml"
    toml_file.write_text(toml_content)
    
    # Generate with timesheet data
    timesheet_data = {
        100: 2.5,  # Feature 1: 2.5 hours
        101: 1.0,  # Story 1: 1.0 hour
        200: 3.0,  # Feature 2: 3.0 hours
        201: 4.5,  # Story 2: 4.5 hours
    }
    
    html = ImplementationOverviewGenerator.generate_from_toml(toml_file, timesheet_data)
    
    # Verify overall totals table is present
    assert "Overall Total Estimate Time" in html
    assert "Overall Total Actual Time" in html
    
    # Verify times are calculated correctly
    # Total estimate: 1:30 + 3:00 + 2:00 + 5:30 = 12:00
    assert "12:00" in html
    
    # Total actual: 2.5 + 1.0 + 3.0 + 4.5 = 11.0 hours = 11:00
    assert "11:00" in html
    
    # Verify table has right-aligned cells
    assert 'text-align: right' in html


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
