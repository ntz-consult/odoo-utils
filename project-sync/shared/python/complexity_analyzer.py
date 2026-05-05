"""Complexity Analyzer for source code metrics.

Analyzes source files to compute complexity metrics for effort estimation.
This is the metrics engine for Phase 2 (Effort Estimator).
"""

import ast
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from .enricher_config import EffortEstimatorConfig, MetricLimits, MetricWeights
except ImportError:
    from enricher_config import EffortEstimatorConfig, MetricLimits, MetricWeights


@dataclass
class OdooIndicators:
    """Detected Odoo-specific indicators from source code."""
    
    # Field indicators
    has_compute: bool = False
    has_related: bool = False
    has_currency_compute: bool = False
    
    # ORM indicators
    orm_calls_count: int = 0
    has_search_browse: bool = False
    has_sql_query: bool = False
    cross_model_calls: bool = False
    
    # View indicators
    xpath_count: int = 0
    has_attrs_domain: bool = False
    has_widget_override: bool = False
    has_js_class: bool = False
    is_form_tree_kanban: bool = False
    
    # QWeb indicators
    has_qweb_directives: bool = False
    has_t_if: bool = False
    has_t_foreach: bool = False
    t_foreach_count: int = 0
    has_t_call: bool = False
    has_t_raw: bool = False
    has_nested_loops: bool = False
    is_pdf_output: bool = False
    is_label_output: bool = False
    
    # Action indicators
    has_python_code: bool = False
    has_external_api: bool = False
    has_transaction: bool = False
    has_multi_company: bool = False
    has_env_context: bool = False
    
    # Control flow indicators
    has_loop: bool = False
    has_conditional: bool = False
    method_count: int = 0
    
    # Report indicators
    has_custom_paperformat: bool = False
    has_custom_model: bool = False
    has_barcode_qr: bool = False
    
    # Automation indicators
    has_domain_filter: bool = False
    trigger_fields_count: int = 0


@dataclass
class ComplexityMetrics:
    """Raw complexity metrics extracted from source files."""
    
    # Lines of code (non-blank, non-comment)
    loc: int = 0
    
    # Function/method count
    functions_count: int = 0
    
    # Cyclomatic complexity metrics
    total_cyclomatic_complexity: int = 0
    avg_cyclomatic_complexity: float = 0.0
    max_cyclomatic_complexity: int = 0
    
    # Branch/conditional count
    branches_count: int = 0
    
    # SQL/ORM query count
    sql_queries_count: int = 0
    
    # External HTTP/API calls
    external_calls_count: int = 0
    
    # UI elements (fields, widgets, templates in XML/JS)
    ui_elements_count: int = 0
    
    # Dynamic code flags (eval, exec, __import__)
    dynamic_code_flags: int = 0
    
    # File types in component (py, xml, js, etc.)
    file_types: set[str] = field(default_factory=set)
    
    # Test coverage flag
    has_tests: bool = False
    
    # Metadata
    files_analyzed: int = 0
    errors: list[str] = field(default_factory=list)
    
    # Odoo-specific indicators
    odoo_indicators: OdooIndicators = field(default_factory=OdooIndicators)
    
    @property
    def file_types_count(self) -> int:
        """Number of distinct file types."""
        return len(self.file_types)


@dataclass
class NormalizedMetrics:
    """Normalized metrics (0.0 to 1.0 scale)."""
    
    loc: float = 0.0
    functions_count: float = 0.0
    avg_cyclomatic_complexity: float = 0.0
    branches_count: float = 0.0
    sql_queries_count: float = 0.0
    external_calls_count: float = 0.0
    ui_elements_count: float = 0.0
    dynamic_code_flags: float = 0.0
    file_types_mix: float = 0.0
    test_coverage_flag: float = 0.0
    
    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary for iteration."""
        return {
            "loc": self.loc,
            "functions_count": self.functions_count,
            "avg_cyclomatic_complexity": self.avg_cyclomatic_complexity,
            "branches_count": self.branches_count,
            "sql_queries_count": self.sql_queries_count,
            "external_calls_count": self.external_calls_count,
            "ui_elements_count": self.ui_elements_count,
            "dynamic_code_flags": self.dynamic_code_flags,
            "file_types_mix": self.file_types_mix,
            "test_coverage_flag": self.test_coverage_flag,
        }


@dataclass
class ComplexityResult:
    """Full complexity analysis result."""
    
    raw_metrics: ComplexityMetrics
    normalized_metrics: NormalizedMetrics
    weighted_score: float
    complexity_label: str  # simple, medium, complex, very_complex
    top_contributors: list[tuple[str, float]]  # [(metric_name, contribution), ...]
    source_files: list[Path]
    
    @property
    def is_fallback(self) -> bool:
        """Check if this result used fallback (no files analyzed)."""
        return self.raw_metrics.files_analyzed == 0


class PythonAnalyzer:
    """Analyze Python source files for complexity metrics."""
    
    # Patterns for SQL/ORM queries
    SQL_PATTERNS = [
        re.compile(r'\.(search|browse|create|write|unlink)\s*\('),
        re.compile(r'\.(read|read_group|search_read|search_count)\s*\('),
        re.compile(r'self\.env\['),
        re.compile(r'execute\s*\(\s*["\'](?:SELECT|INSERT|UPDATE|DELETE)', re.IGNORECASE),
        re.compile(r'_sql_constraints'),
        re.compile(r'cr\.execute'),
    ]
    
    # Patterns for external calls
    EXTERNAL_CALL_PATTERNS = [
        re.compile(r'requests\.(get|post|put|delete|patch)\s*\('),
        re.compile(r'urllib'),
        re.compile(r'http\.client'),
        re.compile(r'aiohttp'),
        re.compile(r'httpx'),
    ]
    
    # Patterns for dynamic code
    DYNAMIC_CODE_PATTERNS = [
        re.compile(r'\beval\s*\('),
        re.compile(r'\bexec\s*\('),
        re.compile(r'__import__\s*\('),
        re.compile(r'importlib\.import_module'),
        re.compile(r'getattr\s*\([^,]+,\s*[^)]+\)\s*\('),  # getattr with call
    ]
    
    def analyze(self, content: str, file_path: Path | None = None) -> ComplexityMetrics:
        """Analyze Python source code.
        
        Args:
            content: Python source code
            file_path: Optional file path for error context
            
        Returns:
            ComplexityMetrics for the file
        """
        metrics = ComplexityMetrics()
        metrics.file_types.add("py")
        
        # Count lines of code
        metrics.loc = self._count_loc(content)
        
        # Parse AST for structural analysis
        try:
            tree = ast.parse(content)
            metrics.functions_count = self._count_functions(tree)
            cc_metrics = self._calculate_cyclomatic_complexity(tree)
            metrics.total_cyclomatic_complexity = cc_metrics["total"]
            metrics.avg_cyclomatic_complexity = cc_metrics["avg"]
            metrics.max_cyclomatic_complexity = cc_metrics["max"]
            metrics.branches_count = self._count_branches(tree)
        except SyntaxError as e:
            error_msg = f"Syntax error in {file_path or 'source'}: {e}"
            metrics.errors.append(error_msg)
        
        # Pattern-based analysis
        metrics.sql_queries_count = self._count_patterns(content, self.SQL_PATTERNS)
        metrics.external_calls_count = self._count_patterns(content, self.EXTERNAL_CALL_PATTERNS)
        metrics.dynamic_code_flags = min(1, self._count_patterns(content, self.DYNAMIC_CODE_PATTERNS))
        
        metrics.files_analyzed = 1
        
        return metrics
    
    def _count_loc(self, content: str) -> int:
        """Count non-blank, non-comment lines."""
        count = 0
        in_multiline_string = False
        
        for line in content.split('\n'):
            stripped = line.strip()
            
            # Skip empty lines
            if not stripped:
                continue
            
            # Handle multiline strings (docstrings)
            # Count triple quotes to handle both opening and closing on same line
            triple_double = stripped.count('"""')
            triple_single = stripped.count("'''")
            total_triples = triple_double + triple_single
            
            if total_triples > 0:
                if total_triples == 2:
                    # Opening and closing on same line (e.g., """docstring""")
                    # This is a docstring line, skip it
                    continue
                elif total_triples == 1:
                    # Toggle multiline string state
                    in_multiline_string = not in_multiline_string
                    continue
            
            if in_multiline_string:
                continue
            
            # Skip single-line comments
            if stripped.startswith('#'):
                continue
            
            count += 1
        
        return count
    
    def _count_functions(self, tree: ast.AST) -> int:
        """Count function and method definitions."""
        count = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                count += 1
        return count
    
    def _calculate_cyclomatic_complexity(self, tree: ast.AST) -> dict[str, Any]:
        """Calculate cyclomatic complexity metrics.
        
        Cyclomatic complexity = E - N + 2P
        Simplified: 1 + number of decision points
        """
        # Decision point node types
        decision_nodes = (
            ast.If, ast.While, ast.For, ast.AsyncFor,
            ast.ExceptHandler, ast.With, ast.AsyncWith,
            ast.Assert, ast.comprehension,
        )
        
        # Boolean operators add complexity
        bool_ops = (ast.And, ast.Or)
        
        function_complexities = []
        
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                complexity = 1  # Base complexity
                
                for child in ast.walk(node):
                    if isinstance(child, decision_nodes):
                        complexity += 1
                    elif isinstance(child, ast.BoolOp):
                        # Each boolean operator adds paths
                        complexity += len(child.values) - 1
                    elif isinstance(child, ast.IfExp):
                        complexity += 1  # Ternary operator
                
                function_complexities.append(complexity)
        
        if not function_complexities:
            return {"total": 0, "avg": 0.0, "max": 0}
        
        return {
            "total": sum(function_complexities),
            "avg": sum(function_complexities) / len(function_complexities),
            "max": max(function_complexities),
        }
    
    def _count_branches(self, tree: ast.AST) -> int:
        """Count branching/conditional constructs."""
        branch_types = (
            ast.If, ast.While, ast.For, ast.AsyncFor,
            ast.Try, ast.ExceptHandler, ast.Match,
        )
        
        count = 0
        for node in ast.walk(tree):
            if isinstance(node, branch_types):
                count += 1
            # Count elif as additional branches
            if isinstance(node, ast.If):
                # Each elif adds a branch
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, ast.If):
                        count += 1
        
        return count
    
    def _count_patterns(self, content: str, patterns: list[re.Pattern]) -> int:
        """Count occurrences of regex patterns."""
        count = 0
        for pattern in patterns:
            count += len(pattern.findall(content))
        return count

    def extract_field_content(self, content: str, field_name: str) -> str | None:
        """Extract only the field definition and its compute method from Python source.
        
        For a field like 'x_alt_product_uom_id', extracts:
        1. The field definition line(s)
        2. The compute method (if referenced by compute='_compute_x_alt_product_uom_id')
        
        Args:
            content: Full Python file content
            field_name: Name of the field to extract (e.g., 'x_alt_product_uom_id')
            
        Returns:
            Extracted content for just this field, or None if not found
        """
        lines = content.split('\n')
        extracted_lines = []
        
        # Find the field definition line(s)
        field_pattern = re.compile(rf'^\s*{re.escape(field_name)}\s*=\s*fields\.')
        compute_method_name = None
        field_found = False
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            if field_pattern.match(line):
                field_found = True
                # Capture the field definition (may span multiple lines)
                field_lines = [line]
                # Check if line continues (ends with comma, open paren without close)
                open_parens = line.count('(') - line.count(')')
                while open_parens > 0 and i + 1 < len(lines):
                    i += 1
                    field_lines.append(lines[i])
                    open_parens += lines[i].count('(') - lines[i].count(')')
                
                extracted_lines.extend(field_lines)
                
                # Look for compute= in the field definition
                field_text = '\n'.join(field_lines)
                compute_match = re.search(r"compute\s*=\s*['\"]([^'\"]+)['\"]", field_text)
                if compute_match:
                    compute_method_name = compute_match.group(1)
                break
            i += 1
        
        # If we found a compute method, extract it too
        if compute_method_name:
            method_pattern = re.compile(rf'^\s*def\s+{re.escape(compute_method_name)}\s*\(')
            i = 0
            while i < len(lines):
                line = lines[i]
                if method_pattern.match(line):
                    # Capture the method definition
                    method_lines = [line]
                    # Get the indentation level
                    base_indent = len(line) - len(line.lstrip())
                    i += 1
                    while i < len(lines):
                        next_line = lines[i]
                        # Empty lines are part of the method
                        if not next_line.strip():
                            method_lines.append(next_line)
                            i += 1
                            continue
                        # Check indentation
                        next_indent = len(next_line) - len(next_line.lstrip())
                        if next_indent > base_indent:
                            method_lines.append(next_line)
                            i += 1
                        else:
                            break
                    extracted_lines.extend(method_lines)
                    break
                i += 1
        
        if not field_found:
            return None
        
        return '\n'.join(extracted_lines)


