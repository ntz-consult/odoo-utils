"""Feature detection for Odoo Studio customizations.

Groups extracted components into logical features based on:
1. Pattern matching against feature-mapping.json
2. Fallback grouping by Odoo model
"""

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path
from typing import Any


class ComponentType(Enum):
    """Types of Odoo Studio components."""

    FIELD = "field"
    VIEW = "view"
    SERVER_ACTION = "server_action"
    AUTOMATION = "automation"
    REPORT = "report"


@dataclass
class Component:
    """A single Odoo Studio component."""

    id: int
    name: str
    display_name: str
    component_type: ComponentType
    model: str
    complexity: str  # simple, medium, complex, very_complex
    raw_data: dict[str, Any]
    is_studio: bool = False

    @property
    def type_label(self) -> str:
        """Human-readable component type."""
        labels = {
            ComponentType.FIELD: "Field",
            ComponentType.VIEW: "View",
            ComponentType.SERVER_ACTION: "Server Action",
            ComponentType.AUTOMATION: "Automation",
            ComponentType.REPORT: "Report",
        }
        return labels.get(self.component_type, self.component_type.value)


@dataclass
class UserStory:
    """A development task within a feature."""

    title: str
    description: str
    components: list[Component]
    estimated_hours: float
    logged_hours: float = 0.0
    status: str = "pending"  # pending, in_progress, completed
    odoo_task_id: int | None = None

    @property
    def remaining_hours(self) -> float:
        """Hours remaining for this story."""
        return max(0, self.estimated_hours - self.logged_hours)


@dataclass
class Feature:
    """A logical grouping of related components."""

    name: str
    description: str
    user_stories: list[UserStory] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)
    affected_models: set[str] = field(default_factory=set)

    @property
    def total_estimated_hours(self) -> float:
        """Total estimated hours across all user stories."""
        return sum(s.estimated_hours for s in self.user_stories)

    @property
    def total_logged_hours(self) -> float:
        """Total logged hours across all user stories."""
        return sum(s.logged_hours for s in self.user_stories)

    @property
    def completion_count(self) -> tuple[int, int]:
        """(completed, total) user stories."""
        completed = sum(
            1 for s in self.user_stories if s.status == "completed"
        )
        return (completed, len(self.user_stories))


@dataclass
class FeatureMapping:
    """Configuration for mapping components to features."""

    features: dict[str, dict[str, Any]]  # {name: {description, patterns}}
    unmapped_handling: str = "group_by_model"

    @classmethod
    def from_file(cls, path: Path) -> "FeatureMapping":
        """Load feature mapping from JSON file.

        Args:
            path: Path to feature-mapping.json

        Returns:
            FeatureMapping instance
        """
        with open(path) as f:
            data = json.load(f)

        return cls(
            features=data.get("features", {}),
            unmapped_handling=data.get("unmapped_handling", "group_by_model"),
        )

    @classmethod
    def default(cls) -> "FeatureMapping":
        """Create empty default mapping (all components grouped by model)."""
        return cls(features={}, unmapped_handling="group_by_model")


class PatternMatcher:
    """Match component names against feature patterns.

    Pattern types:
    - x_prefix_* : wildcard at end (fnmatch)
    - *keyword*  : wildcard both sides (fnmatch)
    - [tag]*     : tag prefix regex
    """

    def __init__(self, patterns: list[str]):
        """Initialize with list of patterns.

        Args:
            patterns: List of pattern strings
        """
        self.patterns = patterns
        self._compiled = self._compile_patterns(patterns)

    def _compile_patterns(self, patterns: list[str]) -> list[tuple[str, Any]]:
        """Compile patterns into matchers.

        Args:
            patterns: List of pattern strings

        Returns:
            List of (type, matcher) tuples
        """
        compiled = []
        for pattern in patterns:
            if pattern.startswith("[") and "]" in pattern:
                # Tag pattern: [tag]* -> regex
                tag_end = pattern.index("]")
                tag = pattern[1:tag_end]
                regex = re.compile(rf"^\[{re.escape(tag)}\]", re.IGNORECASE)
                compiled.append(("tag", regex))
            else:
                compiled.append(("fnmatch", pattern))
        return compiled

    def matches(self, component_name: str) -> bool:
        """Check if component name matches any pattern.

        Args:
            component_name: Name to check

        Returns:
            True if matches any pattern
        """
        for pattern_type, pattern in self._compiled:
            if pattern_type == "tag":
                if pattern.search(component_name):
                    return True
            elif fnmatch(component_name.lower(), pattern.lower()):
                return True
        return False


