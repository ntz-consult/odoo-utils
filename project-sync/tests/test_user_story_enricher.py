"""Tests for the User Story Enricher module.

Tests the TOML-based approach where the enricher reads directly from
feature_user_story_map.toml and uses source_location to access source files.
Enriched descriptions are written to Odoo task descriptions (HTML format).
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "shared" / "python"))

from user_story_enricher import (
    TomlLoader,
    TomlComponent,
    TomlUserStory,
    TomlFeature,
    UserStoryGenerator,
    MarkdownGenerator,
    OdooHtmlGenerator,
    UserStoryEnricher,
)
from enricher_config import EnricherConfig, UserStoryEnricherConfig
from ai_providers.base import AIResponse


@pytest.fixture
def test_project_root():
    """Get path to test project with TOML and source files."""
    return Path(__file__).parent / "fixtures" / "enricher_test_project"


@pytest.fixture
def config():
    """Create test configuration."""
    return EnricherConfig.default()


class TestTomlComponent:
    """Tests for TomlComponent dataclass."""
    
    def test_from_string_ref(self, test_project_root):
        """Test creating component from string reference."""
        comp = TomlComponent.from_toml_item("field.sale_order.x_test", test_project_root)
        
        assert comp.ref == "field.sale_order.x_test"
        assert comp.component_type == "field"
        assert comp.model == "sale.order"
        assert comp.name == "x_test"
        assert comp.source_location is None
        assert comp.source_content is None
    
    def test_from_dict_with_source_location(self, test_project_root):
        """Test creating component from dict with source_location."""
        item = {
            "ref": "field.sale_order_line.x_weight",
            "source_location": "models/sale_order.py",
        }
        comp = TomlComponent.from_toml_item(item, test_project_root)
        
        assert comp.ref == "field.sale_order_line.x_weight"
        assert comp.source_location == "models/sale_order.py"
        assert comp.source_content is not None  # File should exist
        assert "class" in comp.source_content or "def" in comp.source_content
    
    def test_source_content_missing_file(self, test_project_root):
        """Test that missing source file results in None source_content."""
        item = {
            "ref": "field.test.x_missing",
            "source_location": "nonexistent/file.py",
        }
        comp = TomlComponent.from_toml_item(item, test_project_root)
        
        assert comp.source_location == "nonexistent/file.py"
        assert comp.source_content is None


class TestTomlLoader:
    """Tests for TomlLoader."""
    
    def test_load_features(self, test_project_root):
        """Test loading features from TOML."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        
        assert len(features) == 3
        
        # Check sorted by sequence
        assert features[0].name == "Sales Order Customizations"
        assert features[0].sequence == 1
    
    def test_load_user_stories(self, test_project_root):
        """Test loading user stories within features."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        
        sales_feature = features[0]
        assert len(sales_feature.user_stories) == 2
        # In new structure, name is the key and description is a property
        assert sales_feature.user_stories[0].name == "Dual UoM Support"
        # The fixture has structured descriptions with Who/What/Why/How format
        assert "sales representative" in sales_feature.user_stories[0].description.lower()
    
    def test_load_components_with_source_location(self, test_project_root):
        """Test loading components with source_location."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        
        sales_feature = features[0]
        first_story = sales_feature.user_stories[0]
        
        # Should have 3 components with source_location
        assert len(first_story.components) == 3
        for comp in first_story.components:
            assert comp.source_location == "models/sale_order.py"
    
    def test_load_components_without_source_location(self, test_project_root):
        """Test loading components without source_location (string format)."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        
        # Find "No Source Components" feature
        no_source_feature = next(f for f in features if "No Source" in f.name)
        first_story = no_source_feature.user_stories[0]
        
        # Components should have no source_location (False or None are falsy)
        assert len(first_story.components) == 2
        for comp in first_story.components:
            assert not comp.source_location  # Accept both None and False as "no source"
    
    def test_missing_toml_file(self, tmp_path):
        """Test error when TOML file is missing."""
        loader = TomlLoader(tmp_path)
        
        with pytest.raises(ValueError) as exc_info:
            loader.load_features()
        
        assert "not found" in str(exc_info.value)


class TestTomlFeature:
    """Tests for TomlFeature dataclass."""
    
    def test_primary_model(self, test_project_root):
        """Test primary model detection."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        
        sales_feature = features[0]
        assert sales_feature.primary_model == "sale.order.line"
    
    def test_domain(self, test_project_root):
        """Test domain detection from model."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        
        sales_feature = features[0]
        # sale.order.line maps to Sales via the MODEL_DOMAIN_MAP
        assert sales_feature.domain == "Sales"


class TestUserStoryGenerator:
    """Tests for UserStoryGenerator."""
    
    @pytest.fixture
    def mock_provider(self):
        """Create a mock AI provider."""
        provider = MagicMock()
        provider.generate.return_value = AIResponse(
            content="""**Feature Description:** This feature enables dual unit of measure support for sales orders, allowing tracking of quantities in both primary and secondary units.

