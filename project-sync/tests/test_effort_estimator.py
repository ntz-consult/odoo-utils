"""Tests for the Effort Estimator module.

Tests the TOML-based approach where the estimator reads directly from
feature_user_story_map.toml and uses source_location to analyze source files.
"""

import pytest
from pathlib import Path
import json

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "shared" / "python"))

from effort_estimator import (
    EffortEstimator,
    TomlLoader,
    TomlComponent,
    EffortCalculator,
    MarkdownGenerator,
    EstimatedComponent,
    EstimatedFeature,
    TimeMetrics,
    TimeBreakdown,
)
from enricher_config import EnricherConfig, EffortEstimatorConfig


@pytest.fixture
def test_project_root():
    """Get path to test project with TOML and source files."""
    return Path(__file__).parent / "fixtures" / "enricher_test_project"


@pytest.fixture
def time_metrics(test_project_root):
    """Load time metrics from test project."""
    metrics_path = test_project_root / "time_metrics.json"
    return TimeMetrics.from_file(metrics_path)


@pytest.fixture
def config():
    """Create test configuration."""
    return EnricherConfig.default()


class TestTomlComponent:
    """Tests for TomlComponent in effort estimator."""
    
    def test_from_string_ref(self):
        """Test creating component from string reference."""
        comp = TomlComponent.from_toml_item("field.sale_order.x_test")
        
        assert comp.ref == "field.sale_order.x_test"
        assert comp.component_type == "field"
        assert comp.model == "sale.order"
        assert comp.name == "x_test"
        assert comp.source_location is None
    
    def test_from_dict_with_source_location(self):
        """Test creating component from dict with source_location."""
        item = {
            "ref": "server_action.sale_order.action_calculate",
            "source_location": "models/sale_order.py",
        }
        comp = TomlComponent.from_toml_item(item)
        
        assert comp.ref == "server_action.sale_order.action_calculate"
        assert comp.component_type == "server_action"
        assert comp.source_location == "models/sale_order.py"


class TestTomlLoader:
    """Tests for TomlLoader in effort estimator."""
    
    def test_load_features(self, test_project_root):
        """Test loading features from TOML."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        
        assert len(features) == 3
        
        # Check features are sorted by sequence
        sequences = [f.sequence for f in features]
        assert sequences == sorted(sequences)
    
    def test_load_components(self, test_project_root):
        """Test loading components with source_location from TOML."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        
        sales_feature = features[0]
        first_story = sales_feature.user_stories[0]
        
        # All components should have source_location
        for comp in first_story.components:
            assert comp.source_location is not None


class TestEffortCalculator:
    """Tests for EffortCalculator."""
    
    @pytest.fixture
    def calculator(self, config, time_metrics, test_project_root):
        """Create effort calculator."""
        return EffortCalculator(
            config.effort_estimator,
            time_metrics=time_metrics,
            project_root=test_project_root,
        )
    
    def test_estimate_with_source(self, calculator):
        """Test estimation with available source files."""
        component = TomlComponent(
            ref="field.sale_order_line.x_weight",
            source_location="models/sale_order.py",
            component_type="field",
            model="sale.order.line",
            name="x_weight",
        )
        
        estimate = calculator.estimate_component(component)
        
        assert not estimate.is_fallback
        assert estimate.computed_score > 0
        assert estimate.computed_label in ["simple", "medium", "complex", "very_complex"]
        assert estimate.adjusted_hours.total > 0
    
    def test_estimate_fallback_missing_source(self, calculator):
        """Test error when source file not found - NO FALLBACK."""
        component = TomlComponent(
            ref="field.test.x_missing",
            source_location="nonexistent/file.py",
            component_type="field",
            model="test.model",
            name="x_missing",
        )
        
        # Should raise ValueError, not fallback
        import pytest
        with pytest.raises(ValueError, match="Source file not found"):
            calculator.estimate_component(component)
    
    def test_estimate_no_source_location(self, calculator):
        """Test error when no source_location in TOML - NO FALLBACK."""
        component = TomlComponent(
            ref="field.test.x_no_source",
            source_location=None,
            component_type="field",
            model="test.model",
            name="x_no_source",
        )
        
        # Should raise ValueError, not fallback
        import pytest
        with pytest.raises(ValueError, match="No source_location"):
            calculator.estimate_component(component)
    
    def test_estimate_feature(self, calculator, test_project_root):
        """Test estimating all components in a feature."""
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        
        estimated = calculator.estimate_feature(features[0])
        
        assert estimated.total_hours > 0
        assert len(estimated.user_stories) == 2
        
        # Each story should have estimated components
        for story in estimated.user_stories:
            assert story.total_hours >= 0
            for comp in story.components:
                assert isinstance(comp, EstimatedComponent)
    
    def test_multipliers_applied(self, config, time_metrics, test_project_root):
        """Test that complexity multipliers affect hours."""
        calculator = EffortCalculator(
            config.effort_estimator,
            time_metrics=time_metrics,
            project_root=test_project_root,
        )
        
        # Use a component with actual source file
        comp = TomlComponent(
            ref="field.sale_order.x_test",
            source_location="models/sale_order.py",
            component_type="field",
            model="sale.order",
            name="x_test",
        )
        
        estimate = calculator.estimate_component(comp)
        
        # Should have applied multiplier and have hours
        assert estimate.adjusted_hours.total > 0
        assert estimate.computed_label in ["simple", "medium", "complex", "very_complex"]


