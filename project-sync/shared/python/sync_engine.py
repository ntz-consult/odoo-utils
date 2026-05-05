"""Sync Engine for feature_user_story_map.toml to Odoo tasks.

Bidirectional synchronization:
- Creates Odoo tasks for features (task_id == 0)
- Creates Odoo subtasks for user stories (task_id == 0)
- Validates existing task_ids (task_id > 0) exist in Odoo
- Recreates tasks if task_id is invalid AND story has valid source_location
- Removes stories if task_id is invalid AND story has NO valid source_location
- Updates TOML file with created/recreated task IDs and removes orphaned stories
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from .odoo_client import OdooClient, OdooClientError
except ImportError:
    from odoo_client import OdooClient, OdooClientError


class SyncError(Exception):
    """Sync operation error."""

    pass


@dataclass
class SyncResult:
    """Result of a sync operation.

    Attributes:
        features_created: Number of features created in Odoo
        user_stories_created: Number of user stories created in Odoo
        features_validated: Number of features validated against Odoo
        user_stories_validated: Number of user stories validated against Odoo
        features_recreated: Number of features recreated (task_id was invalid)
        user_stories_recreated: Number of user stories recreated (task_id was invalid, has source_location)
        user_stories_removed: Number of user stories removed (task_id was invalid, no source_location)
        user_stories_imported: Number of user stories imported from Odoo
        errors: List of error messages
    """

    features_created: int = 0
    user_stories_created: int = 0
    features_validated: int = 0
    user_stories_validated: int = 0
    features_recreated: int = 0
    user_stories_recreated: int = 0
    user_stories_removed: int = 0
    user_stories_imported: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Generate human-readable summary.

        Returns:
            Formatted summary string
        """
        lines = []

        if self.features_created > 0:
            lines.append(f"Features created: {self.features_created}")

        if self.user_stories_created > 0:
            lines.append(f"User stories created: {self.user_stories_created}")

        if self.features_validated > 0:
            lines.append(f"Features validated: {self.features_validated}")

        if self.user_stories_validated > 0:
            lines.append(f"User stories validated: {self.user_stories_validated}")

        if self.features_recreated > 0:
            lines.append(f"Features recreated (invalid task_id): {self.features_recreated}")

        if self.user_stories_recreated > 0:
            lines.append(f"User stories recreated (invalid task_id): {self.user_stories_recreated}")

        if self.user_stories_removed > 0:
            lines.append(f"User stories removed (invalid task_id, no source_location): {self.user_stories_removed}")

        if self.user_stories_imported > 0:
            lines.append(f"User stories imported from Odoo: {self.user_stories_imported}")

        if self.errors:
            lines.append(f"Errors: {len(self.errors)}")
            for error in self.errors:
                lines.append(f"  - {error}")

        if not lines:
            return "No changes made."

        return "\n".join(lines)