# Common Odoo model display names
MODEL_DISPLAY_NAMES = {
    "sale.order": "Sales Order",
    "sale.order.line": "Sales Order Line",
    "purchase.order": "Purchase Order",
    "purchase.order.line": "Purchase Order Line",
    "res.partner": "Contact",
    "res.users": "User",
    "res.company": "Company",
    "product.product": "Product",
    "product.template": "Product Template",
    "stock.picking": "Inventory Transfer",
    "stock.move": "Stock Move",
    "stock.quant": "Stock Quant",
    "account.move": "Journal Entry",
    "account.move.line": "Journal Item",
    "account.payment": "Payment",
    "mrp.production": "Manufacturing Order",
    "mrp.bom": "Bill of Materials",
    "project.project": "Project",
    "project.task": "Project Task",
    "hr.employee": "Employee",
    "crm.lead": "Lead/Opportunity",
    "helpdesk.ticket": "Helpdesk Ticket",
}


def load_extraction_results(extraction_dir: Path) -> list[Component]:
    """Load all extraction JSON files and convert to Components.

    Args:
        extraction_dir: Directory containing extraction output files

    Returns:
        List of Component objects
    """
    components: list[Component] = []

    file_parsers = {
        "custom_fields_output.json": (
            _parse_field_component,
            ComponentType.FIELD,
        ),
        "views_metadata.json": (_parse_view_component, ComponentType.VIEW),
        "server_actions_output.json": (
            _parse_server_action_component,
            ComponentType.SERVER_ACTION,
        ),
        "auto_actions_output.json": (
            _parse_automation_component,
            ComponentType.AUTOMATION,
        ),
        "reports_output.json": (_parse_report_component, ComponentType.REPORT),
    }

    for filename, (parser, comp_type) in file_parsers.items():
        filepath = extraction_dir / filename
        if filepath.exists():
            with open(filepath) as f:
                data = json.load(f)
            for record in data.get("records", []):
                components.append(parser(record, comp_type))

    return components


def load_source_components(source_dir: Path) -> list[Component]:
    """Load components from Odoo source code directory.

    Args:
        source_dir: Directory containing Odoo module source files

    Returns:
        List of Component objects
    """
    try:
        from source_extractors import load_source_components as _load_source
    except ImportError:
        raise ImportError(
            "source_extractors module not found. Install or implement source code parsing."
        )

    source_components = _load_source(source_dir)

    # Convert SourceComponent to Component
    components = []
    for src_comp in source_components:
        # Include file_path in raw_data for filename-based matching
        raw_data_with_path = src_comp.raw_data.copy() if isinstance(src_comp.raw_data, dict) else {}
        raw_data_with_path["file_path"] = src_comp.file_path
        
        component = Component(
            id=src_comp.id,
            name=src_comp.name,
            display_name=src_comp.display_name,
            component_type=ComponentType(src_comp.component_type),
            model=src_comp.model,
            complexity=src_comp.complexity,
            raw_data=raw_data_with_path,
            is_studio=src_comp.is_studio,
        )
        components.append(component)

    return components


def _parse_field_component(
    record: dict[str, Any], comp_type: ComponentType
) -> Component:
    """Parse a field record into a Component."""
    return Component(
        id=record.get("id", 0),
        name=record.get("name", ""),
        display_name=record.get("field_description", record.get("name", "")),
        component_type=comp_type,
        model=record.get("model", ""),
        complexity=_infer_field_complexity(record),
        raw_data=record,
        is_studio=record.get("is_studio", False),
    )


def _parse_view_component(
    record: dict[str, Any], comp_type: ComponentType
) -> Component:
    """Parse a view record into a Component."""
    return Component(
        id=record.get("id", 0),
        name=record.get("name", ""),
        display_name=record.get("display_name", record.get("name", "")),
        component_type=comp_type,
        model=record.get("model", ""),
        complexity=_infer_view_complexity(record),
        raw_data=record,
        is_studio=record.get("is_studio", False),
    )


def _parse_server_action_component(
    record: dict[str, Any], comp_type: ComponentType
) -> Component:
    """Parse a server action record into a Component."""
    return Component(
        id=record.get("id", 0),
        name=record.get("name", ""),
        display_name=record.get("display_name", record.get("name", "")),
        component_type=comp_type,
        model=record.get(
            "model_name",
            (
                record.get("model_id", ["", ""])[1]
                if isinstance(record.get("model_id"), (list, tuple))
                else ""
            ),
        ),
        complexity=_infer_code_complexity(record.get("code", "")),
        raw_data=record,
        is_studio=record.get("is_studio", False),
    )


def _parse_automation_component(
    record: dict[str, Any], comp_type: ComponentType
) -> Component:
    """Parse an automation record into a Component."""
    model = record.get("model_name", "")
    if not model and isinstance(record.get("model_id"), (list, tuple)):
        model = record["model_id"][1] if len(record["model_id"]) >= 2 else ""

    return Component(
        id=record.get("id", 0),
        name=record.get("name", ""),
        display_name=record.get("display_name", record.get("name", "")),
        component_type=comp_type,
        model=model,
        complexity=_infer_automation_complexity(record),
        raw_data=record,
        is_studio=record.get("is_studio", False),
    )