class XMLAnalyzer:
    """Analyze XML source files (Odoo views, templates, data files)."""
    
    # UI element patterns
    UI_ELEMENT_PATTERNS = [
        re.compile(r'<field\s'),
        re.compile(r'<button\s'),
        re.compile(r'<widget\s'),
        re.compile(r'<group\s'),
        re.compile(r'<notebook\s'),
        re.compile(r'<page\s'),
        re.compile(r'<tree\s'),
        re.compile(r'<form\s'),
        re.compile(r'<kanban\s'),
        re.compile(r'<search\s'),
        re.compile(r'<xpath\s'),
        re.compile(r'<t\s+t-'),  # QWeb templates
    ]
    
    # Pattern to extract arch content from view XML files
    ARCH_PATTERN = re.compile(
        r'<field\s+name=["\']arch["\'][^>]*type=["\']xml["\'][^>]*>\s*(.*?)\s*</field>',
        re.DOTALL | re.IGNORECASE
    )
    # Alternative pattern for arch without type attribute
    ARCH_PATTERN_ALT = re.compile(
        r'<field\s+name=["\']arch["\'][^>]*>\s*(.*?)\s*</field>',
        re.DOTALL | re.IGNORECASE
    )
    
    # Pattern to detect automation files
    AUTOMATION_PATTERN = re.compile(
        r'model=["\']base\.automation["\']',
        re.IGNORECASE
    )
    
    # Pattern to extract domain from automation
    AUTOMATION_DOMAIN_PATTERN = re.compile(
        r'<field\s+name=["\']filter_domain["\'][^>]*>(.*?)</field>',
        re.DOTALL | re.IGNORECASE
    )
    
    def analyze(self, content: str, file_path: Path | None = None) -> ComplexityMetrics:
        """Analyze XML source code.
        
        For Odoo view files, extracts and analyzes only the <arch> content,
        not the boilerplate wrapper (odoo, data, record tags).
        
        For automation files, returns LOC=1 (they're just config) unless
        there's a complex domain filter.
        
        Args:
            content: XML source code
            file_path: Optional file path for error context
            
        Returns:
            ComplexityMetrics for the file
        """
        metrics = ComplexityMetrics()
        metrics.file_types.add("xml")
        
        # Check if this is an automation file (base.automation record)
        if self.AUTOMATION_PATTERN.search(content):
            # Automations are config - LOC=1 by default
            # Only increase if there's a complex domain filter
            metrics.loc = 1
            
            # Check for domain filter
            domain_match = self.AUTOMATION_DOMAIN_PATTERN.search(content)
            if domain_match:
                domain_content = domain_match.group(1).strip()
                # Count domain complexity by number of conditions
                # Each tuple in domain adds complexity
                condition_count = domain_content.count("(") 
                if condition_count > 3:
                    # Complex domain - bump LOC to reflect complexity
                    metrics.loc = condition_count
            
            metrics.files_analyzed = 1
            return metrics
        
        # Check if this is an Odoo view file with <arch> content
        arch_content = self._extract_arch_content(content)
        
        if arch_content:
            # This is a view file - count only meaningful LOC from arch content
            metrics.loc = self._count_meaningful_xml_lines(arch_content)
            analysis_content = arch_content
        else:
            # Not a view file (data file, manifest, etc.) - count all lines
            metrics.loc = sum(1 for line in content.split('\n') if line.strip())
            analysis_content = content
        
        # Count UI elements from the relevant content
        for pattern in self.UI_ELEMENT_PATTERNS:
            metrics.ui_elements_count += len(pattern.findall(analysis_content))
        
        metrics.files_analyzed = 1
        
        return metrics
    
    def _count_meaningful_xml_lines(self, content: str) -> int:
        """Count meaningful lines in XML view content.
        
        Ignores:
        - Closing tags (</...>)
        - Wrapper tags like <data>, </data>, <template>, </template>
        - Empty/whitespace-only lines
        
        Args:
            content: XML content (typically from arch field)
            
        Returns:
            Count of meaningful lines
        """
        count = 0
        # Patterns for lines to ignore
        ignore_patterns = [
            re.compile(r'^\s*</'),           # Closing tags
            re.compile(r'^\s*<data\s*>?\s*$', re.IGNORECASE),      # <data> wrapper
            re.compile(r'^\s*<template\s*[^>]*>\s*$', re.IGNORECASE),  # <template> wrapper
        ]
        
        for line in content.split('\n'):
            stripped = line.strip()
            if not stripped:
                continue
            
            # Check if line should be ignored
            should_ignore = False
            for pattern in ignore_patterns:
                if pattern.match(stripped):
                    should_ignore = True
                    break
            
            if not should_ignore:
                count += 1
        
        return count
    
    def _extract_arch_content(self, content: str) -> str | None:
        """Extract the content within <field name="arch">...</field> tags.
        
        For Odoo view files, the actual view logic is inside the arch field.
        The outer XML (odoo, data, record) is just boilerplate.
        
        Args:
            content: Full XML file content
            
        Returns:
            Arch content if found, None otherwise
        """
        # Try the pattern with type="xml" first
        matches = self.ARCH_PATTERN.findall(content)
        
        if not matches:
            # Try alternative pattern without type attribute
            matches = self.ARCH_PATTERN_ALT.findall(content)
        
        if matches:
            # Combine all arch contents (there might be multiple views in one file)
            return '\n'.join(matches)
        
        return None


