"""Tests for feature_detector module."""

import json
from pathlib import Path

import pytest
from feature_detector import (
    Component,
    ComponentType,
    Feature,
    FeatureDetector,
    FeatureMapping,
    PatternMatcher,
    UserStory,
    load_extraction_results,
)


class TestComponent:
    """Tests for Component dataclass."""

    def test_component_creation(self):
        """Test basic component creation."""
        comp = Component(
            id=1,
            name="x_studio_test",
            display_name="Test Field",
            component_type=ComponentType.FIELD,
            model="sale.order",
            complexity="simple",
            raw_data={"id": 1},
            is_studio=True,
        )

        assert comp.id == 1
        assert comp.name == "x_studio_test"
        assert comp.is_studio is True
        assert comp.type_label == "Field"

    def test_component_type_labels(self):
        """Test type_label property for all component types."""
        labels = {
            ComponentType.FIELD: "Field",
            ComponentType.VIEW: "View",
            ComponentType.SERVER_ACTION: "Server Action",
            ComponentType.AUTOMATION: "Automation",
            ComponentType.REPORT: "Report",
        }

        for comp_type, expected_label in labels.items():
            comp = Component(
                id=1,
                name="test",
                display_name="Test",
                component_type=comp_type,
                model="test.model",
                complexity="simple",
                raw_data={},
            )
            assert comp.type_label == expected_label


class TestUserStory:
    """Tests for UserStory dataclass."""

    def test_remaining_hours(self):
        """Test remaining hours calculation."""
        story = UserStory(
            title="Test",
            description="Test story",
            components=[],
            estimated_hours=10.0,
            logged_hours=3.0,
        )

        assert story.remaining_hours == 7.0

    def test_remaining_hours_never_negative(self):
        """Test remaining hours doesn't go negative."""
        story = UserStory(
            title="Test",
            description="Test story",
            components=[],
            estimated_hours=5.0,
            logged_hours=10.0,
        )

        assert story.remaining_hours == 0.0


class TestFeature:
    """Tests for Feature dataclass."""

    def test_total_estimated_hours(self):
        """Test total estimated hours calculation."""
        stories = [
            UserStory(
                title="Story 1",
                description="",
                components=[],
                estimated_hours=5.0,
            ),
            UserStory(
                title="Story 2",
                description="",
                components=[],
                estimated_hours=3.0,
            ),
        ]

        feature = Feature(
            name="Test Feature",
            description="",
            user_stories=stories,
        )

        assert feature.total_estimated_hours == 8.0

    def test_completion_count(self):
        """Test completion count calculation."""
        stories = [
            UserStory(
                title="Story 1",
                description="",
                components=[],
                estimated_hours=5.0,
                status="completed",
            ),
            UserStory(
                title="Story 2",
                description="",
                components=[],
                estimated_hours=3.0,
                status="pending",
            ),
            UserStory(
                title="Story 3",
                description="",
                components=[],
                estimated_hours=2.0,
                status="completed",
            ),
        ]

        feature = Feature(
            name="Test Feature",
            description="",
            user_stories=stories,
        )

        completed, total = feature.completion_count
        assert completed == 2
        assert total == 3


class TestPatternMatcher:
    """Tests for PatternMatcher class."""

    def test_wildcard_end_pattern(self):
        """Test wildcard at end of pattern."""
        matcher = PatternMatcher(["x_sales_*"])

        assert matcher.matches("x_sales_discount") is True
        assert matcher.matches("x_sales_status") is True
        assert matcher.matches("x_purchase_discount") is False

    def test_wildcard_both_sides_pattern(self):
        """Test wildcard on both sides."""
        matcher = PatternMatcher(["*_quote_*"])

        assert matcher.matches("x_quote_status") is True
        assert matcher.matches("sale_quote_number") is True
        assert matcher.matches("x_sales_status") is False

    def test_tag_pattern(self):
        """Test [tag] prefix pattern."""
        matcher = PatternMatcher(["[sales]*"])

        assert matcher.matches("[sales] Approval Status") is True
        assert matcher.matches("[SALES] Priority") is True  # Case insensitive
        assert matcher.matches("[purchase] Status") is False

    def test_multiple_patterns(self):
        """Test matching against multiple patterns."""
        matcher = PatternMatcher(["x_sales_*", "*_quote_*", "[invoice]*"])

        assert matcher.matches("x_sales_discount") is True
        assert matcher.matches("purchase_quote_number") is True
        assert matcher.matches("[invoice] Number") is True
        assert matcher.matches("x_random_field") is False

    def test_case_insensitive_fnmatch(self):
        """Test case insensitivity for fnmatch patterns."""
        matcher = PatternMatcher(["x_sales_*"])

        assert matcher.matches("X_SALES_STATUS") is True
        assert matcher.matches("x_Sales_Status") is True


