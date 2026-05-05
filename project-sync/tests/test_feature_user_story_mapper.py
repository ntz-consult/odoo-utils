"""Tests for feature_user_story_mapper module."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from feature_detector import Component, ComponentType, UserStory
from feature_user_story_mapper import FeatureUserStoryMapper


class TestFeatureUserStoryMapper:
    """Tests for FeatureUserStoryMapper class."""

    @pytest.fixture
    def temp_project(self, tmp_path):
        """Create temporary project directory."""
        return tmp_path

    @pytest.fixture
    def sample_toml_simple(self, temp_project):
        """Create sample TOML with simple user stories."""
        map_file = temp_project / "feature_user_story_map.toml"
        content = """
[metadata]
generated_at = "2025-12-13T10:00:00"
extraction_count = 10

[statistics]
total_features = 1
total_user_stories = 2
total_components = 4

[features."Test Feature"]
description = "Test feature"
user_stories = [
    { description = "Configure Custom Fields", components = [
        "field.x_approval_status",
        "field.x_approval_date",
    ] },
    { description = "Update Views", components = [
        "view.sale_order_approval_view",
    ] },
]

[defaults]
min_user_story_components = 1
max_user_story_components = 10
"""
        map_file.write_text(content)
        return map_file

    @pytest.fixture
    def sample_toml_deprecated(self, temp_project):
        """Create sample TOML with deprecated feature."""
        map_file = temp_project / "feature_user_story_map.toml"
        content = """
[metadata]
generated_at = "2025-12-13T10:00:00"
extraction_count = 10

[statistics]
total_features = 1
total_user_stories = 1
total_components = 2

[features."Deprecated Feature"]
description = "Old feature [DEPRECATED - not in latest extraction]"
_deprecated = true
user_stories = [
    { description = "Old Task", components = [
        "field.x_old_field",
    ] },
]

[defaults]
min_user_story_components = 1
"""
        map_file.write_text(content)
        return map_file

    @pytest.fixture
    def sample_toml_empty_stories(self, temp_project):
        """Create sample TOML with empty user_stories."""
        map_file = temp_project / "feature_user_story_map.toml"
        content = """
[metadata]
generated_at = "2025-12-13T10:00:00"

[statistics]
total_features = 1
total_user_stories = 0

[features."Empty Feature"]
description = "Feature with no user stories"
user_stories = []

