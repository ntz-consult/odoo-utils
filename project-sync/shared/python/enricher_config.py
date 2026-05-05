"""Shared configuration for TODO enrichers.

Provides configuration dataclasses and loading for both:
- User Story Enricher (Phase 1)
- Effort Estimator (Phase 2)
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    import tomli as tomllib


@dataclass
class UserStoryEnricherConfig:
    """Configuration for the User Story Enricher."""
    
    enabled: bool = True
    ai_provider: str = "openai"
    model: str | None = None  # Uses provider default if not set
    temperature: float = 0.7
    max_stories_per_feature: int = 5
    output_mode: str = "append"  # 'append', 'replace', 'separate_file'
    mark_ai_generated: bool = True
    require_human_review: bool = True
    
    # Component grouping settings
    group_by_model: bool = True
    group_by_naming_pattern: bool = True
    use_feature_map: bool = True  # Use feature_user_story_map.toml if available
    
    @classmethod
    def with_env_defaults(cls) -> "UserStoryEnricherConfig":
        """Create config with defaults from environment variables."""
        return cls(
            ai_provider=os.getenv("AI_PROVIDER", "openai"),
            model=os.getenv("AI_MODEL"),  # None if not set
        )


@dataclass
class MetricLimits:
    """Maximum values for complexity metrics (for normalization)."""
    
    loc_max: int = 2000
    functions_max: int = 50
    cyclomatic_complexity_max: int = 15
    branches_max: int = 100
    sql_queries_max: int = 30
    external_calls_max: int = 10
    ui_elements_max: int = 50


@dataclass
class MetricWeights:
    """Weights for complexity metrics in score calculation."""
    
    loc: float = 1.5
    functions_count: float = 1.0
    avg_cyclomatic_complexity: float = 2.0
    branches_count: float = 0.8
    sql_queries_count: float = 1.2
    external_calls_count: float = 1.5
    ui_elements_count: float = 0.6
    dynamic_code_flags: float = 2.5
    file_types_mix: float = 0.5
    test_coverage_flag: float = -0.8  # Negative - reduces complexity


@dataclass
class ScoreThresholds:
    """Score thresholds for complexity labels."""
    
    simple_max: float = 1.0
    medium_max: float = 2.5
    complex_max: float = 4.5
    # Anything above complex_max is very_complex


@dataclass
class BandMultipliers:
    """Multipliers for time estimation by complexity band."""
    
    simple: float = 0.85
    medium: float = 1.0
    complex: float = 1.4
    very_complex: float = 1.9


@dataclass
class UserStoryModifiers:
    """Modifiers based on user story content."""
    
    additional_story_percent: float = 0.10  # +10% per additional story
    additional_criteria_percent: float = 0.05  # +5% per criterion beyond 3
    criteria_baseline: int = 3


@dataclass
class EffortEstimatorConfig:
    """Configuration for the Effort Estimator."""
    
    enabled: bool = True
    feature_flag: str = "complexity_v2"
    
    limits: MetricLimits = field(default_factory=MetricLimits)
    weights: MetricWeights = field(default_factory=MetricWeights)
    thresholds: ScoreThresholds = field(default_factory=ScoreThresholds)
    multipliers: BandMultipliers = field(default_factory=BandMultipliers)
    user_story_modifiers: UserStoryModifiers = field(default_factory=UserStoryModifiers)
    
    # Output settings
    include_metric_breakdown: bool = True
    include_top_contributors: bool = True
    fallback_to_existing: bool = True  # Use existing complexity if source unavailable


@dataclass
class EnricherConfig:
    """Combined configuration for all enrichers."""
    
    user_story_enricher: UserStoryEnricherConfig = field(
        default_factory=UserStoryEnricherConfig
    )
    effort_estimator: EffortEstimatorConfig = field(
        default_factory=EffortEstimatorConfig
    )
    
    @classmethod
    def default(cls) -> "EnricherConfig":
        """Create a default configuration with environment variable defaults."""
        return cls(
            user_story_enricher=UserStoryEnricherConfig.with_env_defaults(),
            effort_estimator=EffortEstimatorConfig(),
        )
    
    @classmethod
    def from_file(cls, path: Path) -> "EnricherConfig":
        """Load configuration from a TOML file.
        
        Args:
            path: Path to TOML configuration file
            
        Returns:
            EnricherConfig instance
        """
        with open(path, "rb") as f:
            data = tomllib.load(f)
        
        return cls.from_dict(data)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnricherConfig":
        """Create configuration from a dictionary.
        
        Args:
            data: Configuration dictionary
            
        Returns:
            EnricherConfig instance
        """
        config = cls()
        
        # Load user story enricher config
        if "user_story_enricher" in data:
            use_data = data["user_story_enricher"]
            config.user_story_enricher = UserStoryEnricherConfig(
                enabled=use_data.get("enabled", True),
                ai_provider=use_data.get("ai_provider", "openai"),
                model=use_data.get("model"),
                temperature=use_data.get("temperature", 0.7),
                max_stories_per_feature=use_data.get("max_stories_per_feature", 5),
                output_mode=use_data.get("output_mode", "append"),
                mark_ai_generated=use_data.get("mark_ai_generated", True),
                require_human_review=use_data.get("require_human_review", True),
                group_by_model=use_data.get("group_by_model", True),
                group_by_naming_pattern=use_data.get("group_by_naming_pattern", True),
                use_feature_map=use_data.get("use_feature_map", True),
            )
        
        # Load effort estimator config
        if "effort_estimator" in data:
            ee_data = data["effort_estimator"]
            
            # Load nested configurations
            limits = MetricLimits()
            if "metrics" in ee_data:
                m = ee_data["metrics"]
                limits = MetricLimits(
                    loc_max=m.get("loc_max", 2000),
                    functions_max=m.get("functions_max", 50),
                    cyclomatic_complexity_max=m.get("cc_max", 15),
                    branches_max=m.get("branches_max", 100),
                    sql_queries_max=m.get("sql_queries_max", 30),
                    external_calls_max=m.get("external_calls_max", 10),
                    ui_elements_max=m.get("ui_elements_max", 50),
                )
            
            weights = MetricWeights()
            if "weights" in ee_data:
                w = ee_data["weights"]
                weights = MetricWeights(
                    loc=w.get("loc", 1.5),
                    functions_count=w.get("functions_count", 1.0),
                    avg_cyclomatic_complexity=w.get("avg_cyclomatic_complexity", 2.0),
                    branches_count=w.get("branches_count", 0.8),
                    sql_queries_count=w.get("sql_queries_count", 1.2),
                    external_calls_count=w.get("external_calls_count", 1.5),
                    ui_elements_count=w.get("ui_elements_count", 0.6),
                    dynamic_code_flags=w.get("dynamic_code_flags", 2.5),
                    file_types_mix=w.get("file_types_mix", 0.5),
                    test_coverage_flag=w.get("test_coverage_flag", -0.8),
                )
            
            thresholds = ScoreThresholds()
            if "thresholds" in ee_data:
                t = ee_data["thresholds"]
                thresholds = ScoreThresholds(
                    simple_max=t.get("simple_max", 1.0),
                    medium_max=t.get("medium_max", 2.5),
                    complex_max=t.get("complex_max", 4.5),
                )
            
            multipliers = BandMultipliers()
            if "multipliers" in ee_data:
                mul = ee_data["multipliers"]
                multipliers = BandMultipliers(
                    simple=mul.get("simple", 0.85),
                    medium=mul.get("medium", 1.0),
                    complex=mul.get("complex", 1.4),
                    very_complex=mul.get("very_complex", 1.9),
                )
            
            config.effort_estimator = EffortEstimatorConfig(
                enabled=ee_data.get("enabled", True),
                feature_flag=ee_data.get("feature_flag", "complexity_v2"),
                limits=limits,
                weights=weights,
                thresholds=thresholds,
                multipliers=multipliers,
                include_metric_breakdown=ee_data.get("include_metric_breakdown", True),
                include_top_contributors=ee_data.get("include_top_contributors", True),
                fallback_to_existing=ee_data.get("fallback_to_existing", True),
            )
        
        return config
    
    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary for serialization."""
        return {
            "user_story_enricher": {
                "enabled": self.user_story_enricher.enabled,
                "ai_provider": self.user_story_enricher.ai_provider,
                "model": self.user_story_enricher.model,
                "temperature": self.user_story_enricher.temperature,
                "max_stories_per_feature": self.user_story_enricher.max_stories_per_feature,
                "output_mode": self.user_story_enricher.output_mode,
                "mark_ai_generated": self.user_story_enricher.mark_ai_generated,
                "require_human_review": self.user_story_enricher.require_human_review,
            },
            "effort_estimator": {
                "enabled": self.effort_estimator.enabled,
                "feature_flag": self.effort_estimator.feature_flag,
                "metrics": {
                    "loc_max": self.effort_estimator.limits.loc_max,
                    "functions_max": self.effort_estimator.limits.functions_max,
                    "cc_max": self.effort_estimator.limits.cyclomatic_complexity_max,
                    "branches_max": self.effort_estimator.limits.branches_max,
                },
                "weights": {
                    "loc": self.effort_estimator.weights.loc,
                    "functions_count": self.effort_estimator.weights.functions_count,
                    "avg_cyclomatic_complexity": self.effort_estimator.weights.avg_cyclomatic_complexity,
                    "branches_count": self.effort_estimator.weights.branches_count,
                    "sql_queries_count": self.effort_estimator.weights.sql_queries_count,
                    "external_calls_count": self.effort_estimator.weights.external_calls_count,
                    "ui_elements_count": self.effort_estimator.weights.ui_elements_count,
                    "dynamic_code_flags": self.effort_estimator.weights.dynamic_code_flags,
                    "file_types_mix": self.effort_estimator.weights.file_types_mix,
                    "test_coverage_flag": self.effort_estimator.weights.test_coverage_flag,
                },
                "thresholds": {
                    "simple_max": self.effort_estimator.thresholds.simple_max,
                    "medium_max": self.effort_estimator.thresholds.medium_max,
                    "complex_max": self.effort_estimator.thresholds.complex_max,
                },
                "multipliers": {
                    "simple": self.effort_estimator.multipliers.simple,
                    "medium": self.effort_estimator.multipliers.medium,
                    "complex": self.effort_estimator.multipliers.complex,
                    "very_complex": self.effort_estimator.multipliers.very_complex,
                },
            },
        }
