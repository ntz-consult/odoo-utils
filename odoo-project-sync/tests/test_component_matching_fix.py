"""Test component matching with model normalization (dots vs underscores).

This test validates the fix for the issue where components were showing
"⚠️ 0.0 (not found in source)" even when they existed in source files.

The root cause was:
1. Using 'in' instead of '==' for string comparison in find_component_by_reference
2. Not generating both dot and underscore variants of model names in candidate keys
"""

import pytest
from component_ref_utils import ComponentRefUtils
from feature_detector import Component, ComponentType


class TestComponentMatchingFix:
    """Test component matching with model name normalization."""

    def test_match_underscore_ref_to_dotted_model(self):
        """Test matching TOML ref with underscores to source component with dots.
        
        TOML: server_action.stock_move_line.[rwx] Denier to WiP
        Source: Component(model="stock.move.line", name="[rwx] Denier to WiP")
        
        This should MATCH after the fix.
        """
        # Source component (as extracted from XML)
        source_components = [
            Component(
                id=1,
                name="[rwx] Denier to WiP",
                display_name="[rwx] Denier to WiP",
                component_type=ComponentType.SERVER_ACTION,
                model="stock.move.line",  # Dots in model name
                complexity="medium",
                raw_data={},
            )
        ]
        
        # TOML reference (with underscores in model name)
        toml_ref = "server_action.stock_move_line.[rwx] Denier to WiP"
        
        # Should find match
        matched = ComponentRefUtils.find_component_by_reference(toml_ref, source_components)
        
        assert matched is not None, "Component should be matched"
        assert matched.name == "[rwx] Denier to WiP"
        assert matched.model == "stock.move.line"
        assert matched.component_type == ComponentType.SERVER_ACTION

    def test_match_dotted_ref_to_underscore_model(self):
        """Test matching TOML ref with dots to source component with underscores."""
        source_components = [
            Component(
                id=1,
                name="test_field",
                display_name="Test Field",
                component_type=ComponentType.FIELD,
                model="res_partner",  # Underscores in model name
                complexity="simple",
                raw_data={},
            )
        ]
        
        # TOML reference with dots
        toml_ref = "field.res.partner.test_field"
        
        matched = ComponentRefUtils.find_component_by_reference(toml_ref, source_components)
        
        assert matched is not None, "Component should be matched"
        assert matched.name == "test_field"
        assert matched.model == "res_partner"

    def test_match_complex_model_name(self):
        """Test matching with complex model names like stock.move.line."""
        source_components = [
            Component(
                id=1,
                name="x_custom_field",
                display_name="Custom Field",
                component_type=ComponentType.FIELD,
                model="stock.picking.batch",  # Multiple dots
                complexity="simple",
                raw_data={},
            )
        ]
        
        # TOML reference with underscores
        toml_ref = "field.stock_picking_batch.x_custom_field"
        
        matched = ComponentRefUtils.find_component_by_reference(toml_ref, source_components)
        
        assert matched is not None, "Component should be matched"
        assert matched.name == "x_custom_field"
        assert matched.model == "stock.picking.batch"

    def test_case_insensitive_matching(self):
        """Test that matching is case-insensitive."""
        source_components = [
            Component(
                id=1,
                name="TestAction",
                display_name="Test Action",
                component_type=ComponentType.SERVER_ACTION,
                model="sale.order",
                complexity="medium",
                raw_data={},
            )
        ]
        
        # TOML reference with different case
        toml_ref = "server_action.sale_order.testaction"
        
        matched = ComponentRefUtils.find_component_by_reference(toml_ref, source_components)
        
        assert matched is not None, "Component should be matched (case-insensitive)"
        assert matched.name == "TestAction"

    def test_no_false_matches_with_substring(self):
        """Test that 'in' operator bug is fixed - no false substring matches."""
        source_components = [
            Component(
                id=1,
                name="long_component_name_with_extra_text",
                display_name="Long Component",
                component_type=ComponentType.FIELD,
                model="res.partner",
                complexity="simple",
                raw_data={},
            )
        ]
        
        # TOML reference that is a substring of the component name
        toml_ref = "field.res_partner.component_name"
        
        matched = ComponentRefUtils.find_component_by_reference(toml_ref, source_components)
        
        # Should NOT match (before fix, 'in' operator might have caused issues)
        assert matched is None, "Should not match - exact match required"

    def test_special_characters_in_name(self):
        """Test matching with special characters in component names."""
        source_components = [
            Component(
                id=1,
                name="[rwx] Move to Production",
                display_name="[rwx] Move to Production",
                component_type=ComponentType.SERVER_ACTION,
                model="stock.move.line",
                complexity="complex",
                raw_data={},
            )
        ]
        
        # TOML reference with special characters
        toml_ref = "server_action.stock_move_line.[rwx] Move to Production"
        
        matched = ComponentRefUtils.find_component_by_reference(toml_ref, source_components)
        
        assert matched is not None, "Component with special chars should be matched"
        assert matched.name == "[rwx] Move to Production"

    def test_generate_candidate_keys_bidirectional(self):
        """Test that generate_candidate_keys creates both dot and underscore variants."""
        # Test with underscores
        candidates = ComponentRefUtils.generate_candidate_keys(
            "field", "stock_move_line", "test_field"
        )
        
        # Should have both underscore and dotted variants
        assert "field.stock_move_line.test_field" in candidates  # Original
        assert "field.stock.move.line.test_field" in candidates  # Converted to dots
        
        # Test with dots
        candidates = ComponentRefUtils.generate_candidate_keys(
            "field", "stock.move.line", "test_field"
        )
        
        # Should have both dotted and underscore variants
        assert "field.stock.move.line.test_field" in candidates  # Original
        assert "field.stock_move_line.test_field" in candidates  # Converted to underscores

    def test_automation_vs_server_action_fallback(self):
        """Test fallback matching when TOML mislabels automation as server_action."""
        source_components = [
            Component(
                id=1,
                name="Auto Update Status",
                display_name="Auto Update Status",
                component_type=ComponentType.AUTOMATION,  # Actual type
                model="sale.order",
                complexity="medium",
                raw_data={},
            )
        ]
        
        # TOML incorrectly labels it as server_action
        toml_ref = "server_action.sale_order.Auto Update Status"
        
        matched = ComponentRefUtils.find_component_by_reference(toml_ref, source_components)
        
        # Should still match using fallback logic (model+name match)
        assert matched is not None, "Should match using fallback logic"
        assert matched.component_type == ComponentType.AUTOMATION
        assert matched.name == "Auto Update Status"

    def test_filename_based_matching(self):
        """Test filename-based matching for server actions.
        
        Real-world case from Dynabraid project:
        - TOML ref: server_action.mrp_bom.[bom] Populate Variant BoMs (Dynabraid)
        - Source name: [bom] Populate Variant BoMs (Dynabraid)
        - File path: studio/mrp/actions/server_actions/[bom]_populate_variant_boms_(dynabraid).py
        
        The normalized filename should match even if the name has spaces.
        """
        source_components = [
            Component(
                id=1,
                name="[bom] Populate Variant BoMs (Dynabraid)",
                display_name="[bom] Populate Variant BoMs (Dynabraid)",
                component_type=ComponentType.SERVER_ACTION,
                model="mrp.bom",
                complexity="medium",
                raw_data={
                    "file_path": "studio/mrp/actions/server_actions/[bom]_populate_variant_boms_(dynabraid).py",
                    "action_id": "populate_variant_boms_dynabraid",
                },
            )
        ]
        
        # TOML reference with model as underscores
        toml_ref = "server_action.mrp_bom.[bom] Populate Variant BoMs (Dynabraid)"
        
        matched = ComponentRefUtils.find_component_by_reference(toml_ref, source_components)
        
        assert matched is not None, "Component should be matched via filename"
        assert matched.name == "[bom] Populate Variant BoMs (Dynabraid)"
        assert matched.model == "mrp.bom"
        assert matched.component_type == ComponentType.SERVER_ACTION

    def test_normalize_name_for_filename(self):
        """Test name normalization for filename matching."""
        # Test cases from real Dynabraid project
        test_cases = [
            ("[bom] Populate Variant BoMs (Dynabraid)", "[bom]_populate_variant_boms_(dynabraid)"),
            ("[bom] Populate Variant BoMs (Dynatech)", "[bom]_populate_variant_boms_(dynatech)"),
            ("[rwx] Pop. Var. BoMs kg no color", "[rwx]_pop._var._boms_kg_no_color"),
            ("[rwx] Button on SOL for stock on hand", "[rwx]_button_on_sol_for_stock_on_hand"),
        ]
        
        for name, expected_filename in test_cases:
            normalized = ComponentRefUtils.normalize_name_for_filename(name)
            assert normalized == expected_filename, f"Expected '{expected_filename}', got '{normalized}'"

    def test_filename_matching_when_method_name_differs(self):
        """Test filename matching when Python method name differs from action name.
        
        This is a common case for Studio-exported server actions where:
        - The file is named: [bom]_populate_variant_boms_(dynabraid).py
        - But the Python method inside is: action_execute (or similar generic name)
        - The component's name from the extractor is: action_execute
        - But we need to match against the TOML ref with the descriptive name
        
        The fix ensures file_path is in raw_data so filename matching works.
        """
        source_components = [
            Component(
                id=1,
                name="action_execute",  # Generic method name from Python file
                display_name="action_execute",
                component_type=ComponentType.SERVER_ACTION,
                model="mrp.bom",
                complexity="medium",
                raw_data={
                    # This is what the fix adds - file_path in raw_data
                    "file_path": "studio/mrp/actions/server_actions/[bom]_populate_variant_boms_(dynabraid).py",
                },
            )
        ]
        
        # TOML reference uses the descriptive action name
        toml_ref = "server_action.mrp_bom.[bom] Populate Variant BoMs (Dynabraid)"
        
        matched = ComponentRefUtils.find_component_by_reference(toml_ref, source_components)
        
        assert matched is not None, "Component should be matched via filename"
        assert matched.model == "mrp.bom"
        assert matched.component_type == ComponentType.SERVER_ACTION

    def test_filename_matching_with_generic_model(self):
        """Test filename matching when source component has generic model.
        
        This is a common case for Studio-exported server actions where:
        - The file is named: [bom]_populate_variant_boms_(dynabraid).py
        - The XML record model is: ir.actions.server (generic)
        - But the TOML ref has the target model: mrp_bom
        
        The fix allows matching when the source component has a generic model
        like ir.actions.server, as it means the actual target model couldn't
        be determined from the source code.
        """
        source_components = [
            Component(
                id=1,
                name="[bom]_populate_variant_boms_(dynabraid)",  # From filename
                display_name="[bom]_populate_variant_boms_(dynabraid)",
                component_type=ComponentType.SERVER_ACTION,
                model="ir.actions.server",  # Generic model - target model unknown
                complexity="medium",
                raw_data={
                    "file_path": "studio/mrp/actions/server_actions/[bom]_populate_variant_boms_(dynabraid).py",
                },
            )
        ]
        
        # TOML reference uses the actual target model
        toml_ref = "server_action.mrp_bom.[bom] Populate Variant BoMs (Dynabraid)"
        
        matched = ComponentRefUtils.find_component_by_reference(toml_ref, source_components)
        
        assert matched is not None, "Component should be matched even with generic model"
        assert matched.model == "ir.actions.server"
        assert matched.component_type == ComponentType.SERVER_ACTION