[defaults]
min_user_story_components = 1
"""
        map_file.write_text(content)
        return map_file

    @pytest.fixture
    def mock_components(self):
        """Create mock components."""
        return [
            Component(
                id=1,
                name="x_approval_status",
                display_name="Approval Status",
                component_type=ComponentType.FIELD,
                model="sale.order",
                complexity="simple",
                raw_data={},
            ),
            Component(
                id=2,
                name="x_approval_date",
                display_name="Approval Date",
                component_type=ComponentType.FIELD,
                model="sale.order",
                complexity="simple",
                raw_data={},
            ),
            Component(
                id=3,
                name="sale_order_approval_view",
                display_name="Sale Order Approval View",
                component_type=ComponentType.VIEW,
                model="sale.order",
                complexity="medium",
                raw_data={},
            ),
            Component(
                id=4,
                name="x_other_field",
                display_name="Other Field",
                component_type=ComponentType.FIELD,
                model="sale.order",
                complexity="simple",
                raw_data={},
            ),
        ]

    @pytest.fixture
    def mock_feature(self, mock_components):
        """Create mock feature."""
        feature = Mock()
        feature.name = "Test Feature"
        feature.description = "Test feature"
        feature.components = mock_components
        return feature

    @pytest.fixture
    def mock_estimator(self):
        """Create mock estimator."""
        estimator = Mock()

        # Mock estimate_component to return a simple breakdown
        def mock_estimate(component):
            breakdown = Mock()
            breakdown.total = 1.0
            return breakdown

        estimator.estimate_component = mock_estimate

        # Mock _create_default_user_stories
        def mock_default_stories(feature):
            return [
                UserStory(
                    title="Default Story",
                    description="Default grouping",
                    components=feature.components,
                    estimated_hours=len(feature.components) * 1.0,
                )
            ]

        estimator._create_default_user_stories = mock_default_stories

        return estimator

    def test_mapper_initialization(self, sample_toml_simple):
        """Test mapper initialization."""
        mapper = FeatureUserStoryMapper(sample_toml_simple)
        assert mapper.map_file == sample_toml_simple
        assert mapper._map_data is None

    def test_load_map(self, sample_toml_simple):
        """Test loading map."""
        mapper = FeatureUserStoryMapper(sample_toml_simple)
        features = mapper.load_map()

        assert "Test Feature" in features
        assert features["Test Feature"]["description"] == "Test feature"
        assert len(features["Test Feature"]["user_stories"]) == 2

    def test_load_map_not_found(self, temp_project):
        """Test loading when map doesn't exist."""
        mapper = FeatureUserStoryMapper(temp_project / "nonexistent.toml")

        with pytest.raises(
            ValueError, match="Feature-user story map not found"
        ):
            mapper.load_map()

    def test_validate_map_valid(self, sample_toml_simple):
        """Test validation passes for valid map."""
        mapper = FeatureUserStoryMapper(sample_toml_simple)
        warnings = mapper.validate_map()

        assert warnings == []

    def test_validate_map_detects_deprecated(self, sample_toml_deprecated):
        """Test validation warns for deprecated features."""
        mapper = FeatureUserStoryMapper(sample_toml_deprecated)
        warnings = mapper.validate_map()

        assert len(warnings) == 1
        assert "DEPRECATED" in warnings[0]

    def test_validate_map_detects_empty_stories(
        self, sample_toml_empty_stories
    ):
        """Test validation warns for empty user_stories."""
        mapper = FeatureUserStoryMapper(sample_toml_empty_stories)
        warnings = mapper.validate_map()

        assert len(warnings) == 1
        assert "no user stories" in warnings[0]

    def test_get_user_stories_from_map(
        self, sample_toml_simple, mock_feature, mock_estimator
    ):
        """Test getting user stories from map."""
        mapper = FeatureUserStoryMapper(sample_toml_simple)

        stories = mapper.get_user_stories_for_feature(
            mock_feature, mock_estimator
        )

        # Should have 3 stories: 2 from map + 1 "Other Components" for unmatched
        assert len(stories) == 3

        # Check story names
        story_titles = {s.title for s in stories}
        assert "Configure Custom Fields" in story_titles
        assert "Update Views" in story_titles
        assert "Other Components" in story_titles

    def test_get_user_stories_fields_matched(
        self, sample_toml_simple, mock_feature, mock_estimator
    ):
        """Test that fields are matched to correct user story."""
        mapper = FeatureUserStoryMapper(sample_toml_simple)

        stories = mapper.get_user_stories_for_feature(
            mock_feature, mock_estimator
        )

        # Find "Configure Custom Fields" story
        fields_story = next(
            s for s in stories if s.title == "Configure Custom Fields"
        )

        # Should have 2 field components
        assert len(fields_story.components) == 2
        component_names = {c.name for c in fields_story.components}
        assert "x_approval_status" in component_names
        assert "x_approval_date" in component_names

    def test_get_user_stories_view_matched(
        self, sample_toml_simple, mock_feature, mock_estimator
    ):
        """Test that view is matched to correct user story."""
        mapper = FeatureUserStoryMapper(sample_toml_simple)

        stories = mapper.get_user_stories_for_feature(
            mock_feature, mock_estimator
        )

        # Find "Update Views" story
        views_story = next(s for s in stories if s.title == "Update Views")

        # Should have 1 view component
        assert len(views_story.components) == 1
        assert views_story.components[0].name == "sale_order_approval_view"

    def test_unmatched_components_go_to_other(
        self, sample_toml_simple, mock_feature, mock_estimator
    ):
        """Test that unmatched components go to 'Other Components'."""
        mapper = FeatureUserStoryMapper(sample_toml_simple)

        stories = mapper.get_user_stories_for_feature(
            mock_feature, mock_estimator
        )

        # Find "Other Components" story
        other_story = next(s for s in stories if s.title == "Other Components")

        # Should have 1 unmatched component (x_other_field)
        assert len(other_story.components) == 1
        assert other_story.components[0].name == "x_other_field"

    def test_get_user_stories_falls_back_to_default(
        self, sample_toml_simple, mock_estimator
    ):
        """Test fallback to default when feature not in map."""
        mapper = FeatureUserStoryMapper(sample_toml_simple)

        # Feature not in map
        unknown_feature = Mock()
        unknown_feature.name = "Unknown Feature"
        unknown_feature.components = [
            Component(
                id=99,
                name="x_unknown",
                display_name="Unknown",
                component_type=ComponentType.FIELD,
                model="sale.order",
                complexity="simple",
                raw_data={},
            )
        ]

        stories = mapper.get_user_stories_for_feature(
            unknown_feature, mock_estimator
        )

        # Should use default grouping
        assert len(stories) == 1
        assert stories[0].title == "Default Story"

    def test_get_user_stories_deprecated_uses_default(
        self, sample_toml_deprecated, mock_estimator
    ):
        """Test deprecated feature falls back to default."""
        mapper = FeatureUserStoryMapper(sample_toml_deprecated)

        deprecated_feature = Mock()
        deprecated_feature.name = "Deprecated Feature"
        deprecated_feature.components = [
            Component(
                id=1,
                name="x_old_field",
                display_name="Old Field",
                component_type=ComponentType.FIELD,
                model="sale.order",
                complexity="simple",
                raw_data={},
            )
        ]

        stories = mapper.get_user_stories_for_feature(
            deprecated_feature, mock_estimator
        )

        # Should use default grouping (deprecated features ignored)
        assert len(stories) == 1
        assert stories[0].title == "Default Story"

    def test_get_all_features(self, sample_toml_simple):
        """Test getting all feature names."""
        mapper = FeatureUserStoryMapper(sample_toml_simple)
        features = mapper.get_all_features()

        assert features == ["Test Feature"]

    def test_get_all_features_excludes_deprecated(
        self, sample_toml_deprecated
    ):
        """Test that deprecated features are excluded."""
        mapper = FeatureUserStoryMapper(sample_toml_deprecated)
        features = mapper.get_all_features()

        assert features == []

    def test_get_statistics(self, sample_toml_simple):
        """Test getting statistics from map."""
        mapper = FeatureUserStoryMapper(sample_toml_simple)
        stats = mapper.get_statistics()

        assert stats["total_features"] == 1
        assert stats["total_user_stories"] == 2
        assert stats["total_components"] == 4

    def test_case_insensitive_component_matching(
        self, temp_project, mock_estimator
    ):
        """Test component matching is case-insensitive."""
        map_file = temp_project / "feature_user_story_map.toml"
        content = """
[metadata]
generated_at = "2025-12-13T10:00:00"

[statistics]
total_features = 1

[features."Test Feature"]
description = "Test"
user_stories = [
    { description = "Fields", components = [
        "field.X_APPROVAL_STATUS",
    ] },
]

[defaults]
min_user_story_components = 1
"""
        map_file.write_text(content)

        mapper = FeatureUserStoryMapper(map_file)

        feature = Mock()
        feature.name = "Test Feature"
        feature.components = [
            Component(
                id=1,
                name="x_approval_status",
                display_name="Approval Status",
                component_type=ComponentType.FIELD,
                model="sale.order",
                complexity="simple",
                raw_data={},
            )
        ]

        stories = mapper.get_user_stories_for_feature(feature, mock_estimator)

        # Should match despite case difference
        fields_story = next((s for s in stories if s.title == "Fields"), None)
        assert fields_story is not None
        assert len(fields_story.components) == 1

    def test_component_lookup_by_display_name(
        self, temp_project, mock_estimator
    ):
        """Test component can be matched by display_name."""
        map_file = temp_project / "feature_user_story_map.toml"
        content = """
[metadata]
generated_at = "2025-12-13T10:00:00"

[statistics]
total_features = 1

[features."Test Feature"]
description = "Test"
user_stories = [
    { description = "Views", components = [
        "view.Custom Sale Order View",
    ] },
]

[defaults]
min_user_story_components = 1
"""
        map_file.write_text(content)

        mapper = FeatureUserStoryMapper(map_file)

        feature = Mock()
        feature.name = "Test Feature"
        feature.components = [
            Component(
                id=1,
                name="sale_order_view_custom",
                display_name="Custom Sale Order View",
                component_type=ComponentType.VIEW,
                model="sale.order",
                complexity="medium",
                raw_data={},
            )
        ]

        stories = mapper.get_user_stories_for_feature(feature, mock_estimator)

        views_story = next((s for s in stories if s.title == "Views"), None)
        assert views_story is not None
        assert len(views_story.components) == 1