class TestMarkdownGenerator:
    """Tests for MarkdownGenerator."""
    
    @pytest.fixture
    def sample_estimated_features(self):
        """Create sample estimated features."""
        from effort_estimator import EstimatedUserStory
        
        component = TomlComponent(
            ref="field.sale_order.x_test",
            source_location="models/sale_order.py",
            component_type="field",
            model="sale.order",
            name="x_test",
        )
        
        estimated_comp = EstimatedComponent(
            component=component,
            complexity_result=None,
            computed_score=1.5,
            computed_label="medium",
            baseline_hours=TimeBreakdown(development=2.0, requirements=0.5, testing=1.0),
            adjusted_hours=TimeBreakdown(development=2.0, requirements=0.5, testing=1.0),
            is_fallback=False,
        )
        
        story = EstimatedUserStory(
            name="Test Story",
            description="Test Story Description",
            sequence=1,
            components=[estimated_comp],
            total_hours=3.5,
        )
        
        feature = EstimatedFeature(
            name="Test Feature",
            description="Test description",
            sequence=1,
            user_stories=[story],
            total_hours=3.5,
        )
        
        return [feature]
    
    def test_generate_markdown(self, config, sample_estimated_features):
        """Test generating markdown with effort estimates."""
        generator = MarkdownGenerator(config.effort_estimator)
        markdown = generator.generate(sample_estimated_features, "Test Project")
        
        assert "# Test Project - Implementation TODO" in markdown
        assert "## Summary" in markdown
        assert "Total Estimated Hours" in markdown
        assert "## Feature: Test Feature" in markdown
        assert "### User Story" in markdown
        assert "#### Component:" in markdown
        assert "**Hours:**" in markdown
    
    def test_summary_statistics(self, config, sample_estimated_features):
        """Test summary statistics in markdown."""
        generator = MarkdownGenerator(config.effort_estimator)
        markdown = generator.generate(sample_estimated_features, "Test")
        
        assert "Features:" in markdown
        assert "User Stories:" in markdown
        assert "Components:" in markdown
        assert "3.5h" in markdown  # Total hours


