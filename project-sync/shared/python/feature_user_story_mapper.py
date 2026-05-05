"""
Feature-User Story Mapper - Load and apply feature-user story mappings from TOML file.

Part of V1.1.7 - Feature-User Story Mapping Configuration.

Loads the feature_user_story_map.toml file and provides user story definitions
for TODO.md generation. Supports the simple inline array format with type.name
component references.
"""

import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional

from feature_detector import Component, ComponentType, Feature, UserStory
from file_manager import FileManager


class FeatureUserStoryMapper:
    """Load and apply feature-user story mappings from TOML configuration.

    The mapper reads feature_user_story_map.toml and creates UserStory objects
    based on the user-defined groupings. If a feature is not in the map, it
    falls back to default grouping by component type.
    """

    def __init__(self, map_file: Path):
        """Initialize FeatureUserStoryMapper.

        Args:
            map_file: Path to feature_user_story_map.toml file
        """
        self.map_file = Path(map_file)
        self.file_manager = FileManager(self.map_file.parent)
        self._map_data: Optional[Dict] = None

    def load_map(self) -> Dict[str, Dict]:
        """Load feature→user stories mapping from TOML file.

        Returns:
            Dict mapping feature names to feature definitions

        Raises:
            ValueError: If map file doesn't exist
            tomllib.TOMLDecodeError: If map file is invalid TOML
        """
        if not self.file_manager.exists(self.map_file):
            raise ValueError(
                f"Feature-user story map not found: {self.map_file}\n"
                f"Run './.odoo-sync/cli.py generate-feature-user-story-map --execute' first."
            )

        # Return cached if already loaded
        if self._map_data is not None:
            return self._map_data.get("features", {})

        # Load TOML file
        self._map_data = self.file_manager.read_toml(self.map_file)

        return self._map_data.get("features", {})

    def validate_map(self) -> List[str]:
        """Validate map has no issues.

        Checks for:
        - Features with empty user_stories
        - Deprecated features still in map
        - Invalid component references
        - Features containing components directly (not allowed)

        Returns:
            List of error/warning messages (empty list if valid)
        """
        features = self.load_map()
        warnings = []

        for feature_name, feature_def in features.items():
            # Check for deprecated marker
            if feature_def.get("_deprecated"):
                warnings.append(
                    f"Feature '{feature_name}' is marked as DEPRECATED\n"
                    f"  → Consider removing it from feature_user_story_map.toml"
                )
                continue

            # Check for direct components in feature (not allowed)
            if "components" in feature_def:
                warnings.append(
                    f"Feature '{feature_name}' contains direct components\n"
                    f"  → Components must be under user stories, not features. Please restructure the TOML."
                )

            # Check for empty user_stories
            user_stories = feature_def.get("user_stories", {})
            # Handle both dict format (new) and list format (legacy)
            if isinstance(user_stories, dict):
                if not user_stories:
                    warnings.append(
                        f"Feature '{feature_name}' has no user stories defined\n"
                        f"  → Add user stories or remove the feature from the map"
                    )
                    continue

                # Check each user story has components
                for story_name, story_data in user_stories.items():
                    if not story_data.get("components"):
                        warnings.append(
                            f"Feature '{feature_name}' user story '{story_name}' has no components\n"
                            f"  → Add components to the user story"
                        )
            else:
                # Legacy list format
                if not user_stories:
                    warnings.append(
                        f"Feature '{feature_name}' has no user stories defined\n"
                        f"  → Add user stories or remove the feature from the map"
                    )
                    continue

                # Check each user story has components
                for i, story in enumerate(user_stories):
                    if not story.get("components"):
                        warnings.append(
                            f"Feature '{feature_name}' user story {i+1} has no components\n"
                            f"  → Add components to the user story"
                        )

        return warnings

    def get_user_stories_for_feature(
        self, feature: Feature, estimator: Any  # TimeEstimator instance
    ) -> List[UserStory]:
        """Get user stories for a feature from the map.

        If the feature is in the map, creates UserStory objects based on
        the map definition. Otherwise, falls back to default grouping.

        Args:
            feature: Feature object with components
            estimator: TimeEstimator instance for time calculations

        Returns:
            List of UserStory objects
        """
        features_map = self.load_map()

        # Get feature definition from map
        feature_def = features_map.get(feature.name)

        if not feature_def or feature_def.get("_deprecated"):
            # Feature not in map or deprecated - use default strategy
            return estimator._create_default_user_stories(feature)

        user_stories_data = feature_def.get("user_stories", {})
        # Handle both dict format (new) and list format (legacy)
        if isinstance(user_stories_data, dict):
            if not user_stories_data:
                return estimator._create_default_user_stories(feature)
        else:
            if not user_stories_data:
                return estimator._create_default_user_stories(feature)

        return self._create_user_stories_from_map(
            feature, user_stories_data, estimator
        )

    def _create_user_stories_from_map(
        self, feature: Feature, user_stories_data, estimator: Any
    ) -> List[UserStory]:
        """Create UserStory objects from map definition.

        Args:
            feature: Feature object with components
            user_stories_data: Dict or list of user story definitions from map
            estimator: TimeEstimator for time calculations

        Returns:
            List of UserStory objects
        """
        user_stories = []
        matched_component_ids = set()

        # Build a lookup for components by reference
        component_lookup = self._build_component_lookup(feature.components)

        # Handle both dict format (new) and list format (legacy)
        if isinstance(user_stories_data, dict):
            story_items = [(name, data) for name, data in user_stories_data.items()]
        else:
            # Legacy: list format where description is the identifier
            story_items = [(data.get("description", f"Story {i+1}"), data) for i, data in enumerate(user_stories_data)]

        for story_name, story_data in story_items:
            description = story_data.get("description", story_name)
            component_refs = story_data.get("components", [])

            # Find matching components
            story_components = []
            for ref in component_refs:
                # Handle both string format and dict format with 'ref' key
                if isinstance(ref, dict):
                    ref = ref.get("ref", "")
                if not ref:
                    continue
                    
                matched = self._find_component_by_reference(
                    ref, feature.components, component_lookup
                )
                if matched and matched.id not in matched_component_ids:
                    story_components.append(matched)
                    matched_component_ids.add(matched.id)

            # Create user story if it has components
            if story_components:
                total_hours = sum(
                    estimator.estimate_component(c).total
                    for c in story_components
                )

                user_stories.append(
                    UserStory(
                        title=description,
                        description=f"Implement {len(story_components)} component(s)",
                        components=story_components,
                        estimated_hours=round(total_hours, 1),
                    )
                )

        # Create fallback user story for unmatched components
        unmatched = [
            c for c in feature.components if c.id not in matched_component_ids
        ]

        if unmatched:
            total_hours = sum(
                estimator.estimate_component(c).total for c in unmatched
            )

            user_stories.append(
                UserStory(
                    title="Other Components",
                    description=f"Implement {len(unmatched)} additional component(s)",
                    components=unmatched,
                    estimated_hours=round(total_hours, 1),
                )
            )

        return user_stories

    def _build_component_lookup(
        self, components: List[Component]
    ) -> Dict[str, Component]:
        """Build lookup dictionary for components by various reference formats.

        Supports model-qualified format for ALL component types:
        - "type.model_name.component_name" (e.g., "field.sale_order.x_credit_limit")
        - "view.product_product.Product List Customization"
        - "server_action.sale_order.[rwx] Check Credit"
        - "automation.account_move.Auto-post"
        - "report.sale_order.Sales Summary"

        Also supports legacy format for backward compatibility:
        - "type.name" (e.g., "field.x_credit_limit")

        Args:
            components: List of Component objects

        Returns:
            Dict mapping reference strings to Component objects
        """
        lookup = {}

        for comp in components:
            type_prefix = comp.component_type.value

            # Add model-qualified format for ALL component types where model is available
            if comp.model:
                model_part = comp.model.replace(".", "_")
                qualified_name = f"{type_prefix}.{model_part}.{comp.name}"
                lookup[qualified_name] = comp
                lookup[qualified_name.lower()] = comp

            # Add legacy type.name format (backward compatibility)
            lookup[f"{type_prefix}.{comp.name}"] = comp
            if comp.display_name:
                lookup[f"{type_prefix}.{comp.display_name}"] = comp

            # Add lowercase variants for case-insensitive matching
            lookup[f"{type_prefix}.{comp.name}".lower()] = comp
            if comp.display_name:
                lookup[f"{type_prefix}.{comp.display_name}".lower()] = comp

        return lookup

    def _find_component_by_reference(
        self,
        ref: str,
        components: List[Component],
        lookup: Dict[str, Component],
    ) -> Optional[Component]:
        """Find a component by its type.name or type.model.name reference.

        Supports formats for ALL component types:
        - "field.sale_order.x_credit_limit" (model-qualified)
        - "field.x_credit_limit" (legacy format)
        - "view.product_product.Product List" (model-qualified)
        - "view.Partner Form" (legacy format)
        - "server_action.sale_order.[rwx] Check Credit" (model-qualified)
        - "automation.account_move.Auto-post" (model-qualified)
        - "report.sale_order.Sales Summary" (model-qualified)

        Args:
            ref: Component reference string (type.name or type.model.name format)
            components: List of all components
            lookup: Pre-built lookup dictionary

        Returns:
            Matching Component or None
        """
        # Direct lookup
        if ref in lookup:
            return lookup[ref]

        # Case-insensitive lookup
        if ref.lower() in lookup:
            return lookup[ref.lower()]

        # Parse reference and search
        if "." not in ref:
            return None

        parts = ref.split(".")
        if len(parts) < 2:
            return None

        type_part = parts[0]

        # Map type aliases
        type_map = {
            "field": ComponentType.FIELD,
            "view": ComponentType.VIEW,
            "server_action": ComponentType.SERVER_ACTION,
            "automation": ComponentType.AUTOMATION,
            "report": ComponentType.REPORT,
            "cron": ComponentType.AUTOMATION,  # Alias
            "action": ComponentType.SERVER_ACTION,  # Alias
        }

        target_type = type_map.get(type_part.lower())
        if not target_type:
            return None

        # Try to parse as type.model.name format (3+ parts)
        if len(parts) >= 3:
            # Could be model-qualified: "type.model_name.component_name[.extra.parts]"
            model_part = parts[1]
            name_part = ".".join(parts[2:])
            normalized_model = model_part.replace("_", ".")

            for comp in components:
                if comp.component_type != target_type:
                    continue
                # Check model and name match (case-insensitive)
                if (
                    comp.model
                    and comp.model.lower() == normalized_model.lower()
                ):
                    if comp.name.lower() == name_part.lower():
                        return comp
                    # Also check display_name
                    if (
                        comp.display_name
                        and comp.display_name.lower() == name_part.lower()
                    ):
                        return comp

        # Fall back to type.name search (legacy format: "type.component_name[.extra.parts]")
        name_part = ".".join(parts[1:])

        for comp in components:
            if comp.component_type != target_type:
                continue

            # Check name match (case-insensitive)
            if comp.name.lower() == name_part.lower():
                return comp
            if (
                comp.display_name
                and comp.display_name.lower() == name_part.lower()
            ):
                return comp

        return None

    def get_all_features(self) -> List[str]:
        """Get list of all feature names in the map.

        Returns:
            List of feature names (excludes deprecated)
        """
        features = self.load_map()
        return [
            name
            for name, data in features.items()
            if not data.get("_deprecated")
        ]

    def get_statistics(self) -> Dict:
        """Get statistics from map file.

        Returns:
            Dict with statistics (or empty dict if not loaded)
        """
        if self._map_data is None:
            self.load_map()

        return self._map_data.get("statistics", {}) if self._map_data else {}