### User Story: Dual UoM Support

**Description:** - Who: Sales Representative
- What: Enter quantities in secondary units of measure
- Why: To work with customer-preferred units and improve accuracy
- How (Acceptance Criteria):
  - Secondary UoM field is visible on order line
  - Quantity converts automatically
  - Weight is calculated correctly

### User Story: Calculate Weights Action

**Description:** - Who: Sales Representative
- What: Calculate weights automatically
- Why: To reduce manual calculation errors
- How (Acceptance Criteria):
  - Weights are calculated when action is triggered
  - Totals are updated correctly
""",
            model="test-model",
            provider="test",
            usage={"total_tokens": 100},
        )
        return provider
    
    def test_enrich_feature(self, mock_provider, config, test_project_root):
        """Test enriching a feature with AI-generated content."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        
        generator = UserStoryGenerator(mock_provider, config.user_story_enricher)
        enriched = generator.enrich_feature(features[0])
        
        # Feature description should be enriched
        assert "dual unit" in enriched.description.lower()
        assert enriched.ai_enriched is True
        
        # Check user story description was enriched (not the name)
        story = enriched.user_stories[0]
        assert story.name == "Dual UoM Support"  # Name preserved
        assert "Sales Representative" in story.description  # Description enriched
        assert story.ai_enriched is True
    
    def test_fallback_on_ai_error(self, config, test_project_root):
        """Test fallback enrichment when AI fails."""
        from ai_providers.base import AIProviderError
        
        provider = MagicMock()
        provider.generate.side_effect = AIProviderError("Test error")
        
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        
        generator = UserStoryGenerator(provider, config.user_story_enricher)
        enriched = generator.enrich_feature(features[0])
        
        # Should have fallback content in description
        assert enriched.goal is not None
        assert enriched.ai_enriched is False
        
        for story in enriched.user_stories:
            # Fallback creates structured description using story.name
            assert story.name in story.description  # Story name appears in description
            assert story.ai_enriched is True  # Fallback still marks as enriched


class TestMarkdownGenerator:
    """Tests for MarkdownGenerator."""
    
    def test_generate_markdown(self, config, test_project_root):
        """Test generating markdown from enriched features."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        
        # Apply fallback enrichment for testing
        for feature in features:
            feature.goal = f"Implement {feature.name}"
            for story in feature.user_stories:
                story.role = "User"
                story.goal = "complete the workflow"
                story.benefit = "work is done efficiently"
                story.acceptance_criteria = ["Functionality works"]
        
        generator = MarkdownGenerator(config.user_story_enricher)
        markdown = generator.generate(features, "Test Project")
        
        assert "# Test Project - Implementation TODO" in markdown
        assert "## Summary" in markdown
        assert "## Feature: Sales Order Customizations" in markdown
        assert "### User Story" in markdown
        assert "**Components:**" in markdown
    
    def test_ai_generated_marker(self, config, test_project_root):
        """Test AI-generated content marker."""
        config.user_story_enricher.mark_ai_generated = True
        
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        
        # Mark as AI enriched
        for feature in features:
            feature.ai_enriched = True
            feature.goal = "Test goal"
        
        generator = MarkdownGenerator(config.user_story_enricher)
        markdown = generator.generate(features, "Test")
        
        assert "[AI-Enriched]" in markdown or "AI" in markdown


class TestUserStoryEnricherIntegration:
    """Integration tests for UserStoryEnricher."""
    
    def test_dry_run(self, config, test_project_root):
        """Test dry run mode."""
        enricher = UserStoryEnricher(config)
        result = enricher.enrich(test_project_root, dry_run=True)
        
        assert "Dry Run Preview" in result
        assert "Sales Order Customizations" in result
        assert "✓ has source" in result  # Components with source_location
        assert "✗ no source" in result  # Components without source_location
    
    def test_enrich_with_mock_provider(self, config, test_project_root):
        """Test full enrichment with mocked AI provider."""
        mock_provider = MagicMock()
        mock_provider.generate.return_value = AIResponse(
            content="""**Feature Goal:** Enhance sales functionality