class SyncEngine:
    """Sync engine for feature_user_story_map.toml to Odoo tasks.

    Creates Odoo tasks for features and subtasks for user stories
    based on the feature_user_story_map.toml file. Only items with
    task_id == 0 are processed.
    """

    # Odoo models
    TASK_MODEL = "project.task"
    TAG_MODEL = "project.tags"
    STAGE_MODEL = "project.task.type"

    # Stage names and sequence
    STAGE_BACKLOG = "Backlog"
    STAGE_UP_NEXT = "Up Next"
    STAGE_IN_PROGRESS = "In Progress"
    STAGE_USER_ACCEPTANCE = "User Acceptance"
    STAGE_DONE = "Done"
    STAGE_ARCHIVE = "Archive"

    STAGES = [
        (STAGE_BACKLOG, 1),
        (STAGE_UP_NEXT, 2),
        (STAGE_IN_PROGRESS, 3),
        (STAGE_USER_ACCEPTANCE, 4),
        (STAGE_DONE, 5),
        (STAGE_ARCHIVE, 6),
    ]

    def __init__(
        self,
        client: OdooClient,
        project_id: int,
        project_root: Path,
    ):
        """Initialize sync engine.

        Args:
            client: Authenticated OdooClient (must be read/write)
            project_id: Odoo project ID for tasks
            project_root: Project root directory (contains studio/feature_user_story_map.toml)
        """
        self.client = client
        self.project_id = project_id
        self.project_root = project_root
        self.toml_path = project_root / "studio" / "feature_user_story_map.toml"

        # Caches
        self._tag_cache: dict[str, int] = {}
        self._stage_cache: dict[str, int] = {}

    def sync(self, dry_run: bool = True) -> SyncResult:
        """Execute bidirectional synchronization between TOML and Odoo.

        Bidirectional sync logic:
        - If task_id == 0: Create new task in Odoo, update TOML with new task_id
        - If task_id > 0: Validate task exists in Odoo
          - If task exists: No action needed (validated)
          - If task does not exist: Create new task, update TOML (recreated)

        Args:
            dry_run: If True, only validate connectivity (no changes made)

        Returns:
            SyncResult with created/validated/recreated counts and errors
        """
        result = SyncResult()

        # Step 1: Validate Odoo connectivity
        try:
            connection = self.client.test_connection()
            if not connection["success"]:
                raise SyncError(
                    f"Odoo connection failed: {connection.get('error', 'Unknown error')}"
                )
        except OdooClientError as e:
            raise SyncError(f"Odoo connection failed: {e}")

        if dry_run:
            # Dry run only validates connectivity
            return result

        # Step 2: Parse TOML file
        toml_data = self._parse_toml()

        # Step 3: Process features and user stories with bidirectional validation
        features = toml_data.get("features", {})

        for feature_name, feature_def in features.items():
            # Skip deprecated features
            if feature_def.get("_deprecated"):
                continue

            feature_task_id = feature_def.get("task_id", 0)

            # Handle feature task
            if feature_task_id == 0:
                # Create new feature task
                feature_task_id = self._create_feature_task(
                    feature_name, feature_def
                )
                feature_def["task_id"] = feature_task_id
                result.features_created += 1
            else:
                # Validate existing task_id exists in Odoo
                if self._task_exists(feature_task_id):
                    result.features_validated += 1
                else:
                    # Task doesn't exist - recreate it
                    feature_task_id = self._create_feature_task(
                        feature_name, feature_def
                    )
                    feature_def["task_id"] = feature_task_id
                    result.features_recreated += 1

            # Process user stories
            user_stories = feature_def.get("user_stories", [])
            stories_to_remove = []
            
            for story in user_stories:
                story_task_id = story.get("task_id", 0)

                if story_task_id == 0:
                    # Create new user story task
                    story_task_id = self._create_user_story_task(
                        story, feature_task_id
                    )
                    story["task_id"] = story_task_id
                    result.user_stories_created += 1
                else:
                    # Validate existing task_id exists in Odoo with correct parent
                    # This ensures the story belongs to THIS feature in THIS project
                    if self._story_task_valid(story_task_id, feature_task_id):
                        result.user_stories_validated += 1
                    else:
                        # Task doesn't exist or has wrong parent
                        # Check if story has a valid source_location
                        source_location = story.get("source_location", "")
                        has_valid_source = source_location and source_location.strip()
                        
                        if has_valid_source:
                            # Has source_location - recreate task
                            story_task_id = self._create_user_story_task(
                                story, feature_task_id
                            )
                            story["task_id"] = story_task_id
                            result.user_stories_recreated += 1
                        else:
                            # No valid source_location - mark for removal
                            stories_to_remove.append(story)
                            result.user_stories_removed += 1
            
            # Remove stories marked for deletion
            for story in stories_to_remove:
                user_stories.remove(story)

        # Step 4: Import new stories from Odoo (Odoo → TOML)
        imported_count = self._import_stories_from_odoo(toml_data)
        result.user_stories_imported = imported_count

        # Step 5: Write updated TOML back to disk
        self._write_toml(toml_data)

        return result

    def _task_exists(self, task_id: int) -> bool:
        """Check if a task exists in Odoo and belongs to the correct project.

        Args:
            task_id: Task ID to check

        Returns:
            True if task exists and belongs to the configured project, False otherwise
        """
        try:
            records = self.client.search_read(
                self.TASK_MODEL,
                [("id", "=", task_id), ("project_id", "=", self.project_id)],
                ["id"],
                limit=1,
            )
            return len(records) > 0
        except OdooClientError:
            return False

    def _story_task_valid(self, task_id: int, expected_parent_id: int) -> bool:
        """Check if a story task exists and has the correct parent.

        Args:
            task_id: Task ID to check
            expected_parent_id: Expected parent task ID

        Returns:
            True if task exists in project with correct parent, False otherwise
        """
        try:
            records = self.client.search_read(
                self.TASK_MODEL,
                [
                    ("id", "=", task_id),
                    ("project_id", "=", self.project_id),
                    ("parent_id", "=", expected_parent_id),
                ],
                ["id"],
                limit=1,
            )
            return len(records) > 0
        except OdooClientError:
            return False

    def _import_stories_from_odoo(self, toml_data: dict[str, Any]) -> int:
        """Import new stories from Odoo tasks into the TOML data.

        Queries all tasks in the project and creates new stories for tasks
        that have a parent_id matching a feature's task_id but are not yet
        represented in the TOML.

        Args:
            toml_data: The TOML data dictionary (modified in place)

        Returns:
            Number of stories imported
        """
        features = toml_data.get("features", {})

        # Build lookup: feature_task_id -> feature_name (only for features with task_id > 0)
        # IMPORTANT: Only include task_ids that are validated to exist in THIS project
        feature_by_task_id: dict[int, str] = {}
        for feature_name, feature_def in features.items():
            if feature_def.get("_deprecated"):
                continue
            feature_task_id = feature_def.get("task_id", 0)
            if feature_task_id > 0:
                # Validate this task_id belongs to our project before using it for matching
                if self._task_exists(feature_task_id):
                    feature_by_task_id[feature_task_id] = feature_name

        if not feature_by_task_id:
            # No features with validated task_ids to match against
            return 0

        # Build set of all existing story task_ids in TOML
        # Only include task_ids that are validated to exist in THIS project
        existing_story_task_ids: set[int] = set()
        for feature_name, feature_def in features.items():
            for story in feature_def.get("user_stories", []):
                story_task_id = story.get("task_id", 0)
                if story_task_id > 0:
                    # Only consider it "existing" if it's in our project
                    if self._task_exists(story_task_id):
                        existing_story_task_ids.add(story_task_id)

        # Query all tasks in the project from Odoo
        try:
            odoo_tasks = self.client.search_read(
                self.TASK_MODEL,
                [("project_id", "=", self.project_id)],
                ["id", "name", "parent_id"],
            )
        except OdooClientError as e:
            # Log error but don't fail the sync
            return 0

        imported_count = 0

        for task in odoo_tasks:
            task_id = task["id"]
            task_name = task["name"]
            parent_id_field = task.get("parent_id")

            # Skip tasks without parent_id
            if not parent_id_field:
                continue

            # parent_id is typically [id, name] tuple or False
            if isinstance(parent_id_field, (list, tuple)) and len(parent_id_field) >= 1:
                parent_id = parent_id_field[0]
            elif isinstance(parent_id_field, int):
                parent_id = parent_id_field
            else:
                continue

            # Skip if task is already in TOML
            if task_id in existing_story_task_ids:
                continue

            # Check if parent_id matches a feature's task_id
            if parent_id not in feature_by_task_id:
                continue

            # Found a new story to import
            feature_name = feature_by_task_id[parent_id]
            feature_def = features[feature_name]

            # Determine next sequence number
            user_stories = feature_def.get("user_stories", [])
            max_sequence = max((s.get("sequence", 0) for s in user_stories), default=0)

            # Create new story with minimal fields
            new_story = {
                "name": task_name,
                "description": "",
                "sequence": max_sequence + 1,
                "task_id": task_id,
                "tags": "Story",
                "components": [],
            }

            # Append to feature's user_stories
            if "user_stories" not in feature_def:
                feature_def["user_stories"] = []
            feature_def["user_stories"].append(new_story)

            # Track for duplicate prevention within this run
            existing_story_task_ids.add(task_id)
            imported_count += 1

        return imported_count

    def _parse_toml(self) -> dict[str, Any]:
        """Parse the feature_user_story_map.toml file.

        Returns:
            Parsed TOML data as dictionary

        Raises:
            SyncError: If file not found or parsing fails
        """
        if not self.toml_path.exists():
            raise SyncError(
                f"feature_user_story_map.toml not found at {self.toml_path}"
            )

        try:
            with open(self.toml_path, "rb") as f:
                return tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise SyncError(f"Failed to parse TOML file: {e}")

    def _create_feature_task(
        self, feature_name: str, feature_def: dict[str, Any]
    ) -> int:
        """Create an Odoo task for a feature.

        Args:
            feature_name: Name of the feature
            feature_def: Feature definition from TOML

        Returns:
            Created task ID

        Raises:
            SyncError: If task creation fails
        """
        description = feature_def.get("description", "")
        tags_csv = feature_def.get("tags", "")

        # Parse tags from CSV
        tag_names = self._parse_tags_csv(tags_csv)
        tag_ids = self._ensure_tags(tag_names)

        # Get backlog stage for new tasks
        stage_id = self._get_backlog_stage_id()

        vals: dict[str, Any] = {
            "name": feature_name,
            "description": description,
            "project_id": self.project_id,
            "stage_id": stage_id,
        }

        if tag_ids:
            vals["tag_ids"] = [(6, 0, tag_ids)]

        try:
            task_id = self.client.create(self.TASK_MODEL, vals)
            return task_id
        except OdooClientError as e:
            raise SyncError(f"Failed to create feature task '{feature_name}': {e}")

    def _create_user_story_task(
        self, story: dict[str, Any], parent_id: int
    ) -> int:
        """Create an Odoo subtask for a user story.

        Args:
            story: User story definition from TOML
            parent_id: Parent feature task ID

        Returns:
            Created subtask ID

        Raises:
            SyncError: If subtask creation fails
        """
        name = story.get("name", "Unnamed Story")
        description = story.get("description", "")
        tags_csv = story.get("tags", "")

        # Parse tags from CSV
        tag_names = self._parse_tags_csv(tags_csv)
        tag_ids = self._ensure_tags(tag_names)

        # Get backlog stage for new tasks
        stage_id = self._get_backlog_stage_id()

        vals: dict[str, Any] = {
            "name": name,
            "description": description,
            "project_id": self.project_id,
            "parent_id": parent_id,
            "stage_id": stage_id,
        }

        if tag_ids:
            vals["tag_ids"] = [(6, 0, tag_ids)]

        try:
            task_id = self.client.create(self.TASK_MODEL, vals)
            return task_id
        except OdooClientError as e:
            raise SyncError(f"Failed to create user story task '{name}': {e}")

    def _parse_tags_csv(self, tags_csv: str) -> list[str]:
        """Parse comma-separated tags string.

        Args:
            tags_csv: Comma-separated tags string

        Returns:
            List of tag names (trimmed, non-empty)
        """
        if not tags_csv:
            return []

        return [tag.strip() for tag in tags_csv.split(",") if tag.strip()]

    def _ensure_tags(self, tag_names: list[str]) -> list[int]:
        """Ensure tags exist in Odoo and return their IDs.

        Creates tags if they don't exist.

        Args:
            tag_names: List of tag names

        Returns:
            List of tag IDs
        """
        result: list[int] = []

        for tag_name in tag_names:
            # Check cache first
            if tag_name in self._tag_cache:
                result.append(self._tag_cache[tag_name])
                continue

            # Search for existing tag
            tag_id = self._find_tag(tag_name)

            if tag_id:
                self._tag_cache[tag_name] = tag_id
                result.append(tag_id)
            else:
                # Create new tag
                try:
                    tag_id = self.client.create(
                        self.TAG_MODEL,
                        {"name": tag_name},
                    )
                    self._tag_cache[tag_name] = tag_id
                    result.append(tag_id)
                except OdooClientError:
                    pass  # Skip failed tags

        return result

    def _find_tag(self, tag_name: str) -> int | None:
        """Find tag by name.

        Args:
            tag_name: Tag name to find

        Returns:
            Tag ID or None
        """
        try:
            records = self.client.search_read(
                self.TAG_MODEL,
                [("name", "=", tag_name)],
                ["id"],
                limit=1,
            )
            if records:
                return records[0]["id"]
        except OdooClientError:
            pass

        return None

    # =========================================================================
    # Stage Management
    # =========================================================================

    def _find_stage(self, stage_name: str) -> int | None:
        """Find stage by name for current project.

        Args:
            stage_name: Stage name to find

        Returns:
            Stage ID or None
        """
        if stage_name in self._stage_cache:
            return self._stage_cache[stage_name]

        try:
            records = self.client.search_read(
                self.STAGE_MODEL,
                [
                    ("name", "=", stage_name),
                    "|",
                    ("project_ids", "=", False),
                    ("project_ids", "in", [self.project_id]),
                ],
                ["id"],
                limit=1,
            )
            if records:
                stage_id = records[0]["id"]
                self._stage_cache[stage_name] = stage_id
                return stage_id
        except OdooClientError:
            pass

        return None

    def _ensure_stage(self, stage_name: str, sequence: int) -> int:
        """Ensure a stage exists for the project.

        Creates the stage if it doesn't exist.

        Args:
            stage_name: Stage name
            sequence: Stage sequence number

        Returns:
            Stage ID

        Raises:
            SyncError: If stage creation fails
        """
        stage_id = self._find_stage(stage_name)

        if stage_id:
            return stage_id

        # Create the stage
        try:
            stage_id = self.client.create(
                self.STAGE_MODEL,
                {
                    "name": stage_name,
                    "sequence": sequence,
                    "project_ids": [(4, self.project_id)],
                },
            )
            self._stage_cache[stage_name] = stage_id
            return stage_id
        except OdooClientError as e:
            raise SyncError(f"Failed to create stage '{stage_name}': {e}")

    def _get_backlog_stage_id(self) -> int:
        """Get or create the Backlog stage ID.

        Returns:
            Backlog stage ID

        Raises:
            SyncError: If stage cannot be found or created
        """
        return self._ensure_stage(self.STAGE_BACKLOG, 1)

    def ensure_stages(self) -> dict[str, int]:
        """Ensure all required stages exist for the project.

        Returns:
            Dict mapping stage name to ID

        Raises:
            SyncError: If stage creation fails
        """
        result: dict[str, int] = {}

        for stage_name, sequence in self.STAGES:
            stage_id = self._ensure_stage(stage_name, sequence)
            result[stage_name] = stage_id

        return result

    def _calculate_statistics(self, map_data: dict[str, Any]) -> dict[str, Any]:
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

    def _write_toml(self, data: dict[str, Any]) -> None:
        """Write updated TOML data back to file.

        Uses manual formatting for readability with inline arrays.

        Args:
            data: TOML data to write
        """
        lines = []

        # Header comment
        lines.append("# Feature-User Story Mapping for TODO Generation")
        lines.append("# Generated by odoo-project-sync v1.1.7")
        lines.append("#")
        lines.append("# STRUCTURE:")
        lines.append(
            "# - Features: Business capabilities that will become Knowledge articles"
        )
        lines.append("# - User Stories: User-facing work items with component lists")
        lines.append("# - Components: String references with model qualification")
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
        lines.append(
            "# - Components in 'Unassigned Components' should be reassigned"
        )
        lines.append("#")
        lines.append("# Edit  enrich-status from 'done' back to:")        
        lines.append("# 'refresh-all' (for both AI + effort)")        
        lines.append("# 'refresh-stories' (for AI enrichment only)")        
        lines.append("# 'refresh-effort' (for effort estimation only)")         
        lines.append("")

        # Metadata section
        if "metadata" in data:
            lines.append("[metadata]")
            for key, value in data["metadata"].items():
                if isinstance(value, bool):
                    lines.append(f"{key} = {str(value).lower()}")
                elif isinstance(value, str):
                    lines.append(f'{key} = "{value}"')
                else:
                    lines.append(f"{key} = {value}")
            lines.append("")

        # Calculate and update statistics
        data["statistics"] = self._calculate_statistics(data)

        # Statistics section
        if "statistics" in data:
            lines.append("[statistics]")
            for key, value in data["statistics"].items():
                if isinstance(value, str):
                    lines.append(f'{key} = "{value}"')
                else:
                    lines.append(f"{key} = {value}")
            lines.append("")

        # Features sections
        features = data.get("features", {})

        # Sort features: active first, deprecated last
        active_features = []
        deprecated_features = []

        for feature_name, feature_def in sorted(features.items()):
            if feature_def.get("_deprecated"):
                deprecated_features.append((feature_name, feature_def))
            else:
                active_features.append((feature_name, feature_def))

        # Write active features
        for feature_name, feature_def in active_features:
            self._write_feature(lines, feature_name, feature_def)

        # Write deprecated features
        for feature_name, feature_def in deprecated_features:
            self._write_feature(lines, feature_name, feature_def, deprecated=True)

        # Write to file
        self.toml_path.write_text("\n".join(lines) + "\n")

    def _write_feature(
        self,
        lines: list[str],
        feature_name: str,
        feature_def: dict[str, Any],
        deprecated: bool = False,
    ) -> None:
        """Write a single feature section to lines.

        Args:
            lines: List of lines to append to
            feature_name: Feature name
            feature_def: Feature definition
            deprecated: Whether feature is deprecated
        """
        if deprecated:
            lines.append(f"# --- DEPRECATED Feature: {feature_name} ---")
        else:
            lines.append(f"# --- Feature: {feature_name} ---")

        lines.append(f'[features."{feature_name}"]')

        # Write feature fields
        description = feature_def.get("description", "")
        if description:
            lines.append(f'description = "{self._escape_toml_string(description)}"')

        sequence = feature_def.get("sequence", 1)
        lines.append(f"sequence = {sequence}")

        enrich_status = feature_def.get("enrich-status", "")
        if enrich_status:
            lines.append(f'enrich-status = "{enrich_status}"')

        task_id = feature_def.get("task_id", 0)
        lines.append(f"task_id = {task_id}")

        tags = feature_def.get("tags", "")
        if tags:
            lines.append(f'tags = "{tags}"')

        if deprecated:
            lines.append("_deprecated = true")

        # Write user stories
        user_stories = feature_def.get("user_stories", [])
        if user_stories:
            lines.append("")
            lines.append("user_stories = [")
            for i, story in enumerate(user_stories):
                story_line = self._format_user_story(story)
                if i < len(user_stories) - 1:
                    lines.append(f"    {story_line},")
                else:
                    lines.append(f"    {story_line},")
            lines.append("]")

        lines.append("")

    def _format_user_story(self, story: dict[str, Any]) -> str:
        """Format a user story as an inline TOML table.

        Args:
            story: User story definition

        Returns:
            Formatted inline table string
        """
        parts = []

        # Name
        name = story.get("name", "")
        parts.append(f'name = "{self._escape_toml_string(name)}"')

        # Description
        description = story.get("description", "")
        parts.append(f'description = "{self._escape_toml_string(description)}"')

        # Sequence
        sequence = story.get("sequence", 1)
        parts.append(f"sequence = {sequence}")

        # Enrich status
        enrich_status = story.get("enrich-status", "")
        if enrich_status:
            parts.append(f'enrich-status = "{enrich_status}"')

        # Task ID
        task_id = story.get("task_id", 0)
        parts.append(f"task_id = {task_id}")

        # Tags
        tags = story.get("tags", "")
        if tags:
            parts.append(f'tags = "{tags}"')

        # Components
        components = story.get("components", [])
        if components:
            comp_strs = []
            for comp in components:
                if isinstance(comp, dict):
                    comp_parts = []
                    # Define desired field order for components
                    field_order = ["ref", "source_location", "complexity", "loc", "time_estimate", "completion"]
                    # Write fields in order if they exist
                    for key in field_order:
                        if key in comp:
                            value = comp[key]
                            if isinstance(value, str):
                                comp_parts.append(
                                    f'{key} = "{self._escape_toml_string(value)}"'
                                )
                            else:
                                comp_parts.append(f"{key} = {value}")
                    # Write any remaining fields not in the order list
                    for key, value in comp.items():
                        if key not in field_order:
                            if isinstance(value, str):
                                comp_parts.append(
                                    f'{key} = "{self._escape_toml_string(value)}"'
                                )
                            else:
                                comp_parts.append(f"{key} = {value}")
                    comp_strs.append("{ " + ", ".join(comp_parts) + " }")
                else:
                    comp_strs.append(f'"{comp}"')
            parts.append("components = [\n        " + ",\n        ".join(comp_strs) + ",\n    ]")

        return "{ " + ", ".join(parts) + " }"

    def _escape_toml_string(self, s: str) -> str:
        """Escape a string for TOML.

        Args:
            s: String to escape

        Returns:
            Escaped string
        """
        return (
            s.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )

