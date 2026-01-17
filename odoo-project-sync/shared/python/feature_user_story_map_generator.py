"""
Feature-User Story Map Generator - Generate and maintain feature_user_story_map.toml.

Part of V1.1.7 - Feature-User Story Mapping Configuration.

PRESERVATION LOGIC:
- Existing user stories and component assignments are NEVER modified
- New components are added to an "Unassigned Components" user story
- Users maintain full control over groupings across regeneration
"""

import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from .feature_detector import Component, ComponentType, Feature
    from .file_manager import FileManager
    from .qweb_resolver import QWebResolver
except ImportError:
    from feature_detector import Component, ComponentType, Feature
    from file_manager import FileManager
    from qweb_resolver import QWebResolver


@dataclass
class MapGenerationResult:
    """Result of feature-user story map generation/update."""

    total_features: int
    total_user_stories: int
    total_components: int
    user_stories_needing_review: int
    new_features: int
    preserved_features: int
    new_components_added: int


class FeatureUserStoryMapGenerator:
    """Generate and maintain feature_user_story_map.toml file.

    This generator creates a TOML configuration file that maps features to
    user stories. Each user story contains a list of components referenced
    by their type.name format (e.g., "field.x_credit_limit").

    PRESERVATION GUARANTEE:
    Once a component is assigned to a user story by the user, that assignment
    is permanent until manually changed. The generator only adds NEW components
    to an "Unassigned Components" user story for user review.
    """

    def __init__(self, project_root: Path, verbose: bool = True):
        """Initialize generator.

        Args:
            project_root: Project root directory
            verbose: Show progress messages
        """
        self.project_root = Path(project_root)
        self.map_file = self.project_root / "studio" / "feature_user_story_map.toml"
        self.verbose = verbose
        
        # Initialize QWeb resolver for report-view associations
        self.file_manager = FileManager(project_root)
        self.qweb_resolver = QWebResolver(
            project_root=project_root,
            file_manager=self.file_manager,
        )

    def generate_or_update_map(
        self, features: List[Feature], extraction_count: int
    ) -> MapGenerationResult:
        """Generate or update map file with incremental logic.

        Args:
            features: List of Feature objects from feature detection
            extraction_count: Total number of extracted components

        Returns:
            MapGenerationResult with statistics
        """
        if self.verbose:
            print(f"\nGenerating feature-user story map...")

        # Load existing map if present
        existing_map = (
            self._load_existing_map() if self.map_file.exists() else None
        )

        if existing_map and self.verbose:
            print(
                f"  Found existing map with {len(existing_map.get('features', {}))} features"
            )

        # Build new map with preservation logic
        new_map_data, stats = self._build_map(
            features, extraction_count, existing_map
        )

        # Backup existing map before overwriting
        if self.map_file.exists():
            from utils import create_timestamped_backup
            backup_path = create_timestamped_backup(self.map_file, keep=5)
            if backup_path and self.verbose:
                print(f"  Backed up existing map to: {backup_path.name}")

        # Write TOML file
        self._write_toml(new_map_data)

        if self.verbose:
            print(f"✓ Map file written: {self.map_file}")
            if stats.new_components_added > 0:
                print(
                    f"  ⚠ {stats.new_components_added} new components added to 'Unassigned Components' - please review and assign"
                )

        return stats

    def preview_map(
        self, features: List[Feature], extraction_count: int
    ) -> MapGenerationResult:
        """Preview map generation without writing file.

        Args:
            features: List of Feature objects
            extraction_count: Total components

        Returns:
            MapGenerationResult with statistics (no file written)
        """
        existing_map = (
            self._load_existing_map() if self.map_file.exists() else None
        )
        _, stats = self._build_map(features, extraction_count, existing_map)
        return stats

    def _load_existing_map(self) -> Optional[Dict]:
        """Load existing TOML map file."""
        try:
            with open(self.map_file, "rb") as f:
                return tomllib.load(f)
        except Exception as e:
            if self.verbose:
                print(f"  Warning: Could not load existing map: {e}")
            return None

    def _build_assigned_components_index(
        self, existing_map: Optional[Dict]
    ) -> Set[str]:
        """Build index of ALL components already assigned anywhere in the map.

        Returns a set of component references that are already assigned
        to ANY user story in ANY feature.

        Args:
            existing_map: Existing TOML map data

        Returns:
            Set[component_ref] - all assigned component references
        """
        assigned_refs = set()

        if not existing_map or "features" not in existing_map:
            return assigned_refs

        for feature_name, feature_def in existing_map["features"].items():
            user_stories = feature_def.get("user_stories", [])
            # user_stories is an array of inline tables
            for story in user_stories:
                components = story.get("components", [])
                for comp in components:
                    if isinstance(comp, dict):
                        assigned_refs.add(comp.get("ref", ""))
                    else:
                        assigned_refs.add(comp)

        return assigned_refs

    def _build_map(
        self,
        features: List[Feature],
        extraction_count: int,
        existing_map: Optional[Dict],
    ) -> tuple[Dict, MapGenerationResult]:
        """Build new map data with PRESERVATION logic.

        PRESERVATION GUARANTEE:
        - ALL existing features from map are preserved exactly as-is
        - Existing user stories are NEVER modified or removed
        - Component assignments are NEVER changed
        - Only truly NEW components (not assigned anywhere) are added
        - User edits are fully preserved across regeneration
        """
        # Track statistics
        total_user_stories = 0
        total_components = 0
        user_stories_needing_review = 0
        new_features = 0
        preserved_features = 0
        new_components_added = 0

        # Build index of ALL assigned components across entire map
        all_assigned_components = self._build_assigned_components_index(
            existing_map
        )

        # Build lookup of all current components by reference
        all_current_components = []
        for feature in features:
            all_current_components.extend(feature.components)

        component_lookup = self._build_component_reference_lookup(
            all_current_components
        )

        # Start with existing map features (PRESERVE USER'S STRUCTURE)
        feature_data = {}

        if existing_map and "features" in existing_map:
            # STEP 1: Preserve ALL existing features EXACTLY as they are
            for feature_name, existing_feature in existing_map[
                "features"
            ].items():
                # Copy existing feature structure EXACTLY
                feature_data[feature_name] = existing_feature.copy()

                existing_user_stories = existing_feature.get(
                    "user_stories", []
                )
                # user_stories is an array
                total_user_stories += len(existing_user_stories)
                feature_component_count = sum(
                    len(story.get("components", []))
                    for story in existing_user_stories
                )

                total_components += feature_component_count
                preserved_features += 1

                if self.verbose:
                    stories_count = len(existing_user_stories)
                    print(
                        f"  ✓ Preserved: {feature_name} ({stories_count} user stories, {feature_component_count} components)"
                    )

            # STEP 2: Find completely unassigned components (not in ANY existing feature)
            completely_unassigned = []
            for comp in all_current_components:
                comp_refs = self._get_all_reference_formats(comp)
                if not any(
                    ref in all_assigned_components for ref in comp_refs
                ):
                    completely_unassigned.append(comp)

            # STEP 3: Mark features as deprecated only if ALL their components are gone
            all_current_refs = set()
            for comp in all_current_components:
                all_current_refs.update(self._get_all_reference_formats(comp))
            
            for fname in list(feature_data.keys()):
                feature_def = feature_data[fname]
                if feature_def.get("_deprecated"):
                    continue  # Already deprecated
                
                # Check if ANY component in this feature still exists
                has_valid_component = False
                user_stories = feature_def.get("user_stories", [])
                # user_stories is an array
                for story in user_stories:
                    for comp_item in story.get("components", []):
                        # Handle both string and dict format
                        comp_ref = comp_item.get("ref") if isinstance(comp_item, dict) else comp_item
                        # Check both the exact ref and lowercase version
                        if comp_ref in all_current_refs or comp_ref.lower() in all_current_refs:
                            has_valid_component = True
                            break
                    if has_valid_component:
                        break
                
                if not has_valid_component:
                    feature_data[fname]["_deprecated"] = True
                    if self.verbose:
                        print(f"  ⚠ Deprecated: {fname} (no valid components found)")

            # Create new "Unassigned Components" feature for completely unassigned items
            if completely_unassigned:
                unassigned_feature_name = "⚠️ Unassigned Components (New)"
                unassigned_story = self._create_unassigned_story(
                    completely_unassigned
                )

                feature_data[unassigned_feature_name] = {
                    "description": "Components that don't match any existing feature - please review and reassign",
                    "detected_by": "unassigned",
                    "sequence": 1,
                    "user_stories": [unassigned_story],
                }

                new_features += 1
                total_user_stories += 1
                total_components += len(completely_unassigned)
                new_components_added += len(completely_unassigned)
                user_stories_needing_review += 1

                if self.verbose:
                    print(
                        f"  + New: {unassigned_feature_name} (1 user story, {len(completely_unassigned)} components)"
                    )

        else:
            # NO EXISTING MAP: Create from scratch using pattern detection
            for feature in features:
                feature_name = feature.name
                components = feature.components
                user_stories = self._create_intelligent_user_stories(feature)

                feature_data[feature_name] = {
                    "description": feature.description
                    or f"Customizations for {feature_name}",
                    "sequence": 1,
                    "task_id": 0,
                    "tags": "Feature",
                    "user_stories": user_stories,
                }
                new_features += 1
                total_user_stories += len(user_stories)
                total_components += len(components)

                if len(components) > 15:
                    user_stories_needing_review += 1

                if self.verbose:
                    print(
                        f"  + New: {feature_name} ({len(user_stories)} user stories, {len(components)} components)"
                    )

        # STEP 4: Move QWeb views to the same story as their associated report
        if self.verbose:
            print("\n  Processing QWeb views...")
        
        qweb_moved = self._move_qweb_views_to_report_stories(
            feature_data, all_current_components
        )
        
        if qweb_moved > 0 and self.verbose:
            print(f"  ✓ Moved {qweb_moved} QWeb views to their report stories")

        # Build complete map structure
        map_data = {
            "metadata": {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "extraction_count": extraction_count,
                "last_extract": datetime.now().isoformat(timespec="seconds"),
                "module_generation_used": True,
                "feature_mapping_used": True,
            },
            "statistics": {
                "total_features": len(
                    [
                        f
                        for f in feature_data.values()
                        if not f.get("_deprecated")
                    ]
                ),
                "total_user_stories": total_user_stories,
                "total_components": total_components,
            },
            "features": feature_data,
            "defaults": {
                "min_user_story_components": 1,
                "max_user_story_components": 10,
            },
        }

        stats = MapGenerationResult(
            total_features=len(feature_data),
            total_user_stories=total_user_stories,
            total_components=total_components,
            user_stories_needing_review=user_stories_needing_review,
            new_features=new_features,
            preserved_features=preserved_features,
            new_components_added=new_components_added,
        )

        return map_data, stats

    def _build_component_reference_lookup(
        self, components: List[Component]
    ) -> Dict[str, Component]:
        """Build lookup from all possible reference formats to Component
        objects.

        Args:
            components: All components from current extraction

        Returns:
            Dict mapping reference strings to Component objects
        """
        lookup = {}
        for comp in components:
            for ref in self._get_all_reference_formats(comp):
                lookup[ref] = comp
        return lookup

    def _move_qweb_views_to_report_stories(
        self,
        feature_data: Dict[str, Any],
        all_current_components: List[Component],
    ) -> int:
        """Move QWeb views (and transitive dependencies) to same story as their report.
        
        This method ensures that QWeb templates are grouped with the reports that
        use them, maintaining logical cohesion in user stories.
        
        Args:
            feature_data: The complete feature data structure
            all_current_components: List of all components from extraction
            
        Returns:
            Number of QWeb views moved
        """
        moved_count = 0
        
        # Build component lookup by name for quick access
        component_by_ref = {}
        for comp in all_current_components:
            for ref in self._get_all_reference_formats(comp):
                component_by_ref[ref] = comp
        
        # Build index of where each component currently lives (feature -> story -> comp_refs)
        component_location = {}  # comp_ref -> (feature_name, story_index)
        
        for feature_name, feature_def in feature_data.items():
            if feature_def.get("_deprecated"):
                continue
                
            user_stories = feature_def.get("user_stories", [])
            for story_idx, story in enumerate(user_stories):
                for comp_item in story.get("components", []):
                    comp_ref = comp_item.get("ref") if isinstance(comp_item, dict) else comp_item
                    if comp_ref:
                        component_location[comp_ref] = (feature_name, story_idx)
        
        # Find all report components and their associated QWeb views
        reports_to_process = []
        
        for feature_name, feature_def in feature_data.items():
            if feature_def.get("_deprecated"):
                continue
                
            user_stories = feature_def.get("user_stories", [])
            for story_idx, story in enumerate(user_stories):
                for comp_item in story.get("components", []):
                    comp_ref = comp_item.get("ref") if isinstance(comp_item, dict) else comp_item
                    
                    # Check if this is a report component
                    if comp_ref and comp_ref.startswith("report."):
                        # Find the actual Component object
                        comp = component_by_ref.get(comp_ref)
                        if comp:
                            reports_to_process.append((feature_name, story_idx, comp))
        
        # For each report, find and move its QWeb views
        for report_feature, report_story_idx, report_comp in reports_to_process:
            report_name = report_comp.raw_data.get("report_name", "")
            if not report_name:
                continue
            
            # Get all QWeb views this report depends on (including transitive deps)
            qweb_view_keys = self.qweb_resolver.get_qweb_views_for_report(report_name)
            
            for qweb_key in qweb_view_keys:
                # Find the component ref for this QWeb view
                qweb_comp_dict = None
                for comp in all_current_components:
                    if comp.component_type == ComponentType.VIEW:
                        view_key = comp.raw_data.get("key", "")
                        view_name = comp.raw_data.get("name", "")
                        
                        if view_key == qweb_key or view_name == qweb_key:
                            # Found the matching component
                            qweb_comp_dict = self._component_to_reference(comp)
                            break
                
                if not qweb_comp_dict:
                    continue
                
                qweb_comp_ref = qweb_comp_dict.get("ref") if isinstance(qweb_comp_dict, dict) else qweb_comp_dict
                
                # Check if this QWeb view is in a different story
                current_location = component_location.get(qweb_comp_ref)
                if not current_location:
                    continue  # Not assigned yet
                
                current_feature, current_story_idx = current_location
                
                # If already in the same story as the report, skip
                if current_feature == report_feature and current_story_idx == report_story_idx:
                    continue
                
                # Move the QWeb view to the report's story
                # 1. Remove from current location
                current_feature_def = feature_data[current_feature]
                current_story = current_feature_def["user_stories"][current_story_idx]
                current_comps = current_story.get("components", [])
                
                # Remove the QWeb view from its current story
                updated_comps = []
                for comp_item in current_comps:
                    item_ref = comp_item.get("ref") if isinstance(comp_item, dict) else comp_item
                    if item_ref != qweb_comp_ref:
                        updated_comps.append(comp_item)
                
                current_story["components"] = updated_comps
                
                # 2. Add to report's story (if not already there)
                report_story = feature_data[report_feature]["user_stories"][report_story_idx]
                report_comps = report_story.get("components", [])
                
                # Check if already in the target story (shouldn't happen, but be safe)
                already_there = False
                for comp_item in report_comps:
                    item_ref = comp_item.get("ref") if isinstance(comp_item, dict) else comp_item
                    if item_ref == qweb_comp_ref:
                        already_there = True
                        break
                
                if not already_there:
                    # Find the actual component to get its reference format
                    qweb_comp = component_by_ref.get(qweb_comp_ref)
                    if qweb_comp:
                        report_comps.append(self._component_to_reference(qweb_comp))
                        moved_count += 1
                        
                        if self.verbose:
                            print(f"    → Moved QWeb view '{qweb_key}' to report story in {report_feature}")
        
        return moved_count

    def _get_all_reference_formats(self, component: Component) -> Set[str]:
        """Get all possible reference formats for a component.

        Supports both:
        - Model-qualified: "type.model_name.component_name"
        - Legacy: "type.component_name"

        Args:
            component: Component to generate references for

        Returns:
            Set of all possible reference strings
        """
        refs = set()
        type_prefix = component.component_type.value
        name = component.name or component.display_name

        # Model-qualified format
        if component.model:
            model_part = component.model.replace(".", "_")
            refs.add(f"{type_prefix}.{model_part}.{name}")
            refs.add(f"{type_prefix}.{model_part}.{name}".lower())

        # Legacy format
        refs.add(f"{type_prefix}.{name}")
        refs.add(f"{type_prefix}.{name}".lower())

        # Also check display_name
        if component.display_name and component.display_name != name:
            display = component.display_name

            if component.model:
                model_part = component.model.replace(".", "_")
                refs.add(f"{type_prefix}.{model_part}.{display}")
                refs.add(f"{type_prefix}.{model_part}.{display}".lower())

            refs.add(f"{type_prefix}.{display}")
            refs.add(f"{type_prefix}.{display}".lower())

        return refs

    def _create_unassigned_story(self, components: List[Component]) -> Dict:
        """Create an "Unassigned Components" user story for new components.

        Args:
            components: List of new/unassigned components

        Returns:
            User story dict with name, description (empty), sequence, and components
        """
        component_refs = [
            self._component_to_reference(comp) for comp in components
        ]

        return {
            "name": "⚠ Unassigned Components (Review & Reassign)",
            "description": "",
            "sequence": 1,
            "components": component_refs,
        }

    def _create_intelligent_user_stories(self, feature: Feature) -> List[Dict]:
        """Create a single user story with the same name as the feature.

        Every feature gets exactly ONE user story with the feature's name,
        containing ALL the feature's components.
        
        Returns inline array format with name field and empty description.

        Args:
            feature: Feature with components

        Returns:
            List containing one user story dict with name, description (empty), sequence, and components
        """
        # Convert all components to references
        component_refs = [
            self._component_to_reference(comp) for comp in feature.components
        ]

        # Create single user story with feature name
        return [{
            "name": feature.name,
            "description": "",
            "sequence": 1,
            "components": component_refs,
        }]

    def _component_to_reference(self, component: Component) -> Dict[str, Any]:
        """Convert component to dict with ref and source_location.

        Qualifies all component types with model name where available to disambiguate
        components with identical names across different models.

        Format examples:
        - "field.sale_order.x_credit_limit" (field with model)
        - "view.product_product.Product List Customization" (view with model)
        - "server_action.sale_order.[rwx] Check Credit" (action with model)
        - "automation.account_move.Auto-post Journals" (automation with model)
        - "report.sale_order.Sales Summary Report" (report with model)

        Args:
            component: Component object

        Returns:
            Dict with 'ref' (reference string) and 'source_location' (file path or empty)
        """
        type_prefix = component.component_type.value
        name = component.name or component.display_name

        # Build reference string
        if component.model:
            # Use model name, replacing dots with underscores for readability
            # e.g., "sale.order" -> "sale_order"
            model_part = component.model.replace(".", "_")
            ref = f"{type_prefix}.{model_part}.{name}"
        else:
            # Fallback to simple format if no model available
            ref = f"{type_prefix}.{name}"
        
        # Extract source_location from component.raw_data if available
        source_location = ""
        if isinstance(component.raw_data, dict) and "file_path" in component.raw_data:
            file_path = component.raw_data["file_path"]
            # Convert to relative path from project root if absolute
            if file_path:
                from pathlib import Path
                path_obj = Path(file_path)
                # Try to make it relative to project root
                try:
                    if path_obj.is_absolute() and self.project_root:
                        source_location = str(path_obj.relative_to(self.project_root))
                    else:
                        source_location = str(file_path)
                except ValueError:
                    # If not relative to project root, use as-is
                    source_location = str(file_path)
        
        return {
            "ref": ref,
            "source_location": source_location,
        }

    def _find_duplicate_components(self, map_data: Dict) -> Dict[str, List[str]]:
        """Find duplicate component refs across all features and user stories.
        
        Args:
            map_data: The complete map data structure
            
        Returns:
            Dict mapping duplicate refs to list of locations (feature/story names)
        """
        ref_locations: Dict[str, List[str]] = {}
        
        for feature_name, feature_def in map_data.get("features", {}).items():
            user_stories = feature_def.get("user_stories", [])
            # user_stories is an array
            for story in user_stories:
                story_name = story.get("name", "Unknown")
                location = f"{feature_name} / {story_name}"
                
                for comp in story.get("components", []):
                    if isinstance(comp, dict):
                        ref = comp.get("ref", "")
                    else:
                        ref = comp
                    
                    if ref:
                        ref_locations.setdefault(ref, []).append(location)
        
        # Return only duplicates (refs that appear more than once)
        return {ref: locs for ref, locs in ref_locations.items() if len(locs) > 1}

    def _calculate_statistics(self, map_data: Dict) -> Dict[str, Any]:
        """Calculate statistics from the map data.
        
        Calculates total_loc and total_time by summing values from all components.
        Preserves time_factor if it exists, or uses default of 0.4.
        
        Args:
            map_data: The complete map data structure
            
        Returns:
            Updated statistics dict with time_factor, total_loc, and total_time
        """
        total_loc = 0
        total_time_seconds = 0
        total_components = 0
        
        # Parse time string to seconds
        def parse_time(time_str: str) -> int:
            """Parse time string like '1:00' or '1:30' to seconds."""
            if not time_str or time_str == "0:00":
                return 0
            parts = time_str.split(":")
            hours = int(parts[0])
            minutes = int(parts[1]) if len(parts) > 1 else 0
            return hours * 3600 + minutes * 60
        
        # Calculate totals from all components
        for feature_name, feature_def in map_data.get("features", {}).items():
            for story in feature_def.get("user_stories", []):
                for component in story.get("components", []):
                    total_components += 1
                    if isinstance(component, dict):
                        loc = component.get("loc", 0)
                        time_estimate = component.get("time_estimate", "0:00")
                        total_loc += loc
                        total_time_seconds += parse_time(time_estimate)
        
        # Convert total time back to hours:minutes format
        total_hours = total_time_seconds // 3600
        total_minutes = (total_time_seconds % 3600) // 60
        total_time_str = f"{total_hours}:{total_minutes:02d}"
        
        # Get existing statistics or create new dict
        statistics = map_data.get("statistics", {})
        
        # Preserve or set default time_factor
        if "time_factor" not in statistics:
            statistics["time_factor"] = 0.4
        
        # Update calculated values
        statistics["total_components"] = total_components
        statistics["total_loc"] = total_loc
        statistics["total_time"] = total_time_str
        
        return statistics

    def _write_toml(self, map_data: Dict) -> None:
        """Write map data to TOML file.

        Uses manual formatting for better readability with inline arrays.
        """
        lines = []
        
        # Detect duplicates first
        duplicates = self._find_duplicate_components(map_data)

        # Header comment
        lines.append("# Feature-User Story Mapping for TODO Generation")
        lines.append("# Generated by odoo-project-sync v1.1.7")
        
        # BIG RED WARNING if duplicates found
        if duplicates:
            lines.append("#")
            lines.append("# " + "=" * 70)
            lines.append("# ⚠️  WARNING: DUPLICATE COMPONENTS DETECTED! ⚠️")
            lines.append("# " + "=" * 70)
            lines.append("# The following component refs appear multiple times:")
            for dup_ref, locations in duplicates.items():
                lines.append(f"#   - {dup_ref}")
                for loc in locations:
                    lines.append(f"#       in: {loc}")
            lines.append("# ")
            lines.append("# Please remove duplicates to ensure correct source_location updates!")
            lines.append("# " + "=" * 70)
        
        lines.append("#")
        lines.append("# STRUCTURE:")
        lines.append(
            "# - Features: Business capabilities that will become Knowledge articles"
        )
        lines.append(
            "# - User Stories: User-facing work items with component lists"
        )
        lines.append(
            "# - Components: String references with model qualification"
        )
        lines.append(
            "#   - Fields: type.model.name format (e.g., field.sale_order.x_credit_limit)"
        )
        lines.append(
            "#   - Views: type.model.name format (e.g., view.product_product.Product List)"
        )
        lines.append(
            "#   - Actions: type.model.name format (e.g., server_action.sale_order.[rwx] Validate)"
        )
        lines.append(
            "#   - Automations: type.model.name format (e.g., automation.account_move.Auto-post)"
        )
        lines.append(
            "#   - Reports: type.model.name format (e.g., report.sale_order.Sales Summary)"
        )
        lines.append("#   - Fallback: type.name format if model not available")
        lines.append("#")
        lines.append("# EDITING:")
        lines.append("# - Review user story descriptions")
        lines.append("# - Add/remove/regroup components as needed")
        lines.append("# - User stories should represent actual work breakdown")
        lines.append("# - Components in 'Unassigned Components' should be reassigned")
        lines.append("#")
        lines.append("# Edit  enrich-status from 'done' back to:")        
        lines.append("# 'refresh-all' (for both AI + effort)")        
        lines.append("# 'refresh-stories' (for AI enrichment only)")        
        lines.append("# 'refresh-effort' (for effort estimation only)")         
        lines.append("")

        # Metadata section
        lines.append("[metadata]")
        for key, value in map_data["metadata"].items():
            if isinstance(value, bool):
                lines.append(f"{key} = {str(value).lower()}")
            elif isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            else:
                lines.append(f"{key} = {value}")
        lines.append("")

        # Calculate and update statistics
        map_data["statistics"] = self._calculate_statistics(map_data)

        # Statistics section
        lines.append("[statistics]")
        for key, value in map_data["statistics"].items():
            if isinstance(value, str):
                lines.append(f'{key} = "{value}"')
            else:
                lines.append(f"{key} = {value}")
        lines.append("")

        # Features sections
        # Sort features: active first, deprecated last
        active_features = []
        deprecated_features = []

        for feature_name, feature_def in sorted(map_data["features"].items()):
            if feature_def.get("_deprecated"):
                deprecated_features.append((feature_name, feature_def))
            else:
                active_features.append((feature_name, feature_def))

        # Write active features
        for feature_name, feature_def in active_features:
            lines.append(f"# --- Feature: {feature_name} ---")
            lines.append(f'[features."{feature_name}"]')

            description = feature_def.get("description", "")
            if description:
                lines.append(
                    f'description = "{self._escape_toml_string(description)}"'
                )

            # Feature sequence (optional)
            if "sequence" in feature_def:
                lines.append(f'sequence = {feature_def.get("sequence")}')
            
            # Enrich status control
            enrich_status = feature_def.get("enrich-status", "refresh-all")
            lines.append(f'enrich-status = "{enrich_status}"')
            
            # Task ID for external tracking
            task_id = feature_def.get("task_id", 0)
            lines.append(f'task_id = {task_id}')
            
            # Tags for categorization
            tags = feature_def.get("tags", "Feature")
            lines.append(f'tags = "{tags}"')

            lines.append("")

            # Write user_stories as inline array of inline tables
            user_stories = feature_def.get("user_stories", [])
            if user_stories:
                lines.append("user_stories = [")
                for story in user_stories:
                    story_name = story.get("name", "")
                    story_desc = story.get("description", "")
                    sequence = story.get("sequence", 1)
                    enrich_status = story.get("enrich-status", "refresh-all")
                    task_id = story.get("task_id", 0)
                    tags = story.get("tags", "Story")
                    components = story.get("components", [])
                    normalized_comps = self._normalize_components(components)
                    
                    # Start user story inline table
                    lines.append(f'    {{ name = "{self._escape_toml_string(story_name)}", description = "{self._escape_toml_string(story_desc)}", sequence = {sequence}, enrich-status = "{enrich_status}", task_id = {task_id}, tags = "{tags}", components = [')
                    
                    # Write components
                    for comp_dict in normalized_comps:
                        comp_ref = comp_dict["ref"]
                        source_loc = comp_dict["source_location"]
                        complexity = comp_dict["complexity"]
                        loc = comp_dict.get("loc", 0)  # Get LOC, default to 0
                        time_estimate = comp_dict["time_estimate"]
                        completion = comp_dict["completion"]
                        
                        if source_loc and isinstance(source_loc, str):
                            lines.append(
                                f'        {{ ref = "{comp_ref}", source_location = "{source_loc}", '
                                f'complexity = "{complexity}", loc = {loc}, time_estimate = "{time_estimate}", '
                                f'completion = "{completion}" }},'
                            )
                        else:
                            lines.append(
                                f'        {{ ref = "{comp_ref}", source_location = "", '
                                f'complexity = "{complexity}", loc = {loc}, time_estimate = "{time_estimate}", '
                                f'completion = "{completion}" }},'
                            )
                    
                    # Close components array and user story
                    lines.append("    ] },")
                
                # Close user_stories array
                lines.append("]")
            
            lines.append("")

        # Write deprecated features (commented or with note)
        if deprecated_features:
            lines.append(
                "# ============================================================================"
            )
            lines.append("# Deprecated Features (not in latest extraction)")
            lines.append(
                "# ============================================================================"
            )
            lines.append("")

            for feature_name, feature_def in deprecated_features:
                lines.append(f'# [features."{feature_name}"]  # DEPRECATED')
                lines.append(
                    f'# description = "{feature_def.get("description", "")}"'
                )
                lines.append("")

        # Defaults section
        lines.append(
            "# ============================================================================"
        )
        lines.append("# Global Configuration")
        lines.append(
            "# ============================================================================"
        )
        lines.append("")
        lines.append("[defaults]")
        lines.append("# Auto-grouping settings")
        # Handle missing defaults section gracefully
        defaults = map_data.get("defaults", {})
        for key, value in defaults.items():
            lines.append(f"{key} = {value}")

        # Write to file (ensure directory exists)
        self.map_file.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(lines)
        self.map_file.write_text(content, encoding="utf-8")

    def _normalize_components(self, components: List) -> List[Dict[str, Any]]:
        """Normalize components to ensure all tracking fields exist.
        
        Handles both old string format and new dict format.
        Adds tracking fields: complexity, loc, time_estimate, completion
        
        Args:
            components: List of component refs (strings or dicts)
            
        Returns:
            List of component dicts with all required fields
        """
        normalized = []
        for comp in components:
            if isinstance(comp, dict):
                # Preserve existing values or set defaults
                source_loc = comp.get("source_location", "")
                # Convert False/None to empty string
                if source_loc is False or source_loc is None:
                    source_loc = ""
                
                loc = comp.get("loc", 0)
                
                # If source_location is empty and loc is 0, time_estimate MUST be "0:00"
                if not source_loc and loc == 0:
                    time_estimate = "0:00"
                else:
                    time_estimate = comp.get("time_estimate", "0:00")
                    
                comp_dict = {
                    "ref": comp.get("ref", ""),
                    "source_location": source_loc,
                    "complexity": comp.get("complexity", "na"),
                    "loc": loc,
                    "time_estimate": time_estimate,
                    "completion": comp.get("completion", "100%"),
                }
                normalized.append(comp_dict)
            else:
                # Old string format - convert to dict with defaults
                comp_dict = {
                    "ref": comp,
                    "source_location": "",
                    "complexity": "na",
                    "loc": 0,  # Default LOC for string format
                    "time_estimate": "0:00",
                    "completion": "100%",
                }
                normalized.append(comp_dict)
        return normalized

    def _escape_toml_string(self, s: str) -> str:
        """Escape special characters in TOML string."""
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
