"""Tests for feature_user_story_map_generator module."""

import tomllib
from pathlib import Path
from unittest.mock import Mock

import pytest
from feature_detector import Component, ComponentType
from feature_user_story_map_generator import (
    FeatureUserStoryMapGenerator,
    MapGenerationResult,
)


class TestMapGenerationResult:
    """Tests for MapGenerationResult dataclass."""

    def test_result_creation(self):
        """Test basic result creation."""
        result = MapGenerationResult(
            total_features=5,
            total_user_stories=12,
            total_components=45,
            user_stories_needing_review=2,
            new_features=3,
            preserved_features=2,
            new_components_added=0,
        )

        assert result.total_features == 5
        assert result.total_user_stories == 12
        assert result.total_components == 45
        assert result.user_stories_needing_review == 2
        assert result.new_features == 3
        assert result.preserved_features == 2


class TestFeatureUserStoryMapGenerator:
    """Tests for FeatureUserStoryMapGenerator class."""

    @pytest.fixture
    def temp_project(self, tmp_path):
        """Create temporary project directory."""
        return tmp_path

    @pytest.fixture
    def generator(self, temp_project):
        """Create generator instance."""
        return FeatureUserStoryMapGenerator(temp_project, verbose=False)

    @pytest.fixture
    def mock_component(self):
        """Create mock component."""
        return Component(
            id=1,
            name="x_test_field",
            display_name="Test Field",
            component_type=ComponentType.FIELD,
            model="sale.order",
            complexity="simple",
            raw_data={},
        )

    @pytest.fixture
    def mock_feature(self, mock_component):
        """Create mock feature with components."""
        feature = Mock()
        feature.name = "Test Feature"
        feature.description = "Test feature description"
        feature.components = [mock_component]
        return feature

    @pytest.fixture
    def mock_feature_multiple_types(self):
        """Create mock feature with multiple component types."""
        feature = Mock()
        feature.name = "Multi-Type Feature"
        feature.description = "Feature with multiple component types"
        feature.components = [
            Component(
                id=1,
                name="x_field_1",
                display_name="Field 1",
                component_type=ComponentType.FIELD,
                model="sale.order",
                complexity="simple",
                raw_data={},
            ),
            Component(
                id=2,
                name="x_field_2",
                display_name="Field 2",
                component_type=ComponentType.FIELD,
                model="sale.order",
                complexity="medium",
                raw_data={},
            ),
            Component(
                id=3,
                name="sale_order_custom_view",
                display_name="Custom View",
                component_type=ComponentType.VIEW,
                model="sale.order",
                complexity="medium",
                raw_data={},
            ),
            Component(
                id=4,
                name="auto_process",
                display_name="Auto Process",
                component_type=ComponentType.AUTOMATION,
                model="sale.order",
                complexity="complex",
                raw_data={},
            ),
        ]
        return feature

    def test_generator_initialization(self, temp_project):
        """Test generator initialization."""
        gen = FeatureUserStoryMapGenerator(temp_project, verbose=True)

        assert gen.project_root == temp_project
        assert gen.map_file == temp_project / "studio" / "feature_user_story_map.toml"
        assert gen.verbose is True

    def test_generate_map_first_time(self, generator, mock_feature):
        """Test map generation from scratch."""
        features = [mock_feature]

        result = generator.generate_or_update_map(features, extraction_count=1)

        assert result.total_features == 1
        assert result.new_features == 1
        assert result.preserved_features == 0
        assert generator.map_file.exists()

        # Verify TOML is valid
        with open(generator.map_file, "rb") as f:
            data = tomllib.load(f)
            assert "metadata" in data
            assert "statistics" in data
            assert "features" in data
            assert "Test Feature" in data["features"]
            # Sequence should default to 1 on initial generation
            feature_def = data["features"]["Test Feature"]
            assert feature_def.get("sequence") == 1
            # User stories is now a dict with story name as key
            user_stories = feature_def["user_stories"]
            assert isinstance(user_stories, dict)
            # Each user story should have sequence defaulting to 1
            for story_name, story_data in user_stories.items():
                assert story_data.get("sequence") == 1

    def test_generate_map_creates_user_stories_by_type(
        self, generator, mock_feature_multiple_types
    ):
        """Test that user stories are created by component type."""
        features = [mock_feature_multiple_types]

        result = generator.generate_or_update_map(features, extraction_count=4)

        # Should create 3 user stories (fields, view, automation)
        assert result.total_user_stories == 3

        # Verify TOML structure
        with open(generator.map_file, "rb") as f:
            data = tomllib.load(f)
            feature_data = data["features"]["Multi-Type Feature"]
            user_stories = feature_data["user_stories"]

            assert len(user_stories) == 3

            # User stories is now a dict with story name as key
            # Check that expected story names exist
            assert "Configure Custom Fields" in user_stories
            assert "Update Views" in user_stories
            assert "Set Up Automations" in user_stories

            # Each user story should have sequence defaulting to 1
            for story_name, story_data in user_stories.items():
                assert story_data.get("sequence") == 1

    def test_generate_map_component_references(
        self, generator, mock_feature_multiple_types
    ):
        """Test that component references use model-qualified format for
        fields."""
        features = [mock_feature_multiple_types]

        generator.generate_or_update_map(features, extraction_count=4)

        with open(generator.map_file, "rb") as f:
            data = tomllib.load(f)
            feature_data = data["features"]["Multi-Type Feature"]
            user_stories = feature_data["user_stories"]

            # User stories is now a dict - find the fields story by name
            assert "Configure Custom Fields" in user_stories
            fields_story = user_stories["Configure Custom Fields"]

            # Check component references use model-qualified format for fields (dict format with source_location)
            comp_refs = [c.get("ref") if isinstance(c, dict) else c for c in fields_story["components"]]
            assert "field.sale_order.x_field_1" in comp_refs
            assert "field.sale_order.x_field_2" in comp_refs
            # Also check that source_location field exists
            assert all(isinstance(c, dict) and "source_location" in c for c in fields_story["components"])

    def test_update_preserves_user_stories(self, generator, mock_feature):
        """Test that existing user stories are preserved on update."""
        # First generation
        features = [mock_feature]
        generator.generate_or_update_map(features, extraction_count=1)

        # Manually edit the file to add custom user stories
        content = generator.map_file.read_text()
        # The file should exist with default user stories

        # Second generation (update) - should preserve
        result = generator.generate_or_update_map(features, extraction_count=1)

        assert result.preserved_features == 1
        assert result.new_features == 0

    def test_marks_deprecated_features(self, generator, mock_feature):
        """Test that removed features are marked deprecated."""
        # First generation with feature
        features = [mock_feature]
        generator.generate_or_update_map(features, extraction_count=1)

        # Second generation without feature (removed)
        features = []
        result = generator.generate_or_update_map(features, extraction_count=0)

        # Feature should be in file but marked deprecated (commented)
        content = generator.map_file.read_text()
        assert "DEPRECATED" in content

    def test_toml_structure(self, generator, mock_feature):
        """Test generated TOML has correct structure."""
        features = [mock_feature]
        generator.generate_or_update_map(features, extraction_count=1)

        with open(generator.map_file, "rb") as f:
            data = tomllib.load(f)

        # Check required sections
        assert "metadata" in data
        assert "statistics" in data
        assert "features" in data
        assert "defaults" in data

        # Check metadata fields
        assert "generated_at" in data["metadata"]
        assert "extraction_count" in data["metadata"]
        assert "last_extract" in data["metadata"]

        # Check statistics fields
        assert "total_features" in data["statistics"]
        assert "total_user_stories" in data["statistics"]
        assert "total_components" in data["statistics"]

        # Check feature has user_stories dict (not list)
        feature_def = data["features"]["Test Feature"]
        assert "description" in feature_def
        assert "user_stories" in feature_def
        assert isinstance(feature_def["user_stories"], dict)

    def test_preview_map_does_not_write_file(self, generator, mock_feature):
        """Test preview_map returns stats without writing file."""
        features = [mock_feature]

        result = generator.preview_map(features, extraction_count=1)

        assert result.total_features == 1
        assert not generator.map_file.exists()

    def test_unassigned_components_have_sequence(self, generator, mock_feature):
        """New unassigned components should create a feature and story with sequence=1."""
        # First generation with initial feature
        generator.generate_or_update_map([mock_feature], extraction_count=1)

        # New extraction includes an unknown component not assigned anywhere
        new_comp = Component(
            id=99,
            name="x_new_field",
            display_name="New Field",
            component_type=ComponentType.FIELD,
            model="sale.order",
            complexity="simple",
            raw_data={},
        )

        new_feature = Mock()
        new_feature.name = "Another Feature"
        new_feature.description = "Another feature"
        new_feature.components = [new_comp]

        result = generator.generate_or_update_map([new_feature], extraction_count=2)

        # Should have added a new 'Unassigned Components' feature
        with open(generator.map_file, "rb") as f:
            data = tomllib.load(f)

        # Find unassigned feature name (localized string)
        unassigned = next(
            (name for name in data["features"].keys() if "Unassigned Components" in name),
            None,
        )

        assert unassigned is not None
        feat = data["features"][unassigned]
        assert feat.get("sequence") == 1
        # User stories is now a dict - get first story
        user_stories = feat["user_stories"]
        assert isinstance(user_stories, dict)
        for story_name, story_data in user_stories.items():
            assert story_data.get("sequence") == 1

    def test_multiple_features(
        self, generator, mock_feature, mock_feature_multiple_types
    ):
        """Test generation with multiple features."""
        features = [mock_feature, mock_feature_multiple_types]

        result = generator.generate_or_update_map(features, extraction_count=5)

        assert result.total_features == 2

        # Verify all in TOML
        with open(generator.map_file, "rb") as f:
            data = tomllib.load(f)
            assert len(data["features"]) == 2
            assert "Test Feature" in data["features"]
            assert "Multi-Type Feature" in data["features"]

    def test_load_existing_map(self, generator, mock_feature):
        """Test loading existing map."""
        # Generate map first
        features = [mock_feature]
        generator.generate_or_update_map(features, extraction_count=1)

        # Load it
        existing = generator._load_existing_map()

        assert existing is not None
        assert "metadata" in existing
        assert "features" in existing
        assert "Test Feature" in existing["features"]

    def test_load_existing_map_not_found(self, generator):
        """Test loading when map doesn't exist."""
        existing = generator._load_existing_map()
        assert existing is None

    def test_component_to_reference(self, generator):
        """Test component reference format uses model qualification for
        fields."""
        comp = Component(
            id=1,
            name="x_credit_limit",
            display_name="Credit Limit",
            component_type=ComponentType.FIELD,
            model="res.partner",
            complexity="simple",
            raw_data={},
        )

        result = generator._component_to_reference(comp)
        # Should return dict with ref and source_location
        assert isinstance(result, dict)
        assert result["ref"] == "field.res_partner.x_credit_limit"
        assert "source_location" in result

    def test_component_to_reference_view(self, generator):
        """Test view component reference format with model qualification."""
        comp = Component(
            id=2,
            name="partner_credit_form",
            display_name="Partner Credit Form",
            component_type=ComponentType.VIEW,
            model="res.partner",
            complexity="medium",
            raw_data={},
        )

        result = generator._component_to_reference(comp)
        # Should return dict with ref and source_location
        assert isinstance(result, dict)
        assert result["ref"] == "view.res_partner.partner_credit_form"
        assert "source_location" in result
