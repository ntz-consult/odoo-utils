"""Project task management for Odoo Project Sync.

Manages Odoo project tasks for user stories:
- Task CRUD with stage management
- Auto-generated tags (module, complexity, component)
- Custom field for Knowledge article linkage
- Timesheet hours query
"""

from typing import Any

try:
    from .feature_detector import Component, ComponentType, Feature, UserStory
    from .odoo_client import OdooClient, OdooClientError
except ImportError:
    from feature_detector import Component, ComponentType, Feature, UserStory
    from odoo_client import OdooClient, OdooClientError


class TaskError(Exception):
    """Task operation error."""

    pass


# Model name to module mapping for tag generation
MODEL_MODULE_MAP = {
    "sale.order": "Sales",
    "sale.order.line": "Sales",
    "purchase.order": "Purchasing",
    "purchase.order.line": "Purchasing",
    "res.partner": "Contacts",
    "res.users": "Users",
    "res.company": "Company",
    "product.product": "Products",
    "product.template": "Products",
    "stock.picking": "Inventory",
    "stock.move": "Inventory",
    "stock.quant": "Inventory",
    "account.move": "Accounting",
    "account.move.line": "Accounting",
    "account.payment": "Payments",
    "mrp.production": "Manufacturing",
    "mrp.bom": "Manufacturing",
    "project.project": "Projects",
    "project.task": "Projects",
    "hr.employee": "HR",
    "crm.lead": "CRM",
    "helpdesk.ticket": "Helpdesk",
}