def _parse_report_component(
    record: dict[str, Any], comp_type: ComponentType
) -> Component:
    """Parse a report record into a Component."""
    return Component(
        id=record.get("id", 0),
        name=record.get("name", ""),
        display_name=record.get("display_name", record.get("name", "")),
        component_type=comp_type,
        model=record.get("model", ""),
        complexity=_infer_report_complexity(record),
        raw_data=record,
        is_studio=record.get("is_studio", False),
    )


def _infer_field_complexity(record: dict[str, Any]) -> str:
    """Infer field complexity from record data."""
    compute = record.get("compute", "")
    ttype = record.get("ttype", "")

    if compute:
        lines = len(compute.split("\n"))
        if lines > 10:
            return "complex"
        return "medium"

    # Relational fields are more complex
    if ttype in ("many2one", "one2many", "many2many"):
        return "medium"

    return "simple"


def _infer_view_complexity(record: dict[str, Any]) -> str:
    """Infer view complexity from record data."""
    arch = record.get("arch", "") or ""
    lines = len(arch.split("\n"))

    if lines > 150:
        return "very_complex"
    elif lines > 50:
        return "complex"
    elif lines > 20:
        return "medium"
    return "simple"


def _infer_code_complexity(code: str) -> str:
    """Infer complexity from Python code length."""
    if not code:
        return "simple"

    lines = len(code.split("\n"))
    if lines > 150:
        return "very_complex"
    elif lines > 50:
        return "complex"
    elif lines > 20:
        return "medium"
    return "simple"


def _infer_automation_complexity(record: dict[str, Any]) -> str:
    """Infer automation complexity from record data."""
    # Check for code-based actions
    code = record.get("code", "")
    if code:
        return _infer_code_complexity(code)

    # Check trigger complexity
    trigger = record.get("trigger", "")
    filter_domain = record.get("filter_domain", "")

    if trigger in ("on_time", "on_time_created", "on_time_updated"):
        return "medium"

    if filter_domain and len(filter_domain) > 50:
        return "medium"

    return "simple"


def _infer_report_complexity(record: dict[str, Any]) -> str:
    """Infer report complexity from record data."""
    # Reports are generally complex
    report_type = record.get("report_type", "")
    if report_type == "qweb-pdf":
        return "complex"
    return "medium"


class FeatureDetector:
    """Detect and group components into features."""

    def __init__(self, feature_mapping: FeatureMapping):
        """Initialize with feature mapping configuration.

        Args:
            feature_mapping: FeatureMapping instance
        """
        self.feature_mapping = feature_mapping
        self._matchers: dict[str, PatternMatcher] = {}
        self._build_matchers()

    def _build_matchers(self) -> None:
        """Build pattern matchers from feature mapping."""
        for name, config in self.feature_mapping.features.items():
            patterns = config.get("patterns", [])
            if patterns:
                self._matchers[name] = PatternMatcher(patterns)

    def detect_features(self, components: list[Component]) -> list[Feature]:
        """Detect features from list of components.

        Args:
            components: List of Component objects

        Returns:
            List of Feature objects
        """
        features: dict[str, Feature] = {}
        unmapped: list[Component] = []

        for comp in components:
            matched_feature = self._match_component(comp)
            if matched_feature:
                if matched_feature not in features:
                    config = self.feature_mapping.features[matched_feature]
                    features[matched_feature] = Feature(
                        name=matched_feature,
                        description=config.get("description", ""),
                    )
                features[matched_feature].components.append(comp)
                features[matched_feature].affected_models.add(comp.model)
            else:
                unmapped.append(comp)

        # Fallback: group unmapped by model
        if self.feature_mapping.unmapped_handling == "group_by_model":
            by_model = self._group_by_model(unmapped)
            for model, comps in by_model.items():
                feature_name = self._model_to_feature_name(model)
                if feature_name not in features:
                    features[feature_name] = Feature(
                        name=feature_name,
                        description=f"Customizations for {model}",
                        components=comps,
                        affected_models={model},
                    )
                else:
                    features[feature_name].components.extend(comps)
                    features[feature_name].affected_models.add(model)

        return list(features.values())

    def _match_component(self, component: Component) -> str | None:
        """Try to match a component to a feature.

        Args:
            component: Component to match

        Returns:
            Feature name if matched, None otherwise
        """
        for feature_name, matcher in self._matchers.items():
            if matcher.matches(component.name):
                return feature_name
        return None

    def _group_by_model(
        self, components: list[Component]
    ) -> dict[str, list[Component]]:
        """Group components by their Odoo model.

        Args:
            components: List of components

        Returns:
            Dict mapping model name to components
        """
        by_model: dict[str, list[Component]] = {}
        for comp in components:
            model = comp.model or "unknown"
            by_model.setdefault(model, []).append(comp)
        return by_model

    def _model_to_feature_name(self, model: str) -> str:
        """Convert model name to feature name.

        Args:
            model: Odoo model technical name

        Returns:
            Human-readable feature name
        """
        display = MODEL_DISPLAY_NAMES.get(model)
        if not display:
            # Convert model.name to Model Name
            display = " ".join(
                w.capitalize() for w in model.replace(".", " ").split()
            )
        return f"{display} Customizations"