class JavaScriptAnalyzer:
    """Analyze JavaScript source files."""
    
    # Function patterns
    FUNCTION_PATTERNS = [
        re.compile(r'function\s+\w+\s*\('),
        re.compile(r'\w+\s*:\s*function\s*\('),
        re.compile(r'=>'),  # Arrow functions
        re.compile(r'async\s+\w+\s*\('),
    ]
    
    # UI element patterns (Odoo OWL/legacy)
    UI_PATTERNS = [
        re.compile(r'\.template\s*='),
        re.compile(r'_renderElement'),
        re.compile(r'\.widget\s*='),
        re.compile(r'Component\.extend'),
        re.compile(r'<t\s+t-'),
    ]
    
    # External call patterns
    EXTERNAL_PATTERNS = [
        re.compile(r'fetch\s*\('),
        re.compile(r'XMLHttpRequest'),
        re.compile(r'\$\.ajax'),
        re.compile(r'axios'),
    ]
    
    def analyze(self, content: str, file_path: Path | None = None) -> ComplexityMetrics:
        """Analyze JavaScript source code.
        
        Args:
            content: JavaScript source code
            file_path: Optional file path for error context
            
        Returns:
            ComplexityMetrics for the file
        """
        metrics = ComplexityMetrics()
        metrics.file_types.add("js")
        
        # Count lines of code (rough - doesn't handle multiline comments well)
        lines = content.split('\n')
        metrics.loc = sum(
            1 for line in lines 
            if line.strip() and not line.strip().startswith('//')
        )
        
        # Count functions
        for pattern in self.FUNCTION_PATTERNS:
            metrics.functions_count += len(pattern.findall(content))
        
        # Count UI elements
        for pattern in self.UI_PATTERNS:
            metrics.ui_elements_count += len(pattern.findall(content))
        
        # Count external calls
        for pattern in self.EXTERNAL_PATTERNS:
            metrics.external_calls_count += len(pattern.findall(content))
        
        # Count branches
        metrics.branches_count = (
            len(re.findall(r'\bif\s*\(', content)) +
            len(re.findall(r'\belse\s', content)) +
            len(re.findall(r'\bswitch\s*\(', content)) +
            len(re.findall(r'\bcase\s', content)) +
            len(re.findall(r'\bfor\s*\(', content)) +
            len(re.findall(r'\bwhile\s*\(', content))
        )
        
        metrics.files_analyzed = 1
        
        return metrics


