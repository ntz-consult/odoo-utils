"""Effort Estimator for TODO output.

Computes source-based complexity metrics and produces accurate time estimates.
This is Phase 2 of the post-processing enrichment pipeline.

KEY PRINCIPLE:
    Reads DIRECTLY from feature_user_story_map.toml (the source of truth).
    Does NOT parse TODO markdown.
    Uses source_location from TOML to access source files for analysis.

Usage:
    python -m shared.python.effort_estimator project_root -o final_todo.md
"""

import argparse
import json
import logging
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from .complexity_analyzer import (
        ComplexityAnalyzer,
        ComplexityResult,
        resolve_source_location,
    )
    from .enricher_config import EnricherConfig, EffortEstimatorConfig
except ImportError:
    from complexity_analyzer import (
        ComplexityAnalyzer,
        ComplexityResult,
        resolve_source_location,
    )
    from enricher_config import EnricherConfig, EffortEstimatorConfig


logger = logging.getLogger(__name__)


# =============================================================================
# Time Metrics Classes
# =============================================================================

@dataclass
class TimeBreakdown:
    """Breakdown of hours by activity type."""

    development: float
    requirements: float
    testing: float

    @property
    def total(self) -> float:
        """Total hours across all activities."""
        return self.development + self.requirements + self.testing


@dataclass
class TimeMetrics:
    """Time metrics configuration loaded from JSON."""

    metrics: dict[str, dict[str, dict[str, float]]]
    # Structure: {component_type: {complexity: {dev, req, test}}}
    
    complexity_rules: dict  # Complexity rules for the analyzer

    @classmethod
    def from_file(cls, path: Path) -> "TimeMetrics":
        """Load time metrics from JSON file.

        Args:
            path: Path to time_metrics.json

        Returns:
            TimeMetrics instance
            
        Raises:
            FileNotFoundError: If time_metrics.json does not exist
            ValueError: If file is invalid or missing required sections
        """
        if not path.exists():
            raise FileNotFoundError(
                f"\n{'='*60}\n"
                f"FATAL ERROR: time_metrics.json not found!\n"
                f"{'='*60}\n"
                f"Expected location: {path}\n\n"
                f"This file is REQUIRED for effort estimation.\n"
                f"Copy templates/time_metrics.json to your project.\n"
                f"{'='*60}\n"
            )
        
        with open(path) as f:
            data = json.load(f)
        
        metrics = data.get("time_metrics")
        if not metrics:
            raise ValueError(
                f"\n{'='*60}\n"
                f"FATAL ERROR: Invalid time_metrics.json!\n"
                f"{'='*60}\n"
                f"File: {path}\n"
                f"Missing 'time_metrics' section.\n"
                f"{'='*60}\n"
            )
        
        complexity_rules = data.get("complexity_rules")
        if not complexity_rules:
            raise ValueError(
                f"\n{'='*60}\n"
                f"FATAL ERROR: Invalid time_metrics.json!\n"
                f"{'='*60}\n"
                f"File: {path}\n"
                f"Missing 'complexity_rules' section.\n"
                f"{'='*60}\n"
            )
        
        return cls(metrics=metrics, complexity_rules=complexity_rules)

    def get_hours(self, component_type: str, complexity: str) -> TimeBreakdown:
        """Get time breakdown for a component type and complexity.

        Args:
            component_type: Component type (field, view, etc.)
            complexity: Complexity level (simple, medium, complex, very_complex)

        Returns:
            TimeBreakdown with hours for each activity
            
        Raises:
            ValueError: If component_type or complexity not found in metrics
        """
        type_metrics = self.metrics.get(component_type)
        if not type_metrics:
            raise ValueError(
                f"Unknown component type '{component_type}'. "
                f"Valid types: {list(self.metrics.keys())}"
            )
        
        level_metrics = type_metrics.get(complexity)
        if not level_metrics:
            raise ValueError(
                f"Unknown complexity '{complexity}' for {component_type}. "
                f"Valid levels: {list(type_metrics.keys())}"
            )
        
        return TimeBreakdown(
            development=level_metrics.get("dev", 0),
            requirements=level_metrics.get("req", 0),
            testing=level_metrics.get("test", 0),
        )


# =============================================================================
# TOML Data Classes
# =============================================================================

