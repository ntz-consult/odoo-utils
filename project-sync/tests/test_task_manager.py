"""Tests for Task manager."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from feature_detector import Component, ComponentType, Feature, UserStory
from odoo_client import OdooClient
from task_manager import TaskError, TaskManager


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock OdooClient."""
    client = MagicMock(spec=OdooClient)
    client.read_only = False
    client._uid = 42
    return client


@pytest.fixture
def sample_component() -> Component:
    """Create a sample component."""
    return Component(
        id=1,
        name="x_test_field",
        display_name="Test Field",
        component_type=ComponentType.FIELD,
        model="sale.order",
        complexity="medium",
        raw_data={},
        is_studio=True,
    )


@pytest.fixture
def sample_user_story(sample_component: Component) -> UserStory:
    """Create a sample user story."""
    return UserStory(
        title="Implement test field",
        description="Add custom field to sales order",
        components=[sample_component],
        estimated_hours=2.0,
        logged_hours=0.5,
        status="pending",
    )


@pytest.fixture
def sample_feature(
    sample_component: Component, sample_user_story: UserStory
) -> Feature:
    """Create a sample feature."""
    return Feature(
        name="Sales Enhancements",
        description="Custom sales order functionality",
        user_stories=[sample_user_story],
        components=[sample_component],
        affected_models={"sale.order"},
    )


class TestTaskManagerInit:
    """Tests for TaskManager initialization."""

    def test_init(self, mock_client: MagicMock) -> None:
        """Test initialization."""
        tm = TaskManager(mock_client, project_id=123, sale_line_id=456)

        assert tm.client == mock_client
        assert tm.project_id == 123
        assert tm.sale_line_id == 456
        assert tm._stage_cache == {}
        assert tm._tag_cache == {}
        assert tm._task_cache == {}
        assert tm._custom_fields_verified is False


class TestTaskManagerStages:
    """Tests for stage management."""

    def test_ensure_stages_all_exist(self, mock_client: MagicMock) -> None:
        """Test ensure_stages when all stages exist."""
        # Return a stage for each search
        mock_client.search_read.return_value = [{"id": 1}]

        tm = TaskManager(mock_client, project_id=123)
        stages = tm.ensure_stages(dry_run=True)

        assert len(stages) == 6
        mock_client.create.assert_not_called()

    def test_ensure_stages_missing_dry_run(
        self, mock_client: MagicMock
    ) -> None:
        """Test dry-run raises when stage missing."""
        mock_client.search_read.return_value = []

        tm = TaskManager(mock_client, project_id=123)

        with pytest.raises(TaskError, match="does not exist"):
            tm.ensure_stages(dry_run=True)

    def test_ensure_stages_create(self, mock_client: MagicMock) -> None:
        """Test creating missing stages."""
        mock_client.search_read.return_value = []
        mock_client.create.side_effect = [1, 2, 3, 4, 5, 6]

        tm = TaskManager(mock_client, project_id=123)
        stages = tm.ensure_stages(dry_run=False)

        assert len(stages) == 6
        assert mock_client.create.call_count == 6

    def test_get_stage_id(self, mock_client: MagicMock) -> None:
        """Test getting stage ID."""
        mock_client.search_read.return_value = [{"id": 5}]

        tm = TaskManager(mock_client, project_id=123)
        stage_id = tm.get_stage_id("Done")

        assert stage_id == 5

    def test_get_stage_id_cached(self, mock_client: MagicMock) -> None:
        """Test stage ID caching."""
        mock_client.search_read.return_value = [{"id": 5}]

        tm = TaskManager(mock_client, project_id=123)
        tm.get_stage_id("Done")
        tm.get_stage_id("Done")

        # Should only call once due to caching
        assert mock_client.search_read.call_count == 1

    def test_get_stage_id_not_found(self, mock_client: MagicMock) -> None:
        """Test error when stage not found."""
        mock_client.search_read.return_value = []

        tm = TaskManager(mock_client, project_id=123)

        with pytest.raises(TaskError, match="not found"):
            tm.get_stage_id("Nonexistent")

    def test_move_task_to_stage(self, mock_client: MagicMock) -> None:
        """Test moving task to stage."""
        mock_client.search_read.return_value = [{"id": 5}]
        mock_client.write.return_value = True

        tm = TaskManager(mock_client, project_id=123)
        result = tm.move_task_to_stage(100, "Done", dry_run=False)

        assert result is True
        mock_client.write.assert_called_once()


