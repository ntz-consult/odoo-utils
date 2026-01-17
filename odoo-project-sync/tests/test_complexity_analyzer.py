"""Tests for the Complexity Analyzer module."""

import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "shared" / "python"))

from complexity_analyzer import (
    ComplexityAnalyzer,
    PythonAnalyzer,
    XMLAnalyzer,
    JavaScriptAnalyzer,
    ComplexityMetrics,
    NormalizedMetrics,
    ComplexityResult,
    resolve_source_location,
)
from enricher_config import EffortEstimatorConfig


@pytest.fixture
def sample_source_dir():
    """Get path to sample source files."""
    return Path(__file__).parent / "fixtures" / "sample_source_files"


@pytest.fixture
def time_metrics_path():
    """Get path to time_metrics.json."""
    return Path(__file__).parent.parent / "templates" / "time_metrics.json"


@pytest.fixture
def config():
    """Create test configuration."""
    return EffortEstimatorConfig()


class TestPythonAnalyzer:
    """Tests for Python source code analysis."""
    
    def test_analyze_simple_file(self, sample_source_dir):
        """Test analyzing a simple Python file."""
        analyzer = PythonAnalyzer()
        file_path = sample_source_dir / "models" / "stock_picking.py"
        content = file_path.read_text()
        
        metrics = analyzer.analyze(content, file_path)
        
        assert metrics.files_analyzed == 1
        assert metrics.loc > 0
        assert metrics.functions_count >= 2  # At least compute and toggle methods
        assert "py" in metrics.file_types
    
    def test_count_functions(self, sample_source_dir):
        """Test function counting."""
        analyzer = PythonAnalyzer()
        file_path = sample_source_dir / "models" / "sale_order.py"
        content = file_path.read_text()
        
        metrics = analyzer.analyze(content, file_path)
        
        # sale_order.py has multiple methods
        assert metrics.functions_count >= 5
    
    def test_detect_sql_queries(self, sample_source_dir):
        """Test SQL/ORM query detection."""
        analyzer = PythonAnalyzer()
        file_path = sample_source_dir / "models" / "stock_automation.py"
        content = file_path.read_text()
        
        metrics = analyzer.analyze(content, file_path)
        
        # stock_automation.py has search() calls
        assert metrics.sql_queries_count > 0
    
    def test_detect_external_calls(self, sample_source_dir):
        """Test external HTTP call detection."""
        analyzer = PythonAnalyzer()
        file_path = sample_source_dir / "models" / "stock_automation.py"
        content = file_path.read_text()
        
        metrics = analyzer.analyze(content, file_path)
        
        # stock_automation.py has requests.post
        assert metrics.external_calls_count > 0
    
    def test_detect_dynamic_code(self, sample_source_dir):
        """Test dynamic code detection (eval/exec)."""
        analyzer = PythonAnalyzer()
        file_path = sample_source_dir / "models" / "stock_automation.py"
        content = file_path.read_text()
        
        metrics = analyzer.analyze(content, file_path)
        
        # stock_automation.py has eval()
        assert metrics.dynamic_code_flags == 1
    
    def test_cyclomatic_complexity(self):
        """Test cyclomatic complexity calculation."""
        analyzer = PythonAnalyzer()
        
        complex_code = """
def complex_function(x, y):
    if x > 0:
        if y > 0:
            return x + y
        elif y < 0:
            return x - y
        else:
            return x
    else:
        for i in range(10):
            if i % 2 == 0:
                x += i
        return x
"""
        metrics = analyzer.analyze(complex_code)
        
        # Should have higher complexity due to nested conditions
        assert metrics.avg_cyclomatic_complexity > 1
        assert metrics.branches_count >= 4  # if, if, elif, else, for, if


class TestXMLAnalyzer:
    """Tests for XML source code analysis."""
    
    def test_analyze_view_file(self, sample_source_dir):
        """Test analyzing an XML view file."""
        analyzer = XMLAnalyzer()
        file_path = sample_source_dir / "views" / "sale_order_views.xml"
        content = file_path.read_text()
        
        metrics = analyzer.analyze(content, file_path)
        
        assert metrics.files_analyzed == 1
        assert metrics.ui_elements_count > 0
        assert "xml" in metrics.file_types
    
    def test_count_ui_elements(self, sample_source_dir):
        """Test UI element counting."""
        analyzer = XMLAnalyzer()
        file_path = sample_source_dir / "views" / "sale_order_views.xml"
        content = file_path.read_text()
        
        metrics = analyzer.analyze(content, file_path)
        
        # View file has multiple fields, buttons, xpaths
        assert metrics.ui_elements_count >= 5


class TestJavaScriptAnalyzer:
    """Tests for JavaScript source code analysis."""
    
    def test_analyze_js_code(self):
        """Test analyzing JavaScript code."""
        analyzer = JavaScriptAnalyzer()
        
        js_code = """
odoo.define('my_module.widget', function (require) {
    var Widget = require('web.Widget');
    
    var MyWidget = Widget.extend({
        template: 'MyTemplate',
        
        init: function (parent, options) {
            this._super(parent);
            this.options = options;
        },
        
        start: function () {
            var self = this;
            return this._super().then(function () {
                self._renderElement();
            });
        },
        
        _onClick: function (ev) {
            if (this.options.enabled) {
                this.do_action('my_action');
            }
        },
    });
    
    return MyWidget;
});
"""
        metrics = analyzer.analyze(js_code)
        
        assert metrics.files_analyzed == 1
        assert metrics.functions_count > 0
        assert metrics.branches_count > 0  # if statement
        assert "js" in metrics.file_types