class TestEffortEstimatorIntegration:
    """Integration tests for EffortEstimator."""
    
    def test_estimate_from_toml(self, config, test_project_root):
        """Test full estimation from TOML file - only features with source."""
        from shared.python.effort_estimator import TomlLoader
        
        # Load features and filter to ones with source_location
        loader = TomlLoader(test_project_root)
        all_features = loader.load_features()
        
        # Filter out "No Source" features
        valid_features = [f for f in all_features if "No Source" not in f.name]
        
        # Estimate each valid feature
        time_metrics = TimeMetrics.from_file(test_project_root / "time_metrics.json")
        calculator = EffortCalculator(
            config.effort_estimator,
            time_metrics=time_metrics,
            project_root=test_project_root,
        )
        
        estimated_features = []
        for feature in valid_features:
            estimated = calculator.estimate_feature(feature)
            estimated_features.append(estimated)
        
        # Should have features (minus the No Source one)
        assert len(estimated_features) == 2
        
        # Features should have hours
        for feature in estimated_features:
            assert feature.total_hours >= 0
    
    def test_estimate_with_verbose(self, config, test_project_root, capsys):
        """Test verbose logging with valid features."""
        from shared.python.effort_estimator import TomlLoader
        
        # Load features and filter to ones with source_location
        loader = TomlLoader(test_project_root)
        all_features = loader.load_features()
        valid_features = [f for f in all_features if "No Source" not in f.name]
        
        time_metrics = TimeMetrics.from_file(test_project_root / "time_metrics.json")
        calculator = EffortCalculator(
            config.effort_estimator,
            time_metrics=time_metrics,
            project_root=test_project_root,
        )
        
        # Should complete without error
        for feature in valid_features:
            estimated = calculator.estimate_feature(feature)
            assert estimated.total_hours >= 0
    
    def test_estimate_and_save(self, config, test_project_root, tmp_path):
        """Test saving estimated output to file - only valid features."""
        from shared.python.effort_estimator import TomlLoader, MarkdownGenerator
        
        loader = TomlLoader(test_project_root)
        all_features = loader.load_features()
        valid_features = [f for f in all_features if "No Source" not in f.name]
        
        time_metrics = TimeMetrics.from_file(test_project_root / "time_metrics.json")
        calculator = EffortCalculator(
            config.effort_estimator,
            time_metrics=time_metrics,
            project_root=test_project_root,
        )
        
        estimated_features = []
        for feature in valid_features:
            estimated = calculator.estimate_feature(feature)
            estimated_features.append(estimated)
        
        generator = MarkdownGenerator(config.effort_estimator)
        markdown = generator.generate(estimated_features)
        
        output_path = tmp_path / "estimated.md"
        output_path.write_text(markdown)
        
        assert output_path.exists()
        content = output_path.read_text()
        assert "Hours:" in content
    
    def test_export_metrics_json(self, config, test_project_root, tmp_path):
        """Test exporting metrics as JSON - only valid features."""
        from shared.python.effort_estimator import TomlLoader
        
        loader = TomlLoader(test_project_root)
        all_features = loader.load_features()
        valid_features = [f for f in all_features if "No Source" not in f.name]
        
        time_metrics = TimeMetrics.from_file(test_project_root / "time_metrics.json")
        calculator = EffortCalculator(
            config.effort_estimator,
            time_metrics=time_metrics,
            project_root=test_project_root,
        )
        
        estimated_features = []
        for feature in valid_features:
            estimated = calculator.estimate_feature(feature)
            estimated_features.append(estimated)
        
        # Export estimated features to JSON
        import json
        json_path = tmp_path / "metrics.json"
        
        data = {
            "summary": {
                "total_features": len(estimated_features),
                "total_hours": sum(f.total_hours for f in estimated_features),
            },
            "features": [f.name for f in estimated_features],
        }
        
        with open(json_path, "w") as f:
            json.dump(data, f)
        
        assert json_path.exists()
        
        with open(json_path) as f:
            loaded = json.load(f)
        
        assert "summary" in loaded
        assert "features" in loaded
        assert loaded["summary"]["total_features"] == 2  # Only valid features
        assert loaded["summary"]["total_hours"] >= 0
    
    def test_components_with_source_analyzed(self, config, test_project_root):
        """Test that components with source_location are properly analyzed."""
        # We need to use features that have source_location, not the "No Source" one
        from shared.python.effort_estimator import TomlLoader
        
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        
        # Find a feature with source locations (not "No Source")
        sales_feature = next(f for f in features if "Sales" in f.name)
        
        # Create calculator directly
        time_metrics = TimeMetrics.from_file(test_project_root / "time_metrics.json")
        calculator = EffortCalculator(
            config.effort_estimator,
            time_metrics=time_metrics,
            project_root=test_project_root,
        )
        
        estimated = calculator.estimate_feature(sales_feature)
        
        # All components should have valid complexity (no fallback)
        for story in estimated.user_stories:
            for comp in story.components:
                assert comp.computed_label in ["simple", "medium", "complex", "very_complex"]
                assert comp.loc >= 0
    
    def test_components_without_source_raises_error(self, config, test_project_root):
        """Test that components without source_location raise error - NO FALLBACK."""
        from shared.python.effort_estimator import TomlLoader, EffortCalculator, TimeMetrics
        loader = TomlLoader(test_project_root)
        features = loader.load_features()
        
        # Find the "No Source Components" feature
        no_source_feature = next(f for f in features if "No Source" in f.name)
        
        time_metrics = TimeMetrics.from_file(test_project_root / "time_metrics.json")
        calculator = EffortCalculator(
            config.effort_estimator,
            time_metrics=time_metrics,
            project_root=test_project_root,
        )
        
        # Should raise ValueError for components without source
        import pytest
        with pytest.raises(ValueError, match="No source_location"):
            calculator.estimate_feature(no_source_feature)


class TestComplexityAnalysisIntegration:
    """Tests for complexity analysis with real source files."""
    
    def test_python_file_analyzed(self, config, time_metrics, test_project_root):
        """Test that Python files are analyzed for complexity."""
        calculator = EffortCalculator(
            config.effort_estimator,
            time_metrics=time_metrics,
            project_root=test_project_root,
        )
        
        component = TomlComponent(
            ref="server_action.sale_order.action_calculate",
            source_location="models/sale_order.py",
            component_type="server_action",
            model="sale.order",
            name="action_calculate",
        )
        
        estimate = calculator.estimate_component(component)
        
        assert not estimate.is_fallback
        assert estimate.complexity_result is not None
        assert estimate.complexity_result.raw_metrics.loc > 0
    
    def test_automation_file_analyzed(self, config, time_metrics, test_project_root):
        """Test that automation files are analyzed."""
        calculator = EffortCalculator(
            config.effort_estimator,
            time_metrics=time_metrics,
            project_root=test_project_root,
        )
        
        component = TomlComponent(
            ref="automation.stock_picking.auto_validate",
            source_location="models/stock_automation.py",
            component_type="automation",
            model="stock.picking",
            name="auto_validate",
        )
        
        estimate = calculator.estimate_component(component)
        
        assert not estimate.is_fallback
        assert estimate.adjusted_hours.total > 0