@dataclass
class TomlComponent:
    """A component from feature_user_story_map.toml."""
    
    ref: str
    source_location: str | None = None
    component_type: str = ""
    model: str = ""
    name: str = ""
    
    @classmethod
    def from_toml_item(cls, item: dict | str) -> "TomlComponent":
        """Create from TOML component item (string or dict with ref/source_location)."""
        if isinstance(item, dict):
            ref = item.get("ref", "")
            source_location = item.get("source_location")
        else:
            ref = str(item)
            source_location = None
        
        # Parse ref: type.model.name format
        parts = ref.split(".", 2)
        if len(parts) >= 3:
            comp_type = parts[0]
            model = parts[1].replace("_", ".")
            name = parts[2]
        elif len(parts) == 2:
            comp_type = parts[0]
            model = "unknown"
            name = parts[1]
        else:
            comp_type = "unknown"
            model = "unknown"
            name = ref
        
        return cls(
            ref=ref,
            source_location=source_location,
            component_type=comp_type,
            model=model,
            name=name,
        )


@dataclass
class TomlUserStory:
    """A user story from feature_user_story_map.toml."""
    
    name: str  # The user story name (key in TOML)
    description: str  # The description (property in TOML)
    sequence: int
    components: list[TomlComponent]


@dataclass
class TomlFeature:
    """A feature from feature_user_story_map.toml."""
    
    name: str
    description: str
    sequence: int
    user_stories: list[TomlUserStory]
    enrich_status: str = "refresh-all"
    task_id: int = 0
    tags: str = "Feature"