class TestComplexityAnalyzer:
    """Tests for the main ComplexityAnalyzer class."""
    
    def test_analyze_multiple_files(self, sample_source_dir, config, time_metrics_path):
        """Test analyzing multiple files."""
        analyzer = ComplexityAnalyzer.from_config_file(time_metrics_path, config)
        
        files = [
            sample_source_dir / "models" / "sale_order.py",
            sample_source_dir / "models" / "stock_picking.py",
        ]
        
        # component_type is REQUIRED - no fallback
        result = analyzer.analyze_files(files, component_type="field")
        
        assert result.raw_metrics.files_analyzed == 2
        assert result.raw_metrics.loc > 0
        assert result.complexity_label in ["simple", "medium", "complex", "very_complex"]
    
    def test_analyze_directory(self, sample_source_dir, config, time_metrics_path):
        """Test analyzing a directory."""
        analyzer = ComplexityAnalyzer.from_config_file(time_metrics_path, config)
        
        # component_type is REQUIRED - no fallback
        result = analyzer.analyze_directory(sample_source_dir, component_type="view")
        
        # Should have analyzed Python and XML files
        assert result.raw_metrics.files_analyzed >= 4
        assert "py" in result.raw_metrics.file_types
        assert "xml" in result.raw_metrics.file_types
    
    def test_normalization(self, config):
        """Test metric normalization."""
        analyzer = ComplexityAnalyzer(config)
        
        # Create metrics at the limit
        metrics = ComplexityMetrics(
            loc=config.limits.loc_max,
            functions_count=config.limits.functions_max,
            avg_cyclomatic_complexity=config.limits.cyclomatic_complexity_max,
        )
        
        normalized = analyzer._normalize_metrics(metrics)
        
        # Should be close to 1.0 for values at the limit
        assert normalized.functions_count == 1.0
        assert normalized.avg_cyclomatic_complexity == 1.0
    
    def test_weighted_score(self, config):
        """Test weighted score calculation."""
        analyzer = ComplexityAnalyzer(config)
        
        # Simple metrics
        normalized = NormalizedMetrics(
            loc=0.1,
            functions_count=0.1,
            avg_cyclomatic_complexity=0.1,
        )
        
        simple_score = analyzer._calculate_weighted_score(normalized)
        
        # Complex metrics
        complex_normalized = NormalizedMetrics(
            loc=0.9,
            functions_count=0.9,
            avg_cyclomatic_complexity=0.9,
            dynamic_code_flags=1.0,
        )
        
        complex_score = analyzer._calculate_weighted_score(complex_normalized)
        
        assert complex_score > simple_score
    
    def test_score_to_label(self, config):
        """Test score to label mapping."""
        analyzer = ComplexityAnalyzer(config)
        
        assert analyzer._score_to_label(0.5) == "simple"
        assert analyzer._score_to_label(1.5) == "medium"
        assert analyzer._score_to_label(3.0) == "complex"
        assert analyzer._score_to_label(5.0) == "very_complex"
    
    def test_top_contributors(self, config):
        """Test finding top contributors."""
        analyzer = ComplexityAnalyzer(config)
        
        normalized = NormalizedMetrics(
            loc=0.8,
            functions_count=0.2,
            avg_cyclomatic_complexity=0.9,
            dynamic_code_flags=1.0,
        )
        
        contributors = analyzer._find_top_contributors(normalized)
        
        assert len(contributors) <= 3
        # Dynamic code has highest weight (2.5) and value (1.0)
        assert contributors[0][0] == "dynamic_code_flags"
    
    def test_missing_file_handling(self, config, time_metrics_path):
        """Test handling of missing files raises error - NO FALLBACK."""
        analyzer = ComplexityAnalyzer.from_config_file(time_metrics_path, config)
        
        # Missing files should raise ValueError, not silently fallback
        import pytest
        with pytest.raises(ValueError, match="No files were successfully analyzed"):
            analyzer.analyze_files([Path("/nonexistent/file.py")], component_type="field")


class TestResolveSourceLocation:
    """Tests for source location resolution."""
    
    def test_resolve_relative_path(self, sample_source_dir):
        """Test resolving relative paths."""
        base = sample_source_dir.parent
        
        files = resolve_source_location(
            "sample_source_files/models/sale_order.py", 
            base
        )
        
        assert len(files) == 1
        assert files[0].name == "sale_order.py"
    
    def test_resolve_directory(self, sample_source_dir):
        """Test resolving a directory path."""
        base = sample_source_dir.parent
        
        files = resolve_source_location(
            "sample_source_files/models",
            base
        )
        
        # Should return Python files from the directory
        assert len(files) >= 3
    
    def test_resolve_missing_path(self, sample_source_dir):
        """Test handling missing paths."""
        files = resolve_source_location(
            "nonexistent/path.py",
            sample_source_dir
        )
        
        assert files == []
    
    def test_resolve_glob_pattern(self, sample_source_dir):
        """Test resolving glob patterns."""
        base = sample_source_dir.parent
        
        files = resolve_source_location(
            "sample_source_files/**/*.py",
            base
        )
        
        assert len(files) >= 3