### User Story: Dual UoM Support

* **Role:** Sales Rep
* **Goal:** track secondary units
* **Benefit:** billing is accurate
* **Acceptance Criteria:**
  * Field is visible
  * Calculations work
""",
            model="test-model",
            provider="test",
            usage={},
        )
        
        enricher = UserStoryEnricher(config, provider=mock_provider)
        result = enricher.enrich(test_project_root)
        
        # Should have enriched content
        assert "Implementation TODO" in result
        assert "Feature:" in result
        
        # AI provider should have been called for each feature
        assert mock_provider.generate.call_count >= 1
    
    def test_enrich_and_save_deprecated(self, config, test_project_root, tmp_path):
        """Test that enrich_and_save is deprecated and redirects to enrich_in_place."""
        import warnings
        
        mock_provider = MagicMock()
        mock_provider.generate.return_value = AIResponse(
            content="**Feature Goal:** Test goal\n\n### User Story: Test\n\n* **Role:** User\n* **Goal:** test\n* **Benefit:** works\n* **Acceptance Criteria:**\n  * Works",
            model="test",
            provider="test",
            usage={},
        )
        
        enricher = UserStoryEnricher(config, provider=mock_provider)
        
        # Should raise a deprecation warning
        # Note: now requires OdooClient for non-dry-run, so we expect ValueError
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # The method is deprecated and redirects to enrich_in_place which requires OdooClient
            try:
                result = enricher.enrich_and_save(test_project_root)
            except ValueError as e:
                # Expected since OdooClient is required for non-dry-run
                assert "OdooClient is required" in str(e)
                # Should still have raised deprecation warning before the error
                assert len(w) == 1
                assert issubclass(w[0].category, DeprecationWarning)
                assert "enrich_in_place" in str(w[0].message)
                return
            
            # If we get here without ValueError, it must be dry_run mode
            assert isinstance(result, dict)


class TestOdooHtmlGenerator:
    """Tests for OdooHtmlGenerator - HTML generation for Odoo task descriptions."""
    
    def test_generate_feature_html(self, test_project_root):
        """Test generating HTML for a feature task description."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        feature = features[0]
        feature.description = "A comprehensive feature for sales management."
        
        html = OdooHtmlGenerator.generate_feature_html(feature)
        
        assert "<h2" in html
        assert "📋" in html
        assert feature.name in html
        assert "blockquote" in html or "Business Requirement" in html
        assert feature.description in html
        assert "<table" in html  # User stories table
        assert "style=" in html  # Has inline styles
    
    def test_generate_user_story_html(self, test_project_root):
        """Test generating HTML for a user story task description."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        story = features[0].user_stories[0]
        story.description = "- Who: Sales Rep\n- What: Enter quantities\n- Why: Accurate billing\n- How:\n  - Field is visible\n  - Values update"
        
        html = OdooHtmlGenerator.generate_user_story_html(story, "Sales Feature")
        
        assert "<h2" in html
        assert "📋" in html
        assert story.name in html
        assert "Sales Feature" in html  # Parent feature reference
        assert "Business Requirement" in html
        assert "<table" in html  # Components table
        assert "style=" in html  # Has inline styles
    
    def test_html_escaping(self):
        """Test that HTML special characters are escaped."""
        story = TomlUserStory(
            name="Test <script>alert('xss')</script>",
            description="Test & description with <html>",
            sequence=1,
            components=[],
        )
        
        html = OdooHtmlGenerator.generate_user_story_html(story)
        
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "&amp;" in html
    
    def test_error_html_constant(self):
        """Test the error HTML constant for failed enrichment."""
        error_html = OdooHtmlGenerator.ERROR_HTML
        
        assert "ENRICHMENT FAILED" in error_html
        assert "style=" in error_html  # Has inline styles
        assert "color" in error_html  # Has color styling
    
    def test_structured_description_parsing(self):
        """Test parsing of structured Who/What/Why/How descriptions."""
        story = TomlUserStory(
            name="Test Story",
            description="- Who: Administrator\n- What: Configure settings\n- Why: System works correctly\n- How (Acceptance Criteria):\n  - Setting A works\n  - Setting B works",
            sequence=1,
            components=[],
        )
        
        html = OdooHtmlGenerator.generate_user_story_html(story)
        
        assert "Who" in html
        assert "Administrator" in html
        assert "What" in html
        assert "Why" in html
        assert "Acceptance Criteria" in html
        assert "<ul" in html
        assert "<li" in html
    
    def test_components_table_generation(self, test_project_root):
        """Test component table generation with complexity and time."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        story = features[0].user_stories[0]
        
        # Add complexity and time to components
        for comp in story.components:
            comp.complexity = "Medium"
            comp.time_estimate = "1:30"
            comp.completion = "50%"
        
        html = OdooHtmlGenerator.generate_user_story_html(story)
        
        assert "<table" in html
        assert "Status" in html
        assert "Component" in html
        assert "Complexity" in html
        assert "Estimate" in html  # Changed from "Hours" to "Estimate"
        assert "1:30" in html
        assert "Total Estimate" in html  # Check for new total label
        assert "Total Actual" in html  # Check for new total label
        # Check for complexity badge styling
        assert "background-color" in html
    
    def test_feature_html_without_stories_table(self, test_project_root):
        """Test feature HTML generation without stories table."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        feature = features[0]
        
        html = OdooHtmlGenerator.generate_feature_html(
            feature, 
            include_user_stories_table=False
        )
        
        assert "<h2" in html
        assert "📋" in html
        assert "User Stories" not in html
    
    def test_complexity_badge_colors(self):
        """Test that complexity badges have different colors."""
        story = TomlUserStory(
            name="Test",
            description="Test",
            sequence=1,
            components=[],
        )
        
        # Test different complexity levels get different badge styles
        simple_badge = OdooHtmlGenerator._get_complexity_badge("simple")
        medium_badge = OdooHtmlGenerator._get_complexity_badge("medium")
        complex_badge = OdooHtmlGenerator._get_complexity_badge("complex")
        
        assert "#afece7" in simple_badge  # Icy Aqua (palette)
        assert "#af2e00" in medium_badge  # Rusty Spice (palette)
        assert "#003339" in complex_badge  # Dark Teal (palette)


class TestOdooHtmlGeneratorWithTimesheets:
    """Tests for OdooHtmlGenerator with timesheet integration."""
    
    def test_stories_table_with_timesheet_data(self, test_project_root):
        """Test feature-level stories table with actual hours from timesheets."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        feature = features[0]
        
        # Set task_ids on stories
        feature.user_stories[0].task_id = 101
        feature.user_stories[1].task_id = 102
        
        # Add time estimates to components
        for story in feature.user_stories:
            for comp in story.components:
                comp.time_estimate = "2:30"
                comp.complexity = "Medium"
        
        # Mock timesheet data
        timesheet_data = {
            101: 3.5,  # 3 hours 30 minutes
            102: 1.25,  # 1 hour 15 minutes
        }
        
        html = OdooHtmlGenerator._generate_stories_table(
            feature.user_stories,
            timesheet_data=timesheet_data,
            feature_task_id=0,
        )
        
        assert "<table" in html
        assert "Estimate" in html
        assert "Actual" in html
        assert "03:30" in html  # Story 1 actual
        assert "01:15" in html  # Story 2 actual
        # Check total row exists
        assert "Total" in html
    
    def test_stories_table_with_feature_level_time(self, test_project_root):
        """Test feature-level stories table with 'Time at feature level' row."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        feature = features[0]
        feature.task_id = 100
        
        # Set task_ids on stories
        feature.user_stories[0].task_id = 101
        feature.user_stories[1].task_id = 102
        
        # Add time estimates
        for story in feature.user_stories:
            for comp in story.components:
                comp.time_estimate = "1:00"
                comp.complexity = "Simple"
        
        # Mock timesheet data including feature-level time
        timesheet_data = {
            100: 2.0,  # 2 hours at feature level
            101: 1.0,  # 1 hour on story 1
            102: 0.5,  # 30 minutes on story 2
        }
        
        html = OdooHtmlGenerator._generate_stories_table(
            feature.user_stories,
            timesheet_data=timesheet_data,
            feature_task_id=100,
        )
        
        assert "Time at feature level" in html
        assert "02:00" in html  # Feature-level actual time
        # Check that total includes feature-level time: 1.0 + 0.5 + 2.0 = 3.5 hours
        assert "03:30" in html  # Total actual should be 3 hours 30 minutes
    
    def test_components_table_with_total_actual(self, test_project_root):
        """Test story-level components table with Total Actual row."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        story = features[0].user_stories[0]
        story.task_id = 101
        
        # Add time estimates to components
        for comp in story.components:
            comp.time_estimate = "1:30"
            comp.complexity = "Medium"
        
        # Mock timesheet data
        timesheet_data = {
            101: 4.75,  # 4 hours 45 minutes actual
        }
        
        html = OdooHtmlGenerator._generate_components_table(
            story.components,
            timesheet_data=timesheet_data,
            story_task_id=101,
        )
        
        assert "<table" in html
        assert "Estimate" in html
        assert "Total Estimate" in html
        assert "Total Actual" in html
        assert "04:45" in html  # Actual time
    
    def test_generate_feature_html_with_timesheets(self, test_project_root):
        """Test complete feature HTML generation with timesheet data."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        feature = features[0]
        feature.task_id = 100
        
        for story in feature.user_stories:
            story.task_id = 101
            for comp in story.components:
                comp.time_estimate = "1:00"
                comp.complexity = "Simple"
        
        timesheet_data = {100: 1.5, 101: 2.0}
        
        html = OdooHtmlGenerator.generate_feature_html(
            feature,
            timesheet_data=timesheet_data,
        )
        
        assert "Estimate" in html
        assert "Actual" in html
        assert "01:30" in html or "02:00" in html
    
    def test_generate_user_story_html_with_timesheets(self, test_project_root):
        """Test complete user story HTML generation with timesheet data."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        story = features[0].user_stories[0]
        story.task_id = 101
        
        for comp in story.components:
            comp.time_estimate = "2:00"
            comp.complexity = "Medium"
        
        timesheet_data = {101: 5.5}
        
        html = OdooHtmlGenerator.generate_user_story_html(
            story,
            feature_name="Test Feature",
            timesheet_data=timesheet_data,
        )
        
        assert "Total Estimate" in html
        assert "Total Actual" in html
        assert "05:30" in html
    
    def test_timesheets_graceful_degradation(self, test_project_root):
        """Test that missing timesheet data shows 00:00."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        story = features[0].user_stories[0]
        story.task_id = 999  # Non-existent task
        
        for comp in story.components:
            comp.time_estimate = "1:00"
        
        # Empty timesheet data
        timesheet_data = {}
        
        html = OdooHtmlGenerator._generate_components_table(
            story.components,
            timesheet_data=timesheet_data,
            story_task_id=999,
        )
        
        # Should display 00:00 for actual when no data
        assert "Total Actual" in html
        assert "00:00" in html