class TestTaskManagerTags:
    """Tests for tag management."""

    def test_ensure_tags_all_exist(self, mock_client: MagicMock) -> None:
        """Test ensure_tags when all tags exist."""
        mock_client.search_read.side_effect = [
            [{"id": 1}],
            [{"id": 2}],
        ]

        tm = TaskManager(mock_client, project_id=123)
        tag_ids = tm.ensure_tags(["Tag1", "Tag2"], dry_run=True)

        assert tag_ids == [1, 2]
        mock_client.create.assert_not_called()

    def test_ensure_tags_create_missing(self, mock_client: MagicMock) -> None:
        """Test creating missing tags."""
        mock_client.search_read.return_value = []
        mock_client.create.side_effect = [10, 20]

        tm = TaskManager(mock_client, project_id=123)
        tag_ids = tm.ensure_tags(["Tag1", "Tag2"], dry_run=False)

        assert tag_ids == [10, 20]
        assert mock_client.create.call_count == 2

    def test_generate_tags_for_user_story(
        self,
        mock_client: MagicMock,
        sample_user_story: UserStory,
        sample_feature: Feature,
    ) -> None:
        """Test tag generation for user story."""
        tm = TaskManager(mock_client, project_id=123)
        tags = tm.generate_tags_for_user_story(
            sample_user_story, sample_feature
        )

        assert "Module:Sales" in tags
        assert "Complexity:Medium" in tags
        assert "Type:Field" in tags

    def test_generate_tags_complexity_simple(
        self, mock_client: MagicMock
    ) -> None:
        """Test complexity tag for simple components."""
        component = Component(
            id=1,
            name="x_simple",
            display_name="Simple",
            component_type=ComponentType.FIELD,
            model="res.partner",
            complexity="simple",
            raw_data={},
        )
        story = UserStory(
            title="Test",
            description="Test",
            components=[component],
            estimated_hours=1.0,
        )
        feature = Feature(
            name="Test",
            description="Test",
            user_stories=[story],
            components=[component],
            affected_models={"res.partner"},
        )

        tm = TaskManager(mock_client, project_id=123)
        tags = tm.generate_tags_for_user_story(story, feature)

        assert "Complexity:Simple" in tags

    def test_generate_tags_complexity_complex(
        self, mock_client: MagicMock
    ) -> None:
        """Test complexity tag for complex components."""
        component = Component(
            id=1,
            name="x_complex",
            display_name="Complex",
            component_type=ComponentType.VIEW,
            model="sale.order",
            complexity="very_complex",
            raw_data={},
        )
        story = UserStory(
            title="Test",
            description="Test",
            components=[component],
            estimated_hours=8.0,
        )
        feature = Feature(
            name="Test",
            description="Test",
            user_stories=[story],
            components=[component],
            affected_models={"sale.order"},
        )

        tm = TaskManager(mock_client, project_id=123)
        tags = tm.generate_tags_for_user_story(story, feature)

        assert "Complexity:Complex" in tags

    def test_get_tag_color_module(self, mock_client: MagicMock) -> None:
        """Test module tag color."""
        tm = TaskManager(mock_client, project_id=123)
        assert tm._get_tag_color("Module:Sales") == 4  # Blue

    def test_get_tag_color_complexity_simple(
        self, mock_client: MagicMock
    ) -> None:
        """Test simple complexity tag color."""
        tm = TaskManager(mock_client, project_id=123)
        assert tm._get_tag_color("Complexity:Simple") == 10  # Green

    def test_get_tag_color_complexity_complex(
        self, mock_client: MagicMock
    ) -> None:
        """Test complex complexity tag color."""
        tm = TaskManager(mock_client, project_id=123)
        assert tm._get_tag_color("Complexity:Complex") == 1  # Red

    def test_get_tag_color_component(self, mock_client: MagicMock) -> None:
        """Test component type tag color."""
        tm = TaskManager(mock_client, project_id=123)
        assert tm._get_tag_color("Type:Field") == 0  # Gray