class TaskManager:
    """Manage Odoo project tasks for user stories."""

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

    # Tag color codes (Odoo color palette)
    TAG_COLOR_MODULE = 4  # Blue
    TAG_COLOR_SIMPLE = 10  # Green
    TAG_COLOR_MEDIUM = 3  # Yellow
    TAG_COLOR_COMPLEX = 1  # Red
    TAG_COLOR_COMPONENT = 0  # Gray

    # Task model
    TASK_MODEL = "project.task"
    STAGE_MODEL = "project.task.type"
    TAG_MODEL = "project.tags"
    TIMESHEET_MODEL = "account.analytic.line"
    FIELD_MODEL = "ir.model.fields"

    def __init__(
        self,
        client: OdooClient,
        project_id: int,
        sale_line_id: int | None = None,
    ):
        """Initialize Task manager.

        Args:
            client: Authenticated OdooClient (must be read/write)
            project_id: Odoo project ID for tasks
            sale_line_id: Optional sale order line for billing linkage
        """
        self.client = client
        self.project_id = project_id
        self.sale_line_id = sale_line_id

        # Caches
        self._stage_cache: dict[str, int] = {}
        self._tag_cache: dict[str, int] = {}
        self._task_cache: dict[int, dict[str, Any]] = {}
        self._custom_fields_verified = False

    def ensure_task(
        self,
        user_story: UserStory,
        feature: Feature,
        dry_run: bool = True,
    ) -> int:
        """Create or update task for user story.

        Args:
            user_story: UserStory to create/update task for
            feature: Parent feature (for tag generation)
            dry_run: If True, only check existence (don't create/update)

        Returns:
            Task ID

        Raises:
            TaskError: If task operation fails
        """
        existing_id = user_story.odoo_task_id

        # Check if existing task is valid
        if existing_id:
            task = self.get_task(existing_id)
            if task:
                # Task exists - update if needed
                if not dry_run:
                    self._update_task_from_story(
                        existing_id, user_story, feature
                    )
                return existing_id

        if dry_run:
            raise TaskError(
                f"Task for '{user_story.title}' does not exist. "
                "Run with --execute to create."
            )

        # Create new task
        return self._create_task_from_story(
            user_story, feature
        )

    def _create_task_from_story(
        self,
        user_story: UserStory,
        feature: Feature,
    ) -> int:
        """Create a new task from user story.

        Args:
            user_story: UserStory to create task for
            feature: Parent feature

        Returns:
            Created task ID

        Raises:
            TaskError: If creation fails
        """
        # Get stage ID (default to Backlog)
        stage_id = self._get_stage_id_for_status(user_story.status)

        # Generate and ensure tags exist
        tag_names = self.generate_tags_for_user_story(user_story, feature)
        tag_ids = self.ensure_tags(tag_names, dry_run=False)

        # Build task values
        vals: dict[str, Any] = {
            "name": user_story.title,
            "description": self._format_task_description(user_story, feature),
            "project_id": self.project_id,
            "stage_id": stage_id,
            "tag_ids": [(6, 0, tag_ids)] if tag_ids else False,
        }

        # Check if task with same name exists and already has sale_line_id
        existing_task_id = self.find_task_by_name(user_story.title)
        if existing_task_id:
            existing_task = self.get_task(existing_task_id)
            if existing_task and not existing_task.get("sale_line_id"):
                # Only set if not already filled
                if self.sale_line_id:
                    vals["sale_line_id"] = self.sale_line_id
        else:
            # New task, set sale_line_id if available
            if self.sale_line_id:
                vals["sale_line_id"] = self.sale_line_id

        try:
            return self.client.create(self.TASK_MODEL, vals)
        except OdooClientError as e:
            raise TaskError(f"Failed to create task: {e}")

    def _update_task_from_story(
        self,
        task_id: int,
        user_story: UserStory,
        feature: Feature,
    ) -> bool:
        """Update existing task from user story.

        Args:
            task_id: Task ID to update
            user_story: UserStory with updated data
            feature: Parent feature

        Returns:
            True if updated successfully

        Raises:
            TaskError: If update fails
        """
        # Only update select fields to preserve manual changes
        vals: dict[str, Any] = {
            "name": user_story.title,
        }

        # Update stage if status changed
        stage_id = self._get_stage_id_for_status(user_story.status)
        if stage_id:
            vals["stage_id"] = stage_id

        # Update tags
        tag_names = self.generate_tags_for_user_story(user_story, feature)
        tag_ids = self.ensure_tags(tag_names, dry_run=False)
        if tag_ids:
            vals["tag_ids"] = [(6, 0, tag_ids)]

        # Only set sale_line_id if task doesn't already have one
        if self.sale_line_id:
            existing_task = self.get_task(task_id)
            if existing_task and not existing_task.get("sale_line_id"):
                vals["sale_line_id"] = self.sale_line_id

        try:
            return self.client.write(self.TASK_MODEL, [task_id], vals)
        except OdooClientError as e:
            raise TaskError(f"Failed to update task: {e}")

    def create_task(
        self,
        name: str,
        description: str,
        stage_name: str,
        tags: list[str],
        dry_run: bool = True,
    ) -> int:
        """Create a new task with specified values.

        Args:
            name: Task name
            description: Task description (HTML)
            stage_name: Stage name to place task in
            tags: List of tag names
            dry_run: If True, don't create (return 0)

        Returns:
            Task ID (or 0 if dry_run)

        Raises:
            TaskError: If creation fails
        """
        if dry_run:
            return 0

        stage_id = self.get_stage_id(stage_name)
        tag_ids = self.ensure_tags(tags, dry_run=False) if tags else []

        vals: dict[str, Any] = {
            "name": name,
            "description": description,
            "project_id": self.project_id,
            "stage_id": stage_id,
            "tag_ids": [(6, 0, tag_ids)] if tag_ids else False,
        }

        # Check if task with same name exists and already has sale_line_id
        existing_task_id = self.find_task_by_name(name)
        if existing_task_id:
            existing_task = self.get_task(existing_task_id)
            if existing_task and not existing_task.get("sale_line_id"):
                # Only set if not already filled
                if self.sale_line_id:
                    vals["sale_line_id"] = self.sale_line_id
        else:
            # New task, set sale_line_id if available
            if self.sale_line_id:
                vals["sale_line_id"] = self.sale_line_id

        try:
            return self.client.create(self.TASK_MODEL, vals)
        except OdooClientError as e:
            raise TaskError(f"Failed to create task: {e}")

    def update_task(
        self,
        task_id: int,
        vals: dict[str, Any],
        dry_run: bool = True,
    ) -> bool:
        """Update task with specified values.

        Args:
            task_id: Task ID to update
            vals: Field values to update
            dry_run: If True, don't update

        Returns:
            True if updated successfully (or dry_run)

        Raises:
            TaskError: If update fails
        """
        if dry_run:
            return True

        try:
            # Invalidate cache
            self._task_cache.pop(task_id, None)
            return self.client.write(self.TASK_MODEL, [task_id], vals)
        except OdooClientError as e:
            raise TaskError(f"Failed to update task: {e}")

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        """Get task by ID with caching.

        Args:
            task_id: Task ID to fetch

        Returns:
            Task record dict or None if not found
        """
        if task_id in self._task_cache:
            return self._task_cache[task_id]

        try:
            records = self.client.read(
                self.TASK_MODEL,
                [task_id],
                [
                    "id",
                    "name",
                    "description",
                    "project_id",
                    "stage_id",
                    "tag_ids",
                    "sale_line_id",
                ],
            )
            if records:
                self._task_cache[task_id] = records[0]
                return records[0]
        except OdooClientError:
            pass

        return None

    def get_logged_hours(self, task_id: int) -> float:
        """Get total logged hours from timesheets.

        Args:
            task_id: Task ID to query

        Returns:
            Total hours logged
        """
        try:
            records = self.client.search_read(
                self.TIMESHEET_MODEL,
                [("task_id", "=", task_id)],
                ["unit_amount"],
            )
            return sum(r.get("unit_amount", 0) for r in records)
        except OdooClientError:
            return 0.0

    def find_task_by_name(self, task_name: str) -> int | None:
        """Find a task by its name in the current project.

        Args:
            task_name: Exact task name to search for

        Returns:
            Task ID if found, None otherwise
        """
        try:
            task_ids = self.client.search(
                self.TASK_MODEL,
                [
                    ("project_id", "=", self.project_id),
                    ("name", "=", task_name),
                ],
                limit=1,
            )
            return task_ids[0] if task_ids else None
        except OdooClientError:
            return None

    # Stage management

    def ensure_stages(self, dry_run: bool = True) -> dict[str, int]:
        """Ensure all required stages exist for the project.

        Args:
            dry_run: If True, only check existence

        Returns:
            Dict mapping stage name to ID

        Raises:
            TaskError: If stage creation fails
        """
        result: dict[str, int] = {}

        for stage_name, sequence in self.STAGES:
            stage_id = self._find_stage(stage_name)

            if stage_id:
                result[stage_name] = stage_id
            elif dry_run:
                raise TaskError(
                    f"Stage '{stage_name}' does not exist. "
                    "Run with --execute to create."
                )
            else:
                # Create stage
                try:
                    stage_id = self.client.create(
                        self.STAGE_MODEL,
                        {
                            "name": stage_name,
                            "sequence": sequence,
                            "project_ids": [(4, self.project_id)],
                        },
                    )
                    result[stage_name] = stage_id
                    self._stage_cache[stage_name] = stage_id
                except OdooClientError as e:
                    raise TaskError(
                        f"Failed to create stage '{stage_name}': {e}"
                    )

        # Update cache
        self._stage_cache.update(result)
        return result

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

    def get_stage_id(self, stage_name: str) -> int:
        """Get stage ID by name.

        Args:
            stage_name: Stage name

        Returns:
            Stage ID

        Raises:
            TaskError: If stage not found
        """
        stage_id = self._find_stage(stage_name)
        if not stage_id:
            raise TaskError(f"Stage '{stage_name}' not found")
        return stage_id

    def move_task_to_stage(
        self,
        task_id: int,
        stage_name: str,
        dry_run: bool = True,
    ) -> bool:
        """Move task to specified stage.

        Args:
            task_id: Task ID
            stage_name: Target stage name
            dry_run: If True, don't move

        Returns:
            True if moved successfully

        Raises:
            TaskError: If move fails
        """
        if dry_run:
            return True

        stage_id = self.get_stage_id(stage_name)
        return self.update_task(task_id, {"stage_id": stage_id}, dry_run=False)

    def _get_stage_id_for_status(self, status: str) -> int | None:
        """Map user story status to stage ID.

        Args:
            status: User story status

        Returns:
            Stage ID or None
        """
        status_stage_map = {
            "pending": self.STAGE_BACKLOG,
            "in_progress": self.STAGE_IN_PROGRESS,
            "completed": self.STAGE_DONE,
        }
        stage_name = status_stage_map.get(status)
        if stage_name:
            return self._find_stage(stage_name)
        return None

    # Tag management

    def ensure_tags(
        self,
        tag_names: list[str],
        dry_run: bool = True,
    ) -> list[int]:
        """Ensure tags exist and return their IDs.

        Args:
            tag_names: List of tag names
            dry_run: If True, only return existing tag IDs

        Returns:
            List of tag IDs
        """
        result: list[int] = []

        for tag_name in tag_names:
            tag_id = self._find_tag(tag_name)

            if tag_id:
                result.append(tag_id)
            elif not dry_run:
                # Create tag
                try:
                    tag_id = self.client.create(
                        self.TAG_MODEL,
                        {
                            "name": tag_name,
                            "color": self._get_tag_color(tag_name),
                        },
                    )
                    result.append(tag_id)
                    self._tag_cache[tag_name] = tag_id
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
        if tag_name in self._tag_cache:
            return self._tag_cache[tag_name]

        try:
            records = self.client.search_read(
                self.TAG_MODEL,
                [("name", "=", tag_name)],
                ["id"],
                limit=1,
            )
            if records:
                tag_id = records[0]["id"]
                self._tag_cache[tag_name] = tag_id
                return tag_id
        except OdooClientError:
            pass

        return None

    def generate_tags_for_user_story(
        self,
        user_story: UserStory,
        feature: Feature,
    ) -> list[str]:
        """Generate tag names for a user story.

        Tags are generated from:
        - Module names (from affected models)
        - Complexity (aggregated from components)
        - Component types

        Args:
            user_story: UserStory to generate tags for
            feature: Parent feature

        Returns:
            List of tag names
        """
        tags: set[str] = set()

        # Module tags from affected models
        for model in feature.affected_models:
            module = MODEL_MODULE_MAP.get(model)
            if module:
                tags.add(f"Module:{module}")

        # Complexity tag (aggregate from components)
        complexity = self._aggregate_complexity(user_story.components)
        if complexity:
            tags.add(f"Complexity:{complexity}")

        # Component type tags
        type_labels = set()
        for comp in user_story.components:
            type_labels.add(comp.type_label)
        for label in type_labels:
            tags.add(f"Type:{label}")

        return sorted(tags)

    def _aggregate_complexity(self, components: list[Component]) -> str:
        """Determine overall complexity from components.

        Args:
            components: List of components

        Returns:
            Complexity label (Simple, Medium, Complex)
        """
        if not components:
            return "Simple"

        complexity_scores = {
            "simple": 1,
            "medium": 2,
            "complex": 3,
            "very_complex": 4,
        }

        max_score = max(
            complexity_scores.get(c.complexity, 1) for c in components
        )

        if max_score >= 4:
            return "Complex"
        elif max_score >= 2:
            return "Medium"
        return "Simple"

    def _get_tag_color(self, tag_name: str) -> int:
        """Get Odoo color code for tag.

        Args:
            tag_name: Tag name

        Returns:
            Odoo color code (0-11)
        """
        if tag_name.startswith("Module:"):
            return self.TAG_COLOR_MODULE
        elif tag_name.startswith("Complexity:"):
            complexity = tag_name.split(":")[1]
            if complexity == "Simple":
                return self.TAG_COLOR_SIMPLE
            elif complexity == "Medium":
                return self.TAG_COLOR_MEDIUM
            else:
                return self.TAG_COLOR_COMPLEX
        elif tag_name.startswith("Type:"):
            return self.TAG_COLOR_COMPONENT
        return 0

    # Custom field management
    # (removed - knowledge article fields no longer used)

    def _get_model_id(self, model_name: str) -> int:
        """Get ir.model ID for model name.

        Args:
            model_name: Technical model name

        Returns:
            Model ID

        Raises:
            TaskError: If model not found
        """
        try:
            records = self.client.search_read(
                "ir.model",
                [("model", "=", model_name)],
                ["id"],
                limit=1,
            )
            if records:
                return records[0]["id"]
        except OdooClientError:
            pass

        raise TaskError(f"Model '{model_name}' not found")

    def _format_task_description(
        self,
        user_story: UserStory,
        feature: Feature,
    ) -> str:
        """Format task description from user story.

        Args:
            user_story: UserStory
            feature: Parent feature

        Returns:
            HTML description
        """
        html = f"<p>{user_story.description}</p>\n"
        html += f"<p><strong>Feature:</strong> {feature.name}</p>\n"

        if user_story.components:
            html += "<h3>Components</h3>\n<ul>\n"
            for comp in user_story.components:
                html += (
                    f"<li><strong>{comp.type_label}:</strong> "
                    f"{comp.display_name} ({comp.model})</li>\n"
                )
            html += "</ul>\n"

        return html

    def clear_cache(self) -> None:
        """Clear all caches."""
        self._stage_cache.clear()
        self._tag_cache.clear()
        self._task_cache.clear()