class TestFeatureMapping:
    """Tests for FeatureMapping class."""

    def test_from_file(self, tmp_path: Path):
        """Test loading from JSON file."""
        mapping_data = {
            "features": {
                "Sales Enhancement": {
                    "description": "Sales improvements",
                    "patterns": ["x_sales_*"],
                }
            },
            "unmapped_handling": "group_by_model",
        }

        mapping_file = tmp_path / "feature-mapping.json"
        with open(mapping_file, "w") as f:
            json.dump(mapping_data, f)

        mapping = FeatureMapping.from_file(mapping_file)

        assert "Sales Enhancement" in mapping.features
        assert mapping.unmapped_handling == "group_by_model"

    def test_default_mapping(self):
        """Test default empty mapping."""
        mapping = FeatureMapping.default()

        assert mapping.features == {}
        assert mapping.unmapped_handling == "group_by_model"


class TestFeatureDetector:
    """Tests for FeatureDetector class."""

    @pytest.fixture
    def sample_components(self) -> list[Component]:
        """Create sample components for testing."""
        return [
            Component(
                id=1,
                name="x_sales_discount",
                display_name="Sales Discount",
                component_type=ComponentType.FIELD,
                model="sale.order",
                complexity="simple",
                raw_data={},
            ),
            Component(
                id=2,
                name="x_sales_priority",
                display_name="Sales Priority",
                component_type=ComponentType.FIELD,
                model="sale.order",
                complexity="simple",
                raw_data={},
            ),
            Component(
                id=3,
                name="x_vendor_code",
                display_name="Vendor Code",
                component_type=ComponentType.FIELD,
                model="res.partner",
                complexity="simple",
                raw_data={},
            ),
        ]

    def test_detect_with_patterns(self, sample_components: list[Component]):
        """Test feature detection with pattern matching."""
        mapping = FeatureMapping(
            features={
                "Sales Enhancement": {
                    "description": "Sales improvements",
                    "patterns": ["x_sales_*"],
                }
            }
        )

        detector = FeatureDetector(mapping)
        features = detector.detect_features(sample_components)

        # Should have Sales Enhancement feature and Contact Customizations fallback
        feature_names = {f.name for f in features}
        assert "Sales Enhancement" in feature_names
        assert "Contact Customizations" in feature_names

        # Check Sales Enhancement has correct components
        sales_feature = next(
            f for f in features if f.name == "Sales Enhancement"
        )
        assert len(sales_feature.components) == 2
        assert "sale.order" in sales_feature.affected_models

    def test_detect_with_model_fallback(
        self, sample_components: list[Component]
    ):
        """Test grouping by model when no patterns match."""
        mapping = FeatureMapping.default()
        detector = FeatureDetector(mapping)
        features = detector.detect_features(sample_components)

        # Should have Sales Order Customizations and Contact Customizations
        feature_names = {f.name for f in features}
        assert "Sales Order Customizations" in feature_names
        assert "Contact Customizations" in feature_names

    def test_model_to_feature_name_known_model(self):
        """Test feature name generation for known models."""
        mapping = FeatureMapping.default()
        detector = FeatureDetector(mapping)

        assert (
            detector._model_to_feature_name("sale.order")
            == "Sales Order Customizations"
        )
        assert (
            detector._model_to_feature_name("res.partner")
            == "Contact Customizations"
        )

    def test_model_to_feature_name_unknown_model(self):
        """Test feature name generation for unknown models."""
        mapping = FeatureMapping.default()
        detector = FeatureDetector(mapping)

        assert (
            detector._model_to_feature_name("custom.model.name")
            == "Custom Model Name Customizations"
        )


class TestLoadExtractionResults:
    """Tests for load_extraction_results function."""

    def test_load_from_fixtures(self):
        """Test loading extraction results from fixture files."""
        fixture_dir = Path(__file__).parent / "fixtures" / "extraction_samples"

        if not fixture_dir.exists():
            pytest.skip("Fixture directory not found")

        components = load_extraction_results(fixture_dir)

        # Should have loaded components from all files
        assert len(components) > 0

        # Check component types
        types = {c.component_type for c in components}
        assert ComponentType.FIELD in types
        assert ComponentType.VIEW in types

    def test_load_from_empty_directory(self, tmp_path: Path):
        """Test loading from directory with no extraction files."""
        components = load_extraction_results(tmp_path)

        assert components == []

    def test_load_partial_results(self, tmp_path: Path):
        """Test loading when only some extraction files exist."""
        # Create only fields output
        fields_data = {
            "records": [
                {
                    "id": 1,
                    "name": "x_test",
                    "field_description": "Test",
                    "model": "test.model",
                }
            ]
        }

        fields_file = tmp_path / "custom_fields_output.json"
        with open(fields_file, "w") as f:
            json.dump(fields_data, f)

        components = load_extraction_results(tmp_path)

        assert len(components) == 1
        assert components[0].component_type == ComponentType.FIELD