class OdooIndicatorDetector:
    """Detects Odoo-specific indicators from source code using regex patterns."""
    
    def __init__(self, patterns: dict[str, dict[str, list[str]]] | None = None):
        """Initialize with indicator patterns.
        
        Args:
            patterns: Indicator patterns from time_metrics.json
        """
        self.patterns = patterns or self._default_patterns()
        self._compiled_patterns: dict[str, list[re.Pattern]] = {}
        self._compile_patterns()
    
    def _default_patterns(self) -> dict[str, dict[str, list[str]]]:
        """Return default indicator patterns."""
        return {
            "orm_patterns": {
                "orm_calls": [r"self\.env\[", r"\.search\(", r"\.browse\(", r"\.create\(", r"\.write\(", r"\.unlink\(", r"\.filtered\(", r"\.mapped\(", r"\.sorted\("],
                "search_browse": [r"\.search\(", r"\.browse\(", r"\.search_read\("],
                "sql_query": [r"cr\.execute", r"self\._cr\.execute", r"self\.env\.cr\.execute"]
            },
            "field_patterns": {
                "has_compute": [r"compute\s*=", r"@api\.depends"],
                "has_related": [r"related\s*="],
                "currency_compute": [r"currency_id", r"company_currency", r"amount_.*currency"]
            },
            "view_patterns": {
                "xpath": [r"<xpath"],
                "attrs_domain": [r"attrs\s*=\s*[\"']\{"],
                "widget_override": [r"widget\s*="],
                "js_class": [r"js_class\s*="],
                "form_tree_kanban": [r"<(form|tree|kanban)\s"]
            },
            "qweb_patterns": {
                "t_foreach": [r"t-foreach\s*="],
                "t_call": [r"t-call\s*="],
                "t_raw": [r"t-raw\s*=", r"t-out\s*="],
                "t_if": [r"t-if\s*="],
                "qweb_directives": [r"t-(if|foreach|call|set|esc|raw|out)\s*="]
            },
            "action_patterns": {
                "python_code": [r"code\s*="],
                "external_api": [r"requests\.", r"urllib", r"http\.client"],
                "transaction": [r"with_context", r"env\.cr\.savepoint", r"\.sudo\("],
                "multi_company": [r"company_id", r"allowed_company_ids"],
                "env_context": [r"\.with_context\(", r"\.env\.context"]
            },
            "control_flow_patterns": {
                "loop": [r"for\s+\w+\s+in\s+", r"while\s+"],
                "conditional": [r"\bif\s+", r"\belif\s+"],
                "method_def": [r"def\s+\w+\s*\("]
            },
            "report_patterns": {
                "paperformat": [r"paperformat", r"paper_format"],
                "barcode_qr": [r"barcode", r"qrcode", r"QR"],
                "report_model": [r"AbstractModel", r"report\."]
            }
        }
    
    def _compile_patterns(self) -> None:
        """Pre-compile all regex patterns."""
        for category, patterns in self.patterns.items():
            # Skip non-dict entries like _description
            if not isinstance(patterns, dict):
                continue
            for pattern_name, pattern_list in patterns.items():
                # Skip non-list entries
                if not isinstance(pattern_list, list):
                    continue
                key = f"{category}.{pattern_name}"
                self._compiled_patterns[key] = [
                    re.compile(p, re.IGNORECASE) for p in pattern_list
                ]
    
    def _count_matches(self, content: str, pattern_key: str) -> int:
        """Count total matches for a pattern group."""
        patterns = self._compiled_patterns.get(pattern_key, [])
        return sum(len(p.findall(content)) for p in patterns)
    
    def _has_match(self, content: str, pattern_key: str) -> bool:
        """Check if any pattern in group matches."""
        return self._count_matches(content, pattern_key) > 0
    
    def detect(self, content: str, file_type: str = "py") -> OdooIndicators:
        """Detect Odoo indicators in source code.
        
        Args:
            content: Source code content
            file_type: File type (py, xml, js)
            
        Returns:
            OdooIndicators with detected values
        """
        indicators = OdooIndicators()
        
        # Field indicators (Python)
        if file_type == "py":
            indicators.has_compute = self._has_match(content, "field_patterns.has_compute")
            indicators.has_related = self._has_match(content, "field_patterns.has_related")
            indicators.has_currency_compute = self._has_match(content, "field_patterns.currency_compute")
            
            # ORM indicators
            indicators.orm_calls_count = self._count_matches(content, "orm_patterns.orm_calls")
            indicators.has_search_browse = self._has_match(content, "orm_patterns.search_browse")
            indicators.has_sql_query = self._has_match(content, "orm_patterns.sql_query")
            
            # Cross-model detection (self.env['other.model'])
            cross_model_pattern = re.compile(r"self\.env\[['\"]([^'\"]+)['\"]\]")
            model_refs = cross_model_pattern.findall(content)
            indicators.cross_model_calls = len(set(model_refs)) > 1
            
            # Action indicators
            indicators.has_python_code = True  # It's Python
            indicators.has_external_api = self._has_match(content, "action_patterns.external_api")
            indicators.has_transaction = self._has_match(content, "action_patterns.transaction")
            indicators.has_multi_company = self._has_match(content, "action_patterns.multi_company")
            indicators.has_env_context = self._has_match(content, "action_patterns.env_context")
            
            # Control flow
            indicators.has_loop = self._has_match(content, "control_flow_patterns.loop")
            indicators.has_conditional = self._has_match(content, "control_flow_patterns.conditional")
            indicators.method_count = self._count_matches(content, "control_flow_patterns.method_def")
            
            # Report indicators
            indicators.has_custom_model = self._has_match(content, "report_patterns.report_model")
            indicators.has_barcode_qr = self._has_match(content, "report_patterns.barcode_qr")
        
        # View/XML indicators
        if file_type == "xml":
            indicators.xpath_count = self._count_matches(content, "view_patterns.xpath")
            indicators.has_attrs_domain = self._has_match(content, "view_patterns.attrs_domain")
            indicators.has_widget_override = self._has_match(content, "view_patterns.widget_override")
            indicators.has_js_class = self._has_match(content, "view_patterns.js_class")
            indicators.is_form_tree_kanban = self._has_match(content, "view_patterns.form_tree_kanban")
            
            # QWeb indicators
            indicators.has_qweb_directives = self._has_match(content, "qweb_patterns.qweb_directives")
            indicators.has_t_if = self._has_match(content, "qweb_patterns.t_if")
            indicators.has_t_foreach = self._has_match(content, "qweb_patterns.t_foreach")
            indicators.t_foreach_count = self._count_matches(content, "qweb_patterns.t_foreach")
            indicators.has_t_call = self._has_match(content, "qweb_patterns.t_call")
            indicators.has_t_raw = self._has_match(content, "qweb_patterns.t_raw")
            
            # Nested loops detection (t-foreach inside t-foreach)
            indicators.has_nested_loops = indicators.t_foreach_count > 1
            
            # PDF/Label detection
            indicators.is_pdf_output = "report" in content.lower() or "pdf" in content.lower()
            indicators.is_label_output = "label" in content.lower() or "barcode" in content.lower()
            
            # Report indicators (in XML)
            indicators.has_custom_paperformat = self._has_match(content, "report_patterns.paperformat")
            indicators.has_barcode_qr = self._has_match(content, "report_patterns.barcode_qr")
            
            # Domain filter detection
            indicators.has_domain_filter = "domain" in content.lower()
        
        return indicators