class TestTaskManagerTasks:
    """Tests for task CRUD operations."""

    def test_ensure_task_exists(
        self,
        mock_client: MagicMock,
        sample_user_story: UserStory,
        sample_feature: Feature,
    ) -> None:
        """Test ensure_task when task exists."""
        sample_user_story.odoo_task_id = 100
        mock_client.read.return_value = [{"id": 100, "name": "Test"}]

        tm = TaskManager(mock_client, project_id=123)
        task_id = tm.ensure_task(
            sample_user_story, sample_feature, dry_run=True
        )

        assert task_id == 100
        mock_client.create.assert_not_called()

    def test_ensure_task_missing_dry_run(
        self,
        mock_client: MagicMock,
        sample_user_story: UserStory,
        sample_feature: Feature,
    ) -> None:
        """Test dry-run raises when task missing."""
        tm = TaskManager(mock_client, project_id=123)

        with pytest.raises(TaskError, match="does not exist"):
            tm.ensure_task(sample_user_story, sample_feature, dry_run=True)

    def test_ensure_task_create(
        self,
        mock_client: MagicMock,
        sample_user_story: UserStory,
        sample_feature: Feature,
    ) -> None:
        """Test creating new task."""
        # Stage search
        mock_client.search_read.return_value = [{"id": 1}]
        # Task creation
        mock_client.create.return_value = 200

        tm = TaskManager(mock_client, project_id=123)
        task_id = tm.ensure_task(
            sample_user_story,
            sample_feature,
            dry_run=False,
        )

        assert task_id == 200

    def test_get_task(self, mock_client: MagicMock) -> None:
        """Test getting task by ID."""
        mock_client.read.return_value = [{"id": 100, "name": "Test Task"}]

        tm = TaskManager(mock_client, project_id=123)
        task = tm.get_task(100)

        assert task is not None
        assert task["id"] == 100

    def test_get_task_cached(self, mock_client: MagicMock) -> None:
        """Test task caching."""
        mock_client.read.return_value = [{"id": 100, "name": "Test Task"}]

        tm = TaskManager(mock_client, project_id=123)
        tm.get_task(100)
        tm.get_task(100)

        assert mock_client.read.call_count == 1

    def test_get_task_not_found(self, mock_client: MagicMock) -> None:
        """Test getting non-existent task."""
        mock_client.read.return_value = []

        tm = TaskManager(mock_client, project_id=123)
        task = tm.get_task(999)

        assert task is None

    def test_update_task(self, mock_client: MagicMock) -> None:
        """Test updating task."""
        mock_client.write.return_value = True

        tm = TaskManager(mock_client, project_id=123)
        result = tm.update_task(100, {"name": "Updated"}, dry_run=False)

        assert result is True
        mock_client.write.assert_called_once()

    def test_update_task_dry_run(self, mock_client: MagicMock) -> None:
        """Test dry-run skips update."""
        tm = TaskManager(mock_client, project_id=123)
        result = tm.update_task(100, {"name": "Updated"}, dry_run=True)

        assert result is True
        mock_client.write.assert_not_called()

    def test_create_task(self, mock_client: MagicMock) -> None:
        """Test creating task with specified values."""
        mock_client.search_read.return_value = [{"id": 1}]  # Stage
        mock_client.create.return_value = 300

        tm = TaskManager(mock_client, project_id=123)
        task_id = tm.create_task(
            name="New Task",
            description="Task description",
            stage_name="Backlog",
            tags=["Tag1"],
            dry_run=False,
        )

        assert task_id == 300


class TestTaskManagerTimesheets:
    """Tests for timesheet/logged hours."""

    def test_get_logged_hours(self, mock_client: MagicMock) -> None:
        """Test getting logged hours from timesheets."""
        mock_client.search_read.return_value = [
            {"unit_amount": 2.5},
            {"unit_amount": 1.5},
        ]

        tm = TaskManager(mock_client, project_id=123)
        hours = tm.get_logged_hours(100)

        assert hours == 4.0

    def test_get_logged_hours_no_entries(self, mock_client: MagicMock) -> None:
        """Test logged hours with no timesheet entries."""
        mock_client.search_read.return_value = []

        tm = TaskManager(mock_client, project_id=123)
        hours = tm.get_logged_hours(100)

        assert hours == 0.0


class TestTaskManagerCache:
    """Tests for cache management."""

    def test_clear_cache(self, mock_client: MagicMock) -> None:
        """Test clearing all caches."""
        tm = TaskManager(mock_client, project_id=123)
        tm._stage_cache = {"Backlog": 1}
        tm._tag_cache = {"Tag1": 10}
        tm._task_cache = {100: {"id": 100}}

        tm.clear_cache()

        assert tm._stage_cache == {}
        assert tm._tag_cache == {}
        assert tm._task_cache == {}