@dataclass
class EstimatedComponent:
    """A component with computed effort estimates."""
    
    component: TomlComponent
    complexity_result: ComplexityResult | None
    computed_score: float
    computed_label: str
    baseline_hours: TimeBreakdown
    adjusted_hours: TimeBreakdown
    loc: int = 0
    top_contributors: list[tuple[str, float]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    is_fallback: bool = False


@dataclass 
class EstimatedUserStory:
    """A user story with estimated components."""
    
    name: str
    description: str
    sequence: int
    components: list[EstimatedComponent]
    total_hours: float = 0.0


@dataclass
class EstimatedFeature:
    """A feature with estimated user stories."""
    
    name: str
    description: str
    sequence: int
    user_stories: list[EstimatedUserStory]
    total_hours: float = 0.0


class TomlLoader:
    """Load features directly from feature_user_story_map.toml."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.studio_dir = project_root / "studio"
        self.map_file = self.studio_dir / "feature_user_story_map.toml"
    
    def load_features(self) -> list[TomlFeature]:
        """Load all features from TOML.
        
        Returns:
            List of TomlFeature objects with components
        """
        if not self.map_file.exists():
            raise ValueError(f"feature_user_story_map.toml not found: {self.map_file}")
        
        with open(self.map_file, "rb") as f:
            data = tomllib.load(f)
        
        features_data = data.get("features", {})
        features = []
        
        for feature_name, feature_def in features_data.items():
            # Skip deprecated features
            if feature_def.get("_deprecated"):
                continue
            
            user_stories = []
            user_stories_data = feature_def.get("user_stories", {})
            
            # Handle both dict format (new) and list format (legacy)
            if isinstance(user_stories_data, dict):
                for story_name, story_data in user_stories_data.items():
                    components = [
                        TomlComponent.from_toml_item(item)
                        for item in story_data.get("components", [])
                    ]
                    
                    user_stories.append(TomlUserStory(
                        name=story_name,
                        description=story_data.get("description", ""),
                        sequence=story_data.get("sequence", 999),
                        components=components,
                    ))
            else:
                # Legacy list format
                for story_data in user_stories_data:
                    story_name = story_data.get("description", "Unnamed User Story")
                    components = [
                        TomlComponent.from_toml_item(item)
                        for item in story_data.get("components", [])
                    ]
                    
                    user_stories.append(TomlUserStory(
                        name=story_name,
                        description=story_data.get("description", ""),
                        sequence=story_data.get("sequence", 999),
                        components=components,
                    ))
            
            features.append(TomlFeature(
                name=feature_name,
                description=feature_def.get("description", feature_name),
                sequence=feature_def.get("sequence", 999),
                enrich_status=feature_def.get("enrich-status", "refresh-all"),
                task_id=feature_def.get("task_id", 0),
                tags=feature_def.get("tags", "Feature"),
                user_stories=user_stories,
            ))
        
        # Sort by sequence
        features.sort(key=lambda f: (f.sequence, f.name))
        return features


class EffortCalculator:
    """Calculate effort estimates based on complexity analysis."""
    
    def __init__(
        self, 
        config: EffortEstimatorConfig,
        time_metrics: TimeMetrics,
        project_root: Path | None = None,
    ):
        """Initialize the effort calculator.
        
        Args:
            config: Effort estimator configuration
            time_metrics: Time metrics (REQUIRED - loaded from time_metrics.json)
            project_root: Project root for resolving source paths
        """
        self.config = config
        self.time_metrics = time_metrics
        # Pass complexity_rules from time_metrics to the analyzer
        self.analyzer = ComplexityAnalyzer(
            config, 
            complexity_rules=time_metrics.complexity_rules
        )
        self.project_root = project_root or Path.cwd()
    
    def estimate_component(self, component: TomlComponent) -> EstimatedComponent:
        """Estimate effort for a single component.
        
        Uses source_location directly from TOML to find source files.
        
        Args:
            component: TomlComponent to estimate
            
        Returns:
            EstimatedComponent with estimates
        """
        notes = []
        complexity_result = None
        
        # Resolve and analyze source files using source_location from TOML
        # NO FALLBACK - source_location is REQUIRED
        if not component.source_location:
            raise ValueError(
                f"\n{'='*60}\n"
                f"FATAL ERROR: No source_location for component!\n"
                f"{'='*60}\n"
                f"Component: {component.ref}\n"
                f"Type: {component.component_type}\n\n"
                f"source_location is REQUIRED for effort estimation.\n"
                f"Add source_location to the TOML entry.\n"
                f"{'='*60}\n"
            )
        
        source_files = resolve_source_location(
            component.source_location, 
            self.project_root
        )
        
        if not source_files:
            raise ValueError(
                f"\n{'='*60}\n"
                f"FATAL ERROR: Source file not found!\n"
                f"{'='*60}\n"
                f"Component: {component.ref}\n"
                f"source_location: {component.source_location}\n"
                f"project_root: {self.project_root}\n\n"
                f"Cannot estimate effort without source code.\n"
                f"{'='*60}\n"
            )
        
        # Extract field name for field components
        # Ref format: field.model.field_name (e.g., field.sale_order_line.x_alt_product_uom_id)
        field_name = None
        component_type_key = component.component_type.lower().replace(" ", "_")
        if component_type_key == "field":
            ref_parts = component.ref.split(".")
            if len(ref_parts) >= 3:
                # Last part is the field name
                field_name = ref_parts[-1]
        
        complexity_result = self.analyzer.analyze_files(
            source_files, 
            component_type=component_type_key,
            field_name=field_name
        )
        
        if complexity_result.raw_metrics.errors:
            notes.extend(complexity_result.raw_metrics.errors[:2])
        
        # Get complexity label from analysis - NO FALLBACK
        computed_score = complexity_result.weighted_score
        computed_label = complexity_result.complexity_label
        
        # Get baseline hours based on component type
        type_key = component.component_type.lower().replace(" ", "_")
        baseline_hours = self.time_metrics.get_hours(type_key, computed_label)
        
        # Calculate multiplier
        multiplier = self._get_multiplier(computed_label)
        
        # Apply adjustments
        adjusted_hours = TimeBreakdown(
            development=round(baseline_hours.development * multiplier, 1),
            requirements=round(baseline_hours.requirements * multiplier, 1),
            testing=round(baseline_hours.testing * multiplier, 1),
        )
        
        # Get top contributors from analysis
        top_contributors = complexity_result.top_contributors
        
        # Extract LOC from complexity analysis
        loc = complexity_result.raw_metrics.loc
        
        return EstimatedComponent(
            component=component,
            complexity_result=complexity_result,
            computed_score=round(computed_score, 2),
            computed_label=computed_label,
            baseline_hours=baseline_hours,
            adjusted_hours=adjusted_hours,
            loc=loc,
            top_contributors=top_contributors,
            notes=notes,
            is_fallback=False,  # Never fallback anymore - we fail instead
        )
    
    def _get_multiplier(self, label: str) -> float:
        """Get time multiplier for complexity label."""
        multipliers = self.config.multipliers
        label_key = label.lower().replace(" ", "_")
        
        return {
            "simple": multipliers.simple,
            "medium": multipliers.medium,
            "complex": multipliers.complex,
            "very_complex": multipliers.very_complex,
        }.get(label_key, 1.0)
    
    def estimate_feature(self, feature: TomlFeature) -> EstimatedFeature:
        """Estimate all components in a feature."""
        estimated_stories = []
        feature_total = 0.0
        
        for story in feature.user_stories:
            estimated_components = [
                self.estimate_component(comp)
                for comp in story.components
            ]
            
            story_total = sum(ec.adjusted_hours.total for ec in estimated_components)
            feature_total += story_total
            
            estimated_stories.append(EstimatedUserStory(
                name=story.name,
                description=story.description,
                sequence=story.sequence,
                components=estimated_components,
                total_hours=round(story_total, 1),
            ))
        
        return EstimatedFeature(
            name=feature.name,
            description=feature.description,
            sequence=feature.sequence,
            user_stories=estimated_stories,
            total_hours=round(feature_total, 1),
        )


class MarkdownGenerator:
    """Generate TODO markdown with effort estimates."""
    
    def __init__(self, config: EffortEstimatorConfig):
        self.config = config
    
    def generate(
        self, 
        features: list[EstimatedFeature], 
        project_name: str = "Project"
    ) -> str:
        """Generate TODO markdown with effort estimates.
        
        Args:
            features: List of estimated features
            project_name: Name for the project header
            
        Returns:
            Complete TODO markdown content
        """
        lines = [
            f"# {project_name} - Implementation TODO",
            "",
            "*Generated with effort estimates from source analysis*",
            "",
        ]
        
        # Summary statistics
        total_hours = sum(f.total_hours for f in features)
        total_stories = sum(len(f.user_stories) for f in features)
        total_components = sum(
            len(s.components) for f in features for s in f.user_stories
        )
        fallback_count = sum(
            1 for f in features 
            for s in f.user_stories 
            for c in s.components 
            if c.is_fallback
        )
        
        lines.extend([
            "## Summary",
            "",
            f"- **Features:** {len(features)}",
            f"- **User Stories:** {total_stories}",
            f"- **Components:** {total_components}",
            f"- **Total Estimated Hours:** {total_hours:.1f}h",
            f"- **Components with source:** {total_components - fallback_count}/{total_components}",
            "",
            "---",
            "",
        ])
        
        # Render each feature
        for feature in features:
            lines.extend(self._render_feature(feature))
            lines.append("")
        
        return "\n".join(lines)
    
    def _render_feature(self, feature: EstimatedFeature) -> list[str]:
        """Render a single feature as markdown."""
        lines = [
            f"## Feature: {feature.name}",
            "",
            f"**Total Hours:** {feature.total_hours:.1f}h",
            "",
        ]
        
        # Render user stories
        for i, story in enumerate(feature.user_stories, 1):
            lines.extend(self._render_user_story(story, i))
            lines.append("")
        
        return lines
    
    def _render_user_story(self, story: EstimatedUserStory, index: int) -> list[str]:
        """Render a single user story as markdown."""
        lines = [
            f"### User Story {index}: {story.description}",
            "",
            f"**Estimated Hours:** {story.total_hours:.1f}h",
            "",
        ]
        
        # Render components
        for comp_est in story.components:
            lines.extend(self._render_component(comp_est))
        
        return lines
    
    def _render_component(self, estimate: EstimatedComponent) -> list[str]:
        """Render a component with effort estimate."""
        comp = estimate.component
        
        lines = [
            f"#### Component: `{comp.ref}`",
            "",
        ]
        
        if comp.model and comp.model != "unknown":
            lines.append(f"- **Model:** {comp.model}")
        
        if comp.source_location:
            lines.append(f"- **Source:** `{comp.source_location}`")
        
        # Complexity info
        lines.append(
            f"- **Complexity:** `{estimate.computed_score}` → **{estimate.computed_label}**"
        )
        
        # Time estimates
        adjusted = estimate.adjusted_hours
        lines.append(
            f"- **Hours:** Dev {adjusted.development}h / "
            f"Req {adjusted.requirements}h / "
            f"Test {adjusted.testing}h "
            f"(total **{adjusted.total:.1f}h**)"
        )
        
        # Top contributors
        if estimate.top_contributors and self.config.include_top_contributors:
            contributors = ", ".join(
                f"{name} ({value:.2f})" 
                for name, value in estimate.top_contributors
            )
            lines.append(f"- **Complexity drivers:** {contributors}")
        
        # Notes/warnings
        if estimate.notes:
            for note in estimate.notes:
                lines.append(f"- *{note}*")
        
        lines.append("")
        
        return lines


class EffortEstimator:
    """Main class for effort estimation.
    
    Reads directly from feature_user_story_map.toml and uses source_location
    to analyze source files for complexity metrics.
    """
    
    def __init__(
        self,
        config: EnricherConfig | None = None,
        time_metrics: TimeMetrics | None = None,
    ):
        """Initialize the effort estimator.
        
        Args:
            config: Enricher configuration
            time_metrics: Time metrics for baseline hours (if None, will be loaded from file)
        """
        self.config = config or EnricherConfig.default()
        self.ee_config = self.config.effort_estimator
        self.time_metrics = time_metrics
    
    def _get_time_metrics(self, project_root: Path) -> TimeMetrics:
        """Get time metrics, loading from file if needed.
        
        Args:
            project_root: Project root to search for time_metrics.json
            
        Returns:
            TimeMetrics instance
            
        Raises:
            FileNotFoundError: If time_metrics.json not found
        """
        if self.time_metrics:
            return self.time_metrics
        
        # Look for time_metrics.json in project
        metrics_path = project_root / "templates" / "time_metrics.json"
        if not metrics_path.exists():
            metrics_path = project_root / "time_metrics.json"
        
        return TimeMetrics.from_file(metrics_path)
    
    def estimate(
        self,
        project_root: Path,
        verbose: bool = False,
    ) -> tuple[str, list[EstimatedFeature]]:
        """Estimate effort for all components from TOML.
        
        Args:
            project_root: Path to project root (contains studio/ folder)
            verbose: If True, log detailed metrics
            
        Returns:
            Tuple of (markdown content, list of estimated features)
        """
        # Load features directly from TOML
        loader = TomlLoader(project_root)
        features = loader.load_features()
        
        if not features:
            logger.warning("No features found in feature_user_story_map.toml")
            return "# No features found\n", []
        
        logger.info(f"Loaded {len(features)} features from TOML")
        
        # Get time metrics (will raise if not found)
        time_metrics = self._get_time_metrics(project_root)
        
        # Create calculator with project root for source resolution
        calculator = EffortCalculator(
            self.ee_config,
            time_metrics,
            project_root,
        )
        
        # Estimate each feature
        estimated_features = []
        for feature in features:
            logger.info(f"Estimating feature: {feature.name}")
            estimated = calculator.estimate_feature(feature)
            estimated_features.append(estimated)
            
            if verbose:
                self._log_feature_estimate(estimated)
        
        # Generate markdown
        generator = MarkdownGenerator(self.ee_config)
        project_name = project_root.name
        markdown = generator.generate(estimated_features, project_name)
        
        # Log summary
        total_hours = sum(f.total_hours for f in estimated_features)
        total_components = sum(
            len(s.components) for f in estimated_features for s in f.user_stories
        )
        fallback_count = sum(
            1 for f in estimated_features 
            for s in f.user_stories 
            for c in s.components 
            if c.is_fallback
        )
        
        logger.info(f"Estimation complete:")
        logger.info(f"  Total hours: {total_hours:.1f}h")
        logger.info(f"  Components with source: {total_components - fallback_count}/{total_components}")
        
        return markdown, estimated_features
    
    def _log_feature_estimate(self, feature: EstimatedFeature) -> None:
        """Log detailed estimate for a feature."""
        logger.info(f"\n{feature.name}: {feature.total_hours:.1f}h total")
        for story in feature.user_stories:
            logger.info(f"  {story.description}: {story.total_hours:.1f}h")
            for comp in story.components:
                status = "✓" if not comp.is_fallback else "✗"
                logger.info(
                    f"    {status} {comp.component.ref}: "
                    f"{comp.adjusted_hours.total:.1f}h ({comp.computed_label})"
                )
    
    def estimate_and_save(
        self,
        project_root: Path,
        output_path: Path | None = None,
        **kwargs
    ) -> tuple[str, list[EstimatedFeature]]:
        """Estimate and save to file.
        
        Args:
            project_root: Path to project root
            output_path: Path for output (defaults to studio/TODO.estimated.md)
            **kwargs: Additional arguments for estimate()
            
        Returns:
            Tuple of (markdown content, list of estimated features)
        """
        markdown, features = self.estimate(project_root, **kwargs)
        
        if output_path is None:
            output_path = project_root / "studio" / "TODO.estimated.md"
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
        logger.info(f"Wrote estimated output to {output_path}")
        
        return markdown, features
    
    def export_metrics_json(
        self, 
        features: list[EstimatedFeature],
        output_path: Path
    ) -> None:
        """Export detailed metrics as JSON for analysis.
        
        Args:
            features: List of estimated features
            output_path: Path for JSON output
        """
        total_components = sum(
            len(s.components) for f in features for s in f.user_stories
        )
        total_hours = sum(f.total_hours for f in features)
        fallback_count = sum(
            1 for f in features 
            for s in f.user_stories 
            for c in s.components 
            if c.is_fallback
        )
        
        data = {
            "summary": {
                "total_features": len(features),
                "total_components": total_components,
                "total_hours": total_hours,
                "components_with_source": total_components - fallback_count,
            },
            "features": []
        }
        
        for feature in features:
            feature_data = {
                "name": feature.name,
                "total_hours": feature.total_hours,
                "user_stories": []
            }
            
            for story in feature.user_stories:
                story_data = {
                    "description": story.description,
                    "total_hours": story.total_hours,
                    "components": []
                }
                
                for est in story.components:
                    comp_data = {
                        "ref": est.component.ref,
                        "type": est.component.component_type,
                        "model": est.component.model,
                        "source_location": est.component.source_location,
                        "computed_score": est.computed_score,
                        "computed_label": est.computed_label,
                        "loc": est.loc,
                        "hours": {
                            "development": est.adjusted_hours.development,
                            "requirements": est.adjusted_hours.requirements,
                            "testing": est.adjusted_hours.testing,
                            "total": est.adjusted_hours.total,
                        },
                        "is_fallback": est.is_fallback,
                        "notes": est.notes,
                    }
                    
                    # Add raw metrics if available
                    if est.complexity_result and not est.is_fallback:
                        raw = est.complexity_result.raw_metrics
                        comp_data["raw_metrics"] = {
                            "loc": raw.loc,
                            "functions_count": raw.functions_count,
                            "avg_cyclomatic_complexity": raw.avg_cyclomatic_complexity,
                            "branches_count": raw.branches_count,
                            "sql_queries_count": raw.sql_queries_count,
                            "external_calls_count": raw.external_calls_count,
                            "ui_elements_count": raw.ui_elements_count,
                            "dynamic_code_flags": raw.dynamic_code_flags,
                            "file_types": list(raw.file_types),
                            "has_tests": raw.has_tests,
                            "files_analyzed": raw.files_analyzed,
                        }
                    
                    story_data["components"].append(comp_data)
                
                feature_data["user_stories"].append(story_data)
            
            data["features"].append(feature_data)
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Exported metrics to {output_path}")


def main():
    """CLI entry point for effort estimator."""
    parser = argparse.ArgumentParser(
        description="Add effort estimates to TODO (reads from feature_user_story_map.toml)"
    )
    parser.add_argument(
        "project_root",
        type=Path,
        help="Project root directory (contains studio/ folder)"
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Output file path (default: studio/TODO.estimated.md)"
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to enricher configuration TOML file"
    )
    parser.add_argument(
        "--metrics-json",
        type=Path,
        help="Export detailed metrics as JSON"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging with detailed metrics"
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s"
    )
    
    # Validate project root
    if not args.project_root.exists():
        logger.error(f"Project root not found: {args.project_root}")
        sys.exit(1)
    
    studio_dir = args.project_root / "studio"
    if not studio_dir.exists():
        logger.error(f"Studio folder not found: {studio_dir}")
        sys.exit(1)
    
    map_file = studio_dir / "feature_user_story_map.toml"
    if not map_file.exists():
        logger.error(f"feature_user_story_map.toml not found: {map_file}")
        sys.exit(1)
    
    # Load configuration
    if args.config and args.config.exists():
        config = EnricherConfig.from_file(args.config)
    else:
        config = EnricherConfig.default()
    
    # Create estimator and run
    try:
        estimator = EffortEstimator(config)
        markdown, features = estimator.estimate_and_save(
            args.project_root,
            args.output,
            verbose=args.verbose,
        )
        
        # Export metrics if requested
        if args.metrics_json:
            estimator.export_metrics_json(features, args.metrics_json)
        
        output_file = args.output or (studio_dir / "TODO.estimated.md")
        print(f"✓ Estimated output written to: {output_file}")
        
        # Print summary
        total_hours = sum(f.total_hours for f in features)
        print(f"  Total estimated hours: {total_hours:.1f}h")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        if args.verbose:
            raise
        sys.exit(1)


if __name__ == "__main__":
    main()