class ComplexityAnalyzer:
    """Main complexity analyzer that coordinates analysis across file types."""
    
    # File extension to analyzer mapping
    ANALYZERS = {
        ".py": PythonAnalyzer,
        ".xml": XMLAnalyzer,
        ".js": JavaScriptAnalyzer,
    }
    
    def __init__(self, config: EffortEstimatorConfig | None = None, 
                 complexity_rules: dict | None = None,
                 indicator_patterns: dict | None = None):
        """Initialize the complexity analyzer.
        
        Args:
            config: Effort estimator configuration
            complexity_rules: Component-type-specific complexity rules from time_metrics.json
            indicator_patterns: Regex patterns for detecting Odoo indicators
        """
        self.config = config or EffortEstimatorConfig()
        self._analyzers: dict[str, Any] = {}
        self.complexity_rules = complexity_rules or {}
        self.indicator_detector = OdooIndicatorDetector(indicator_patterns)
        self._source_contents: dict[Path, str] = {}  # Cache for indicator detection
    
    @classmethod
    def from_config_file(cls, config_path: Path, config: EffortEstimatorConfig | None = None) -> "ComplexityAnalyzer":
        """Create analyzer from a time_metrics.json config file.
        
        Args:
            config_path: Path to time_metrics.json
            config: Optional EffortEstimatorConfig
            
        Returns:
            Configured ComplexityAnalyzer instance
        """
        complexity_rules = {}
        indicator_patterns = {}
        
        if config_path.exists():
            try:
                with open(config_path) as f:
                    data = json.load(f)
                complexity_rules = data.get("complexity_rules", {})
                indicator_patterns = data.get("indicator_patterns", {})
            except (json.JSONDecodeError, IOError) as e:
                # Fall back to defaults
                pass
        
        return cls(
            config=config,
            complexity_rules=complexity_rules,
            indicator_patterns=indicator_patterns
        )
    
    def _get_analyzer(self, extension: str):
        """Get or create analyzer for file extension."""
        if extension not in self._analyzers:
            analyzer_class = self.ANALYZERS.get(extension)
            if analyzer_class:
                self._analyzers[extension] = analyzer_class()
        return self._analyzers.get(extension)
    
    def analyze_files(
        self, 
        file_paths: list[Path], 
        component_type: str | None = None,
        field_name: str | None = None
    ) -> ComplexityResult:
        """Analyze multiple source files.
        
        Args:
            file_paths: List of paths to analyze
            component_type: Optional component type (field, view, server_action, automation, report)
                          for component-specific complexity rules
            field_name: For field components, the specific field name to extract
                       (e.g., 'x_alt_product_uom_id'). If provided, only analyzes
                       the field definition and its compute method, not the whole file.
            
        Returns:
            ComplexityResult with aggregated metrics
        """
        combined = ComplexityMetrics()
        analyzed_files: list[Path] = []
        all_content: list[tuple[str, str]] = []  # (content, file_type)
        
        for path in file_paths:
            if not path.exists():
                combined.errors.append(f"File not found: {path}")
                continue
            
            ext = path.suffix.lower()
            analyzer = self._get_analyzer(ext)
            
            if not analyzer:
                # Unknown file type - just count lines
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                    lines = sum(1 for line in content.split('\n') if line.strip())
                    combined.loc += lines
                    combined.file_types.add(ext.lstrip('.') or "unknown")
                    combined.files_analyzed += 1
                    analyzed_files.append(path)
                    all_content.append((content, ext.lstrip('.') or "unknown"))
                except Exception as e:
                    combined.errors.append(f"Error reading {path}: {e}")
                continue
            
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                
                # For field components in Python files, extract only the specific field
                if field_name and ext == ".py" and isinstance(analyzer, PythonAnalyzer):
                    extracted = analyzer.extract_field_content(content, field_name)
                    if extracted:
                        # Analyze only the extracted field content
                        metrics = analyzer.analyze(extracted, path)
                        self._merge_metrics(combined, metrics)
                        analyzed_files.append(path)
                        all_content.append((extracted, ext.lstrip('.')))
                    else:
                        # Field not found - this might be a simple field with no definition
                        # Count as 1 LOC minimum
                        combined.loc += 1
                        combined.file_types.add("py")
                        combined.files_analyzed += 1
                        analyzed_files.append(path)
                        all_content.append((f"{field_name} = fields.Char()", "py"))
                else:
                    metrics = analyzer.analyze(content, path)
                    self._merge_metrics(combined, metrics)
                    analyzed_files.append(path)
                    all_content.append((content, ext.lstrip('.')))
            except Exception as e:
                combined.errors.append(f"Error analyzing {path}: {e}")
        
        # Detect Odoo indicators from all content
        combined.odoo_indicators = self._detect_all_indicators(all_content)
        
        # Check for test files
        combined.has_tests = self._check_for_tests(file_paths)
        
        # NO FALLBACK - fail if no files were successfully analyzed
        if combined.files_analyzed == 0:
            error_list = "\n".join(combined.errors) if combined.errors else "No errors recorded"
            raise ValueError(
                f"\n{'='*60}\n"
                f"FATAL ERROR: No files were successfully analyzed!\n"
                f"{'='*60}\n"
                f"Requested files: {[str(p) for p in file_paths]}\n"
                f"Errors:\n{error_list}\n"
                f"{'='*60}\n"
            )
        
        # Normalize metrics
        normalized = self._normalize_metrics(combined)
        
        # Calculate weighted score
        weighted_score = self._calculate_weighted_score(normalized)
        
        # Determine complexity label using component-type-specific rules
        # NO FALLBACK - component_type is REQUIRED
        if not component_type:
            raise ValueError(
                f"\n{'='*60}\n"
                f"FATAL ERROR: component_type is required!\n"
                f"{'='*60}\n"
                f"Cannot determine complexity without knowing the component type.\n"
                f"Pass component_type (field, view, server_action, automation, report)\n"
                f"{'='*60}\n"
            )
        
        if not self.complexity_rules:
            raise ValueError(
                f"\n{'='*60}\n"
                f"FATAL ERROR: No complexity rules loaded!\n"
                f"{'='*60}\n"
                f"complexity_rules is empty.\n"
                f"Ensure time_metrics.json is loaded with complexity_rules section.\n"
                f"{'='*60}\n"
            )
        
        complexity_label = self._component_type_to_label(
            component_type, combined, combined.odoo_indicators
        )
        
        # Find top contributors
        top_contributors = self._find_top_contributors(normalized)
        
        return ComplexityResult(
            raw_metrics=combined,
            normalized_metrics=normalized,
            weighted_score=weighted_score,
            complexity_label=complexity_label,
            top_contributors=top_contributors,
            source_files=analyzed_files,
        )
    
    def _detect_all_indicators(self, contents: list[tuple[str, str]]) -> OdooIndicators:
        """Detect and merge Odoo indicators from all source contents.
        
        Args:
            contents: List of (content, file_type) tuples
            
        Returns:
            Merged OdooIndicators
        """
        merged = OdooIndicators()
        
        for content, file_type in contents:
            indicators = self.indicator_detector.detect(content, file_type)
            
            # Merge boolean indicators (OR)
            merged.has_compute = merged.has_compute or indicators.has_compute
            merged.has_related = merged.has_related or indicators.has_related
            merged.has_currency_compute = merged.has_currency_compute or indicators.has_currency_compute
            merged.has_search_browse = merged.has_search_browse or indicators.has_search_browse
            merged.has_sql_query = merged.has_sql_query or indicators.has_sql_query
            merged.cross_model_calls = merged.cross_model_calls or indicators.cross_model_calls
            merged.has_attrs_domain = merged.has_attrs_domain or indicators.has_attrs_domain
            merged.has_widget_override = merged.has_widget_override or indicators.has_widget_override
            merged.has_js_class = merged.has_js_class or indicators.has_js_class
            merged.is_form_tree_kanban = merged.is_form_tree_kanban or indicators.is_form_tree_kanban
            merged.has_qweb_directives = merged.has_qweb_directives or indicators.has_qweb_directives
            merged.has_t_if = merged.has_t_if or indicators.has_t_if
            merged.has_t_foreach = merged.has_t_foreach or indicators.has_t_foreach
            merged.has_t_call = merged.has_t_call or indicators.has_t_call
            merged.has_t_raw = merged.has_t_raw or indicators.has_t_raw
            merged.has_nested_loops = merged.has_nested_loops or indicators.has_nested_loops
            merged.is_pdf_output = merged.is_pdf_output or indicators.is_pdf_output
            merged.is_label_output = merged.is_label_output or indicators.is_label_output
            merged.has_python_code = merged.has_python_code or indicators.has_python_code
            merged.has_external_api = merged.has_external_api or indicators.has_external_api
            merged.has_transaction = merged.has_transaction or indicators.has_transaction
            merged.has_multi_company = merged.has_multi_company or indicators.has_multi_company
            merged.has_env_context = merged.has_env_context or indicators.has_env_context
            merged.has_loop = merged.has_loop or indicators.has_loop
            merged.has_conditional = merged.has_conditional or indicators.has_conditional
            merged.has_custom_paperformat = merged.has_custom_paperformat or indicators.has_custom_paperformat
            merged.has_custom_model = merged.has_custom_model or indicators.has_custom_model
            merged.has_barcode_qr = merged.has_barcode_qr or indicators.has_barcode_qr
            merged.has_domain_filter = merged.has_domain_filter or indicators.has_domain_filter
            
            # Merge count indicators (SUM)
            merged.orm_calls_count += indicators.orm_calls_count
            merged.xpath_count += indicators.xpath_count
            merged.t_foreach_count += indicators.t_foreach_count
            merged.method_count += indicators.method_count
            merged.trigger_fields_count += indicators.trigger_fields_count
        
        return merged
    
    def _component_type_to_label(
        self, 
        component_type: str, 
        metrics: ComplexityMetrics,
        indicators: OdooIndicators
    ) -> str:
        """Determine complexity label using component-type-specific rules.
        
        Args:
            component_type: Component type (field, view, server_action, automation, report)
            metrics: Raw complexity metrics
            indicators: Detected Odoo indicators
            
        Returns:
            Complexity label (simple, medium, complex, very_complex)
            
        Raises:
            ValueError: If no rules defined for component type or no level matches
        """
        rules = self.complexity_rules.get(component_type)
        if not rules:
            raise ValueError(
                f"\n{'='*60}\n"
                f"FATAL ERROR: No complexity rules for component type!\n"
                f"{'='*60}\n"
                f"Component type: {component_type}\n"
                f"Available types: {list(self.complexity_rules.keys())}\n\n"
                f"Add rules for '{component_type}' to time_metrics.json\n"
                f"{'='*60}\n"
            )
        
        loc = metrics.loc
        
        # Check from simplest to most complex - return FIRST level that matches
        # This ensures we get the lowest applicable complexity level
        for level in ["simple", "medium", "complex", "very_complex"]:
            level_rules = rules.get(level, {})
            if self._matches_level(level, level_rules, loc, indicators):
                return level
        
        # NO FALLBACK - fail with clear error
        raise ValueError(
            f"\n{'='*60}\n"
            f"FATAL ERROR: Cannot determine complexity level!\n"
            f"{'='*60}\n"
            f"Component type: {component_type}\n"
            f"LOC: {loc}\n"
            f"Indicators: {indicators}\n\n"
            f"No complexity level matched in time_metrics.json rules.\n"
            f"Check complexity_rules.{component_type} thresholds.\n"
            f"{'='*60}\n"
        )
    
    def _matches_level(
        self, 
        level: str,
        rules: dict, 
        loc: int, 
        indicators: OdooIndicators
    ) -> bool:
        """Check if LOC matches a complexity level's rules.
        
        LOC thresholds are the ONLY determinant of complexity.
        Indicators are informational only - they don't affect matching.
        
        Args:
            level: Complexity level name
            rules: Rules for this level
            loc: Lines of code
            indicators: Detected indicators (not used for matching)
            
        Returns:
            True if LOC matches this level's thresholds
        """
        if not rules:
            return False
        
        # Check LOC thresholds - this is the ONLY determinant
        max_loc = rules.get("max_loc")
        min_loc = rules.get("min_loc")
        
        # For very_complex, we check min_loc
        if min_loc is not None:
            if loc < min_loc:
                return False
            # If min_loc matches and no max_loc, this level matches
            if max_loc is None:
                return True
        
        # For simple/medium/complex, we check max_loc
        if max_loc is not None:
            if loc > max_loc:
                return False
            # If max_loc matches, this level matches
            return True
        
        return False
    
    def analyze_directory(
        self, 
        directory: Path, 
        patterns: list[str] | None = None,
        component_type: str | None = None
    ) -> ComplexityResult:
        """Analyze all matching files in a directory.
        
        Args:
            directory: Directory to analyze
            patterns: Glob patterns to match (defaults to *.py, *.xml, *.js)
            component_type: REQUIRED component type for complexity rules
            
        Returns:
            ComplexityResult with aggregated metrics
            
        Raises:
            ValueError: If component_type is not provided
        """
        if patterns is None:
            patterns = ["**/*.py", "**/*.xml", "**/*.js"]
        
        files = []
        for pattern in patterns:
            files.extend(directory.glob(pattern))
        
        return self.analyze_files(files, component_type=component_type)
    
    def _merge_metrics(self, target: ComplexityMetrics, source: ComplexityMetrics) -> None:
        """Merge source metrics into target."""
        target.loc += source.loc
        target.functions_count += source.functions_count
        target.total_cyclomatic_complexity += source.total_cyclomatic_complexity
        target.branches_count += source.branches_count
        target.sql_queries_count += source.sql_queries_count
        target.external_calls_count += source.external_calls_count
        target.ui_elements_count += source.ui_elements_count
        target.dynamic_code_flags = max(target.dynamic_code_flags, source.dynamic_code_flags)
        target.file_types.update(source.file_types)
        target.files_analyzed += source.files_analyzed
        target.errors.extend(source.errors)
        
        # Recalculate average CC
        if target.functions_count > 0:
            target.avg_cyclomatic_complexity = (
                target.total_cyclomatic_complexity / target.functions_count
            )
        target.max_cyclomatic_complexity = max(
            target.max_cyclomatic_complexity, 
            source.max_cyclomatic_complexity
        )
    
    def _check_for_tests(self, file_paths: list[Path]) -> bool:
        """Check if any test files exist for the analyzed files."""
        for path in file_paths:
            # Check for test file with same name
            test_name = f"test_{path.name}"
            test_path = path.parent / test_name
            if test_path.exists():
                return True
            
            # Check in tests directory
            tests_dir = path.parent.parent / "tests"
            if tests_dir.exists():
                test_file = tests_dir / test_name
                if test_file.exists():
                    return True
        
        return False
    
    def _normalize_metrics(self, metrics: ComplexityMetrics) -> NormalizedMetrics:
        """Normalize raw metrics to 0.0-1.0 scale."""
        limits = self.config.limits
        
        # Log scale for LOC
        loc_norm = min(1.0, math.log1p(metrics.loc) / math.log1p(limits.loc_max))
        
        # Linear clamping for other metrics
        def normalize(value: float, max_val: int) -> float:
            return min(1.0, value / max_val) if max_val > 0 else 0.0
        
        return NormalizedMetrics(
            loc=loc_norm,
            functions_count=normalize(metrics.functions_count, limits.functions_max),
            avg_cyclomatic_complexity=normalize(
                metrics.avg_cyclomatic_complexity, 
                limits.cyclomatic_complexity_max
            ),
            branches_count=normalize(metrics.branches_count, limits.branches_max),
            sql_queries_count=normalize(metrics.sql_queries_count, limits.sql_queries_max),
            external_calls_count=normalize(metrics.external_calls_count, limits.external_calls_max),
            ui_elements_count=normalize(metrics.ui_elements_count, limits.ui_elements_max),
            dynamic_code_flags=float(min(1, metrics.dynamic_code_flags)),
            file_types_mix=normalize(metrics.file_types_count, 5),  # Max 5 file types
            test_coverage_flag=1.0 if metrics.has_tests else 0.0,
        )
    
    def _calculate_weighted_score(self, normalized: NormalizedMetrics) -> float:
        """Calculate weighted complexity score."""
        weights = self.config.weights
        
        score = (
            normalized.loc * weights.loc +
            normalized.functions_count * weights.functions_count +
            normalized.avg_cyclomatic_complexity * weights.avg_cyclomatic_complexity +
            normalized.branches_count * weights.branches_count +
            normalized.sql_queries_count * weights.sql_queries_count +
            normalized.external_calls_count * weights.external_calls_count +
            normalized.ui_elements_count * weights.ui_elements_count +
            normalized.dynamic_code_flags * weights.dynamic_code_flags +
            normalized.file_types_mix * weights.file_types_mix +
            normalized.test_coverage_flag * weights.test_coverage_flag  # Negative weight
        )
        
        return max(0.0, score)  # Ensure non-negative
    
    def _score_to_label(self, score: float) -> str:
        """Convert complexity score to label."""
        thresholds = self.config.thresholds
        
        if score < thresholds.simple_max:
            return "simple"
        elif score < thresholds.medium_max:
            return "medium"
        elif score < thresholds.complex_max:
            return "complex"
        else:
            return "very_complex"
    
    def _find_top_contributors(
        self, 
        normalized: NormalizedMetrics, 
        top_n: int = 3
    ) -> list[tuple[str, float]]:
        """Find the top contributing metrics to the complexity score."""
        weights = self.config.weights
        metrics_dict = normalized.to_dict()
        
        contributions = []
        for name, value in metrics_dict.items():
            weight = getattr(weights, name, 0.0)
            contribution = value * weight
            if contribution > 0:  # Skip negative contributors and zero
                contributions.append((name, contribution))
        
        # Sort by contribution descending
        contributions.sort(key=lambda x: x[1], reverse=True)
        
        return contributions[:top_n]


def resolve_source_location(source_location: str, base_path: Path) -> list[Path]:
    """Resolve a source_location string to actual file paths.
    
    Handles:
    - Direct file paths
    - Glob patterns
    - Directory paths (returns all matching files)
    
    Args:
        source_location: Source location string from TODO
        base_path: Base path to resolve relative paths against
        
    Returns:
        List of resolved file paths
    """
    # Remove leading/trailing whitespace and backticks
    source_location = source_location.strip().strip('`')
    
    # Handle absolute paths
    path = Path(source_location)
    if path.is_absolute():
        if path.exists():
            if path.is_file():
                return [path]
            elif path.is_dir():
                return list(path.glob("**/*.py")) + list(path.glob("**/*.xml"))
        return []
    
    # Resolve relative to base path
    resolved = base_path / source_location
    
    if resolved.exists():
        if resolved.is_file():
            return [resolved]
        elif resolved.is_dir():
            return list(resolved.glob("**/*.py")) + list(resolved.glob("**/*.xml"))
    
    # Try as glob pattern
    if '*' in source_location:
        return list(base_path.glob(source_location))
    
    return []
