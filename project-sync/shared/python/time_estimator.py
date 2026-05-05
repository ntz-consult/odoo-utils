"""Time estimation for Odoo Studio components.

Calculates development hours based on component type and complexity.
"""

import json
from dataclasses import dataclass
from pathlib import Path

try:
    from .feature_detector import Component, ComponentType, Feature, UserStory
except ImportError:
    from feature_detector import Component, ComponentType, Feature, UserStory


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

    @classmethod
    def from_file(cls, path: Path) -> "TimeMetrics":
        """Load time metrics from JSON file.

        Args:
            path: Path to time_metrics.json

        Returns:
            TimeMetrics instance
            
        Raises:
            FileNotFoundError: If time_metrics.json does not exist
            ValueError: If file is invalid or missing time_metrics section
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
        
        return cls(metrics=metrics)

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


# Map various complexity strings to normalized values
COMPLEXITY_MAP = {
    "simple": "simple",
    "moderate": "medium",
    "medium": "medium",
    "complex": "complex",
    "very_complex": "very_complex",
    "very complex": "very_complex",
}


class TimeEstimator:
    """Estimate development time for components and features."""

    def __init__(self, metrics: TimeMetrics, strategy_name: str = "group_by_type"):
        """Initialize with time metrics and estimation strategy.

        Args:
            metrics: TimeMetrics instance
            strategy_name: Name of the time estimation strategy
        """
        self.metrics = metrics
        try:
            from .time_estimation_strategies import TimeEstimationFactory
        except ImportError:
            from time_estimation_strategies import TimeEstimationFactory

        self.strategy = TimeEstimationFactory.create_strategy(strategy_name)

    def normalize_complexity(self, raw: str) -> str:
        """Normalize complexity string to standard value.

        Args:
            raw: Raw complexity string

        Returns:
            Normalized complexity (simple, medium, complex, very_complex)
        """
        return COMPLEXITY_MAP.get(raw.lower(), "medium")

    def estimate_component(self, component: Component) -> TimeBreakdown:
        """Estimate time for a single component.

        Args:
            component: Component to estimate

        Returns:
            TimeBreakdown with hours (0.0 if no source to evaluate)
        """
        # Check if component has no source to evaluate
        if isinstance(component.raw_data, dict) and component.raw_data.get("no_source_to_evaluate"):
            # Return zero hours - will be marked in display
            return TimeBreakdown(development=0.0, requirements=0.0, testing=0.0)
        
        complexity = self.normalize_complexity(component.complexity)
        return self.metrics.get_hours(
            component.component_type.value, complexity
        )

    def create_user_stories(
        self, feature: Feature, user_story_mapper=None
    ) -> list[UserStory]:
        """Create user stories from feature components.

        If user_story_mapper is provided, uses feature-user story mapping configuration.
        Otherwise, uses the configured estimation strategy.

        Args:
            feature: Feature with components
            user_story_mapper: Optional FeatureUserStoryMapper for custom grouping

        Returns:
            List of UserStory objects
        """
        if user_story_mapper:
            return user_story_mapper.get_user_stories_for_feature(
                feature, self
            )
        else:
            return self.strategy.create_user_stories(feature, self)

    def _create_default_user_stories(
        self, feature: Feature
    ) -> list[UserStory]:
        """Create user stories using default strategy (group by type).

        This is the original create_user_stories() logic, extracted
        for backward compatibility and fallback.

        Args:
            feature: Feature with components

        Returns:
            List of UserStory objects
        """
        # Use the default group_by_type strategy
        default_strategy = None
        try:
            from .time_estimation_strategies import GroupByTypeStrategy
            default_strategy = GroupByTypeStrategy()
        except ImportError:
            from time_estimation_strategies import GroupByTypeStrategy
            default_strategy = GroupByTypeStrategy()

        return default_strategy.create_user_stories(feature, self)

    def estimate_feature(self, feature: Feature) -> float:
        """Estimate total hours for a feature.

        Args:
            feature: Feature to estimate

        Returns:
            Total estimated hours
        """
        return sum(
            self.estimate_component(c).total for c in feature.components
        )
