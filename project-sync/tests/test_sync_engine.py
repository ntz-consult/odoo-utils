"""Tests for sync engine - TOML to Odoo task synchronization."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from odoo_client import OdooClient
from sync_engine import SyncEngine, SyncError, SyncResult


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_client() -> MagicMock:
    """Create mock OdooClient."""
    client = MagicMock(spec=OdooClient)
    client.read_only = False
    # test_connection returns success by default
    client.test_connection.return_value = {
        "success": True,
        "server_version": "17.0",
        "user_id": 1,
        "user_name": "Test User",
        "user_login": "test@example.com",
        "database": "test_db",
        "url": "https://test.odoo.com",
        "read_only": False,
    }
    return client


@pytest.fixture
def sample_toml_content() -> str:
    """Sample TOML content for testing."""
    return '''# Feature-User Story Mapping
[metadata]
generated_at = "2025-12-18T13:18:27"
extraction_count = 10

[statistics]
total_features = 2
total_user_stories = 3
total_components = 10

[features."Customer Portal"]
description = "Customer portal feature"
sequence = 1
task_id = 0
tags = "Feature"

user_stories = [
    { name = "Login page", description = "Create login page", sequence = 1, task_id = 0, tags = "Story", components = [] },
    { name = "Dashboard", description = "Create dashboard", sequence = 2, task_id = 0, tags = "Story", components = [] },
]

[features."Inventory Management"]
description = "Inventory tracking feature"
sequence = 2
task_id = 123
tags = "Feature"

user_stories = [
    { name = "Stock levels", description = "Show stock levels", sequence = 1, task_id = 456, tags = "Story", components = [] },
]
'''


@pytest.fixture
def sync_engine(mock_client: MagicMock, tmp_path: Path, sample_toml_content: str) -> SyncEngine:
    """Create SyncEngine instance with test TOML file."""
    # Create studio directory and TOML file
    studio_dir = tmp_path / "studio"
    studio_dir.mkdir()
    toml_path = studio_dir / "feature_user_story_map.toml"
    toml_path.write_text(sample_toml_content)

    return SyncEngine(
        client=mock_client,
        project_id=100,
        project_root=tmp_path,
    )


# =============================================================================
# SyncResult Tests
# =============================================================================


class TestSyncResult:
    """Tests for SyncResult dataclass."""

    def test_default_values(self) -> None:
        """Test default SyncResult values."""
        result = SyncResult()
        assert result.features_created == 0
        assert result.user_stories_created == 0
        assert result.features_validated == 0
        assert result.user_stories_validated == 0
        assert result.features_recreated == 0
        assert result.user_stories_recreated == 0
        assert result.user_stories_imported == 0
        assert result.errors == []

    def test_summary_no_changes(self) -> None:
        """Test summary with no changes."""
        result = SyncResult()
        summary = result.summary()
        assert "No changes" in summary

    def test_summary_with_features(self) -> None:
        """Test summary with features created."""
        result = SyncResult(features_created=3)
        summary = result.summary()
        assert "Features created: 3" in summary

    def test_summary_with_user_stories(self) -> None:
        """Test summary with user stories created."""
        result = SyncResult(user_stories_created=5)
        summary = result.summary()
        assert "User stories created: 5" in summary

    def test_summary_with_validated(self) -> None:
        """Test summary with validated tasks."""
        result = SyncResult(features_validated=2, user_stories_validated=4)
        summary = result.summary()
        assert "Features validated: 2" in summary
        assert "User stories validated: 4" in summary

    def test_summary_with_imported(self) -> None:
        """Test summary with imported user stories."""
        result = SyncResult(user_stories_imported=3)
        summary = result.summary()
        assert "User stories imported from Odoo: 3" in summary

    def test_summary_with_recreated(self) -> None:
        """Test summary with recreated tasks."""
        result = SyncResult(features_recreated=1, user_stories_recreated=2)
        summary = result.summary()
        assert "Features recreated" in summary
        assert "User stories recreated" in summary

    def test_summary_with_errors(self) -> None:
        """Test summary with errors."""
        result = SyncResult(errors=["Error 1", "Error 2"])
        summary = result.summary()
        assert "Errors: 2" in summary
        assert "Error 1" in summary

    def test_summary_with_removed(self) -> None:
        """Test summary with removed user stories."""
        result = SyncResult(user_stories_removed=3)
        summary = result.summary()
        assert "User stories removed (invalid task_id, no source_location): 3" in summary


# =============================================================================
# SyncEngine Initialization Tests
# =============================================================================


class TestSyncEngineInit:
    """Tests for SyncEngine initialization."""

    def test_init_sets_attributes(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Test that __init__ sets all attributes correctly."""
        engine = SyncEngine(
            client=mock_client,
            project_id=100,
            project_root=tmp_path,
        )
        assert engine.client == mock_client
        assert engine.project_id == 100
        assert engine.project_root == tmp_path
        assert engine.toml_path == tmp_path / "studio" / "feature_user_story_map.toml"

    def test_init_creates_empty_caches(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Test that __init__ creates empty caches."""
        engine = SyncEngine(
            client=mock_client,
            project_id=100,
            project_root=tmp_path,
        )
        assert engine._tag_cache == {}
        assert engine._stage_cache == {}


# =============================================================================
# Dry Run Tests
# =============================================================================


class TestSyncDryRun:
    """Tests for dry run mode."""

    def test_dry_run_validates_connectivity(
        self, sync_engine: SyncEngine, mock_client: MagicMock
    ) -> None:
        """Test that dry run validates Odoo connectivity."""
        result = sync_engine.sync(dry_run=True)

        mock_client.test_connection.assert_called_once()
        assert result.features_created == 0
        assert result.user_stories_created == 0

    def test_dry_run_fails_on_connection_error(
        self, sync_engine: SyncEngine, mock_client: MagicMock
    ) -> None:
        """Test that dry run fails when connection fails."""
        mock_client.test_connection.return_value = {
            "success": False,
            "error": "Connection refused",
        }

        with pytest.raises(SyncError) as exc_info:
            sync_engine.sync(dry_run=True)

        assert "Connection refused" in str(exc_info.value)


# =============================================================================
# TOML Parsing Tests
# =============================================================================


class TestTomlParsing:
    """Tests for TOML file parsing."""

    def test_parse_toml_file_not_found(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Test error when TOML file doesn't exist."""
        engine = SyncEngine(
            client=mock_client,
            project_id=100,
            project_root=tmp_path,
        )

        with pytest.raises(SyncError) as exc_info:
            engine._parse_toml()

        assert "not found" in str(exc_info.value)

    def test_parse_toml_invalid_content(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Test error when TOML content is invalid."""
        studio_dir = tmp_path / "studio"
        studio_dir.mkdir()
        toml_path = studio_dir / "feature_user_story_map.toml"
        toml_path.write_text("invalid [ toml content")

        engine = SyncEngine(
            client=mock_client,
            project_id=100,
            project_root=tmp_path,
        )

        with pytest.raises(SyncError) as exc_info:
            engine._parse_toml()

        assert "Failed to parse TOML" in str(exc_info.value)


# =============================================================================
# Task Creation Tests
# =============================================================================


class TestTaskCreation:
    """Tests for task creation."""

    def test_creates_feature_tasks(
        self, sync_engine: SyncEngine, mock_client: MagicMock
    ) -> None:
        """Test that features with task_id=0 get tasks created."""
        # Mock search_read to handle different models
        def search_read_side_effect(model, domain, fields=None, **kwargs):
            if model == "project.task.type":
                return [{"id": 1}]  # Backlog stage
            elif model == "project.tags":
                return [{"id": 50}]  # Tags exist
            elif model == "project.task":
                if domain == [("project_id", "=", 100)]:
                    return []  # No tasks in Odoo for import
                # For _task_exists checks (2 conditions: id + project_id)
                if domain and len(domain) == 2 and domain[0][0] == "id":
                    return [{"id": domain[0][2]}]
                # For _story_task_valid checks (3 conditions: id + project_id + parent_id)
                if domain and len(domain) == 3 and domain[0][0] == "id":
                    return [{"id": domain[0][2]}]
                return []
            return []

        mock_client.search_read.side_effect = search_read_side_effect
        # Mock task creation - return sequential IDs
        mock_client.create.side_effect = [1000, 1001, 1002]

        result = sync_engine.sync(dry_run=False)

        # Should create 1 feature task (Customer Portal) + 2 user stories
        # Inventory Management already has task_id=123, and its story has task_id=456
        assert result.features_created == 1
        assert result.user_stories_created == 2

    def test_skips_existing_tasks(
        self, sync_engine: SyncEngine, mock_client: MagicMock
    ) -> None:
        """Test that features/stories with existing task_id are skipped."""
        def search_read_side_effect(model, domain, fields=None, **kwargs):
            if model == "project.task.type":
                return [{"id": 1}]
            elif model == "project.tags":
                return [{"id": 50}]  # Tags exist
            elif model == "project.task":
                if domain == [("project_id", "=", 100)]:
                    return []  # No tasks to import
                # For _task_exists checks (2 conditions: id + project_id)
                if domain and len(domain) == 2 and domain[0][0] == "id":
                    return [{"id": domain[0][2]}]
                # For _story_task_valid checks (3 conditions: id + project_id + parent_id)
                if domain and len(domain) == 3 and domain[0][0] == "id":
                    return [{"id": domain[0][2]}]
                return []
            return []

        mock_client.search_read.side_effect = search_read_side_effect
        mock_client.create.side_effect = [1000, 1001, 1002]

        result = sync_engine.sync(dry_run=False)

        # Inventory Management (task_id=123) and its story (task_id=456) should be validated
        assert result.features_created == 1  # Only Customer Portal
        assert result.user_stories_created == 2  # Only Customer Portal's stories

    def test_task_creation_includes_stage(
        self, sync_engine: SyncEngine, mock_client: MagicMock
    ) -> None:
        """Test that created tasks include stage_id."""
        def search_read_side_effect(model, domain, fields=None, **kwargs):
            if model == "project.task.type":
                return [{"id": 99}]  # Backlog stage ID
            elif model == "project.tags":
                return [{"id": 50}]  # Tags exist
            elif model == "project.task":
                if domain == [("project_id", "=", 100)]:
                    return []  # No tasks to import
                # For _task_exists checks (2 conditions: id + project_id)
                if domain and len(domain) == 2 and domain[0][0] == "id":
                    return [{"id": domain[0][2]}]
                # For _story_task_valid checks (3 conditions: id + project_id + parent_id)
                if domain and len(domain) == 3 and domain[0][0] == "id":
                    return [{"id": domain[0][2]}]
                return []
            return []

        mock_client.search_read.side_effect = search_read_side_effect
        mock_client.create.side_effect = [1000, 1001, 1002]

        sync_engine.sync(dry_run=False)

        # Check that create was called with stage_id
        create_calls = mock_client.create.call_args_list
        for call in create_calls:
            if call[0][0] == "project.task":  # Task model
                vals = call[0][1]
                assert "stage_id" in vals
                assert vals["stage_id"] == 99

    def test_task_creation_includes_parent_id(
        self, sync_engine: SyncEngine, mock_client: MagicMock
    ) -> None:
        """Test that user story tasks include parent_id."""
        def search_read_side_effect(model, domain, fields=None, **kwargs):
            if model == "project.task.type":
                return [{"id": 1}]
            elif model == "project.tags":
                return [{"id": 50}]  # Tags exist
            elif model == "project.task":
                if domain == [("project_id", "=", 100)]:
                    return []  # No tasks to import
                # For _task_exists checks (2 conditions: id + project_id)
                if domain and len(domain) == 2 and domain[0][0] == "id":
                    return [{"id": domain[0][2]}]
                # For _story_task_valid checks (3 conditions: id + project_id + parent_id)
                if domain and len(domain) == 3 and domain[0][0] == "id":
                    return [{"id": domain[0][2]}]
                return []
            return []

        mock_client.search_read.side_effect = search_read_side_effect
        # First create returns feature task ID, subsequent returns story IDs
        mock_client.create.side_effect = [1000, 1001, 1002]

        sync_engine.sync(dry_run=False)

        # Find the user story task creation calls (should have parent_id)
        create_calls = mock_client.create.call_args_list
        story_calls = [
            c for c in create_calls 
            if c[0][0] == "project.task" and "parent_id" in c[0][1]
        ]
        assert len(story_calls) == 2  # Two user stories for Customer Portal

        for call in story_calls:
            vals = call[0][1]
            assert vals["parent_id"] == 1000  # Parent is the feature task


# =============================================================================
# Tag Management Tests
# =============================================================================


class TestTagManagement:
    """Tests for tag creation and management."""

    def test_creates_missing_tags(
        self, sync_engine: SyncEngine, mock_client: MagicMock
    ) -> None:
        """Test that missing tags are created."""
        # Mock: no existing tags found, stage exists
        def search_read_side_effect(model, domain, *args, **kwargs):
            if model == "project.tags":
                return []  # No existing tags
            elif model == "project.task.type":
                return [{"id": 1}]  # Stage exists
            return []

        mock_client.search_read.side_effect = search_read_side_effect
        mock_client.create.return_value = 100

        sync_engine.sync(dry_run=False)

        # Check that tags were created
        tag_create_calls = [
            c for c in mock_client.create.call_args_list
            if c[0][0] == "project.tags"
        ]
        assert len(tag_create_calls) > 0

    def test_reuses_existing_tags(
        self, sync_engine: SyncEngine, mock_client: MagicMock
    ) -> None:
        """Test that existing tags are reused."""
        # Mock: existing tags found
        def search_read_side_effect(model, domain, *args, **kwargs):
            if model == "project.tags":
                return [{"id": 50}]  # Existing tag
            elif model == "project.task.type":
                return [{"id": 1}]
            return []

        mock_client.search_read.side_effect = search_read_side_effect
        mock_client.create.return_value = 100

        sync_engine.sync(dry_run=False)

        # Tags should NOT be created (they exist)
        tag_create_calls = [
            c for c in mock_client.create.call_args_list
            if c[0][0] == "project.tags"
        ]
        assert len(tag_create_calls) == 0

    def test_parse_tags_csv(self, sync_engine: SyncEngine) -> None:
        """Test CSV tag parsing."""
        assert sync_engine._parse_tags_csv("") == []
        assert sync_engine._parse_tags_csv("Feature") == ["Feature"]
        assert sync_engine._parse_tags_csv("Tag1, Tag2, Tag3") == ["Tag1", "Tag2", "Tag3"]
        assert sync_engine._parse_tags_csv("  Spaced  ,  Tags  ") == ["Spaced", "Tags"]


# =============================================================================
# Stage Management Tests
# =============================================================================


class TestStageManagement:
    """Tests for stage management."""

    def test_finds_existing_stage(
        self, sync_engine: SyncEngine, mock_client: MagicMock
    ) -> None:
        """Test that existing stages are found."""
        mock_client.search_read.return_value = [{"id": 42}]

        stage_id = sync_engine._find_stage("Backlog")

        assert stage_id == 42
        mock_client.search_read.assert_called()

    def test_creates_missing_stage(
        self, sync_engine: SyncEngine, mock_client: MagicMock
    ) -> None:
        """Test that missing stages are created."""
        mock_client.search_read.return_value = []  # Stage not found
        mock_client.create.return_value = 99

        stage_id = sync_engine._ensure_stage("Backlog", 1)

        assert stage_id == 99
        mock_client.create.assert_called_with(
            "project.task.type",
            {
                "name": "Backlog",
                "sequence": 1,
                "project_ids": [(4, 100)],  # project_id=100
            },
        )

    def test_ensure_all_stages(
        self, sync_engine: SyncEngine, mock_client: MagicMock
    ) -> None:
        """Test ensure_stages creates all required stages."""
        mock_client.search_read.return_value = []  # No stages exist
        mock_client.create.side_effect = [1, 2, 3, 4, 5, 6]  # Sequential IDs

        stages = sync_engine.ensure_stages()

        assert len(stages) == 6
        assert "Backlog" in stages
        assert "In Progress" in stages
        assert "Done" in stages


# =============================================================================
# TOML Writing Tests
# =============================================================================


class TestTomlWriting:
    """Tests for TOML file writing."""

    def test_updates_task_ids_in_toml(
        self, sync_engine: SyncEngine, mock_client: MagicMock
    ) -> None:
        """Test that task_ids are updated in TOML after sync."""
        def search_read_side_effect(model, domain, fields=None, **kwargs):
            if model == "project.task.type":
                return [{"id": 1}]
            elif model == "project.tags":
                return [{"id": 50}]  # Tags exist
            elif model == "project.task":
                if domain == [("project_id", "=", 100)]:
                    return []  # No tasks to import
                # For _task_exists checks (2 conditions: id + project_id)
                if domain and len(domain) == 2 and domain[0][0] == "id":
                    return [{"id": domain[0][2]}]
                # For _story_task_valid checks (3 conditions: id + project_id + parent_id)
                if domain and len(domain) == 3 and domain[0][0] == "id":
                    return [{"id": domain[0][2]}]
                return []
            return []

        mock_client.search_read.side_effect = search_read_side_effect
        mock_client.create.side_effect = [1000, 1001, 1002]

        sync_engine.sync(dry_run=False)

        # Read the updated TOML
        updated_content = sync_engine.toml_path.read_text()

        # Check that new task_ids appear in the file
        assert "task_id = 1000" in updated_content or "task_id = 1001" in updated_content

    def test_preserves_existing_task_ids(
        self, sync_engine: SyncEngine, mock_client: MagicMock
    ) -> None:
        """Test that existing task_ids are preserved."""
        # Mock task existence check - task 123 and 456 exist
        def search_read_side_effect(model, domain, *args, **kwargs):
            if model == "project.task":
                # For _task_exists checks (2 conditions: id + project_id)
                if len(domain) == 2 and domain[0][0] == "id":
                    task_id = domain[0][2]
                    if task_id in [123, 456]:
                        return [{"id": task_id}]
                    return []
                # For _story_task_valid checks (3 conditions: id + project_id + parent_id)
                if len(domain) == 3 and domain[0][0] == "id":
                    task_id = domain[0][2]
                    parent_id = domain[2][2]
                    # Task 456 has parent 123
                    if task_id == 456 and parent_id == 123:
                        return [{"id": task_id}]
                    return []
                return []
            elif model == "project.task.type":
                return [{"id": 1}]  # Stage exists
            elif model == "project.tags":
                return [{"id": 50}]  # Tag exists
            return []

        mock_client.search_read.side_effect = search_read_side_effect
        mock_client.create.side_effect = [1000, 1001, 1002]

        result = sync_engine.sync(dry_run=False)

        # Read the updated TOML
        updated_content = sync_engine.toml_path.read_text()

        # Inventory Management's existing task_id should be preserved
        assert "task_id = 123" in updated_content
        
        # Should have validated the existing tasks
        assert result.features_validated == 1  # Inventory Management
        assert result.user_stories_validated == 1  # Stock levels


# =============================================================================
# Bidirectional Validation Tests
# =============================================================================


class TestBidirectionalValidation:
    """Tests for bidirectional task validation."""

    def test_validates_existing_task_ids(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Test that existing task_ids are validated against Odoo."""
        toml_content = '''
[metadata]
generated_at = "2025-12-18T13:18:27"

[features."Feature With Task"]
description = "Has existing task"
sequence = 1
task_id = 999
tags = "Feature"
user_stories = []
'''
        studio_dir = tmp_path / "studio"
        studio_dir.mkdir()
        toml_path = studio_dir / "feature_user_story_map.toml"
        toml_path.write_text(toml_content)

        engine = SyncEngine(
            client=mock_client,
            project_id=100,
            project_root=tmp_path,
        )

        # Mock: task 999 exists in Odoo
        def search_read_side_effect(model, domain, *args, **kwargs):
            if model == "project.task" and domain and domain[0][2] == 999:
                return [{"id": 999}]  # Task exists
            elif model == "project.task.type":
                return [{"id": 1}]
            return []

        mock_client.search_read.side_effect = search_read_side_effect

        result = engine.sync(dry_run=False)

        assert result.features_validated == 1
        assert result.features_created == 0
        assert result.features_recreated == 0

    def test_recreates_invalid_task_ids(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Test that invalid task_ids trigger task recreation."""
        toml_content = '''
[metadata]
generated_at = "2025-12-18T13:18:27"

[features."Feature With Invalid Task"]
description = "Task no longer exists"
sequence = 1
task_id = 888
tags = "Feature"
user_stories = []
'''
        studio_dir = tmp_path / "studio"
        studio_dir.mkdir()
        toml_path = studio_dir / "feature_user_story_map.toml"
        toml_path.write_text(toml_content)

        engine = SyncEngine(
            client=mock_client,
            project_id=100,
            project_root=tmp_path,
        )

        # Mock: task 888 does NOT exist in Odoo
        def search_read_side_effect(model, domain, *args, **kwargs):
            if model == "project.task" and domain and domain[0][2] == 888:
                return []  # Task does NOT exist
            elif model == "project.task.type":
                return [{"id": 1}]
            elif model == "project.tags":
                return [{"id": 50}]
            return []

        mock_client.search_read.side_effect = search_read_side_effect
        mock_client.create.return_value = 2000  # New task ID

        result = engine.sync(dry_run=False)

        assert result.features_recreated == 1
        assert result.features_created == 0
        assert result.features_validated == 0

        # Check that TOML was updated with new task_id
        updated_content = engine.toml_path.read_text()
        assert "task_id = 2000" in updated_content
        assert "task_id = 888" not in updated_content

    def test_task_exists_check(
        self, sync_engine: SyncEngine, mock_client: MagicMock
    ) -> None:
        """Test the _task_exists helper method."""
        # Task exists
        mock_client.search_read.return_value = [{"id": 100}]
        assert sync_engine._task_exists(100) is True

        # Task doesn't exist
        mock_client.search_read.return_value = []
        assert sync_engine._task_exists(999) is False

    def test_recreates_user_story_with_invalid_task_id(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Test that user stories with invalid task_ids are removed if no source_location, recreated if they have source_location."""
        toml_content = '''
[metadata]
generated_at = "2025-12-18T13:18:27"

[features."Feature"]
description = "Parent feature"
sequence = 1
task_id = 100
tags = "Feature"

user_stories = [
    { name = "Valid Story", description = "Has valid task", sequence = 1, task_id = 200, tags = "Story", source_location = "", components = [] },
    { name = "Invalid Story No Source", description = "Task deleted, no source", sequence = 2, task_id = 300, tags = "Story", source_location = "", components = [] },
    { name = "Invalid Story With Source", description = "Task deleted, has source", sequence = 3, task_id = 400, tags = "Story", source_location = "models/my_model.py", components = [] },
]
'''
        studio_dir = tmp_path / "studio"
        studio_dir.mkdir()
        toml_path = studio_dir / "feature_user_story_map.toml"
        toml_path.write_text(toml_content)

        engine = SyncEngine(
            client=mock_client,
            project_id=100,
            project_root=tmp_path,
        )

        # Mock: feature task 100 and story 200 exist, but stories 300 and 400 don't
        def search_read_side_effect(model, domain, *args, **kwargs):
            if model == "project.task" and domain and domain[0][0] == "id":
                task_id = domain[0][2]
                if task_id in [100, 200]:
                    return [{"id": task_id}]  # Exists
                return []  # Doesn't exist (300, 400)
            elif model == "project.task.type":
                return [{"id": 1}]
            elif model == "project.tags":
                return [{"id": 50}]
            return []

        mock_client.search_read.side_effect = search_read_side_effect
        mock_client.create.return_value = 500  # New task ID for recreation

        result = engine.sync(dry_run=False)

        assert result.features_validated == 1
        assert result.user_stories_validated == 1
        assert result.user_stories_removed == 1  # Story without source_location removed
        assert result.user_stories_recreated == 1  # Story with source_location recreated

        # Check TOML was updated
        updated_content = engine.toml_path.read_text()
        assert "task_id = 100" in updated_content  # Feature preserved
        assert "task_id = 200" in updated_content  # Valid story preserved
        assert "Invalid Story No Source" not in updated_content  # Story without source removed
        assert "task_id = 500" in updated_content  # Story with source recreated
        assert "Invalid Story With Source" in updated_content  # Story with source preserved


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    def test_raises_sync_error_on_task_creation_failure(
        self, sync_engine: SyncEngine, mock_client: MagicMock
    ) -> None:
        """Test that SyncError is raised when task creation fails."""
        from odoo_client import OdooClientError

        mock_client.search_read.return_value = [{"id": 1}]
        mock_client.create.side_effect = OdooClientError("API Error")

        with pytest.raises(SyncError) as exc_info:
            sync_engine.sync(dry_run=False)

        assert "Failed to create" in str(exc_info.value)


# =============================================================================
# Deprecated Features Tests
# =============================================================================


class TestDeprecatedFeatures:
    """Tests for deprecated feature handling."""

    def test_skips_deprecated_features(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Test that deprecated features are skipped during sync."""
        toml_content = '''
[metadata]
generated_at = "2025-12-18T13:18:27"

[features."Active Feature"]
description = "Active"
sequence = 1
task_id = 0
tags = "Feature"

[features."Deprecated Feature"]
description = "Deprecated"
sequence = 2
task_id = 0
tags = "Feature"
_deprecated = true
'''
        studio_dir = tmp_path / "studio"
        studio_dir.mkdir()
        toml_path = studio_dir / "feature_user_story_map.toml"
        toml_path.write_text(toml_content)

        engine = SyncEngine(
            client=mock_client,
            project_id=100,
            project_root=tmp_path,
        )

        def search_read_side_effect(model, domain, fields=None, **kwargs):
            if model == "project.task.type":
                return [{"id": 1}]
            elif model == "project.task":
                if domain == [("project_id", "=", 100)]:
                    return []  # No tasks to import
                return []
            return []

        mock_client.search_read.side_effect = search_read_side_effect
        mock_client.create.return_value = 1000

        result = engine.sync(dry_run=False)

        # Only 1 feature should be created (Active Feature)
        assert result.features_created == 1


# =============================================================================
# Odoo → TOML Import Tests
# =============================================================================


class TestOdooToTomlImport:
    """Tests for importing stories from Odoo to TOML."""

    def test_imports_story_with_matching_parent(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Test that Odoo tasks with matching parent_id are imported as stories."""
        toml_content = '''
[metadata]
generated_at = "2025-12-18T13:18:27"

[features."Test Feature"]
description = "Test"
sequence = 1
task_id = 500
tags = "Feature"

user_stories = []
'''
        studio_dir = tmp_path / "studio"
        studio_dir.mkdir()
        toml_path = studio_dir / "feature_user_story_map.toml"
        toml_path.write_text(toml_content)

        engine = SyncEngine(
            client=mock_client,
            project_id=100,
            project_root=tmp_path,
        )

        # Mock search_read to return stage for validation, then Odoo tasks
        def search_read_side_effect(model, domain, fields, **kwargs):
            if model == "project.task.type":
                return [{"id": 1}]  # Stage
            elif model == "project.task":
                if domain == [("project_id", "=", 100)]:
                    # Return tasks from Odoo - one with parent_id matching feature
                    return [
                        {"id": 600, "name": "New Story from Odoo", "parent_id": [500, "Test Feature"]},
                    ]
                return [{"id": 500}]  # For _task_exists check
            return []

        mock_client.search_read.side_effect = search_read_side_effect

        result = engine.sync(dry_run=False)

        assert result.user_stories_imported == 1

        # Verify TOML was updated
        import tomllib
        with open(toml_path, "rb") as f:
            updated_toml = tomllib.load(f)
        
        stories = updated_toml["features"]["Test Feature"]["user_stories"]
        assert len(stories) == 1
        assert stories[0]["name"] == "New Story from Odoo"
        assert stories[0]["task_id"] == 600

    def test_skips_tasks_without_parent_id(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Test that tasks without parent_id are ignored."""
        toml_content = '''
[metadata]
generated_at = "2025-12-18T13:18:27"

[features."Test Feature"]
description = "Test"
sequence = 1
task_id = 500
tags = "Feature"

user_stories = []
'''
        studio_dir = tmp_path / "studio"
        studio_dir.mkdir()
        toml_path = studio_dir / "feature_user_story_map.toml"
        toml_path.write_text(toml_content)

        engine = SyncEngine(
            client=mock_client,
            project_id=100,
            project_root=tmp_path,
        )

        def search_read_side_effect(model, domain, fields, **kwargs):
            if model == "project.task.type":
                return [{"id": 1}]
            elif model == "project.task":
                if domain == [("project_id", "=", 100)]:
                    # Return task without parent_id (it's a feature-level task)
                    return [
                        {"id": 500, "name": "Test Feature", "parent_id": False},
                    ]
                return [{"id": 500}]
            return []

        mock_client.search_read.side_effect = search_read_side_effect

        result = engine.sync(dry_run=False)

        assert result.user_stories_imported == 0

    def test_skips_tasks_already_in_toml(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Test that tasks already in TOML are not duplicated."""
        toml_content = '''
[metadata]
generated_at = "2025-12-18T13:18:27"

[features."Test Feature"]
description = "Test"
sequence = 1
task_id = 500
tags = "Feature"

user_stories = [
    { name = "Existing Story", description = "", sequence = 1, task_id = 600, tags = "Story", components = [] },
]
'''
        studio_dir = tmp_path / "studio"
        studio_dir.mkdir()
        toml_path = studio_dir / "feature_user_story_map.toml"
        toml_path.write_text(toml_content)

        engine = SyncEngine(
            client=mock_client,
            project_id=100,
            project_root=tmp_path,
        )

        def search_read_side_effect(model, domain, fields, **kwargs):
            if model == "project.task.type":
                return [{"id": 1}]
            elif model == "project.task":
                if domain == [("project_id", "=", 100)]:
                    # Return the same task that's already in TOML
                    return [
                        {"id": 600, "name": "Existing Story", "parent_id": [500, "Test Feature"]},
                    ]
                # For _task_exists checks (2 conditions: id + project_id)
                if len(domain) == 2 and domain[0][0] == "id":
                    task_id = domain[0][2]
                    if task_id in [500, 600]:
                        return [{"id": task_id}]
                # For _story_task_valid checks (3 conditions: id + project_id + parent_id)
                if len(domain) == 3 and domain[0][0] == "id":
                    task_id = domain[0][2]
                    parent_id = domain[2][2]
                    # Return task exists if story 600 has parent 500
                    if task_id == 600 and parent_id == 500:
                        return [{"id": task_id}]
            return []

        mock_client.search_read.side_effect = search_read_side_effect

        result = engine.sync(dry_run=False)

        # Should not import - already exists
        assert result.user_stories_imported == 0
        assert result.user_stories_validated == 1

    def test_skips_tasks_with_unmatched_parent(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Test that tasks with parent_id not matching any feature are ignored."""
        toml_content = '''
[metadata]
generated_at = "2025-12-18T13:18:27"

[features."Test Feature"]
description = "Test"
sequence = 1
task_id = 500
tags = "Feature"

user_stories = []
'''
        studio_dir = tmp_path / "studio"
        studio_dir.mkdir()
        toml_path = studio_dir / "feature_user_story_map.toml"
        toml_path.write_text(toml_content)

        engine = SyncEngine(
            client=mock_client,
            project_id=100,
            project_root=tmp_path,
        )

        def search_read_side_effect(model, domain, fields, **kwargs):
            if model == "project.task.type":
                return [{"id": 1}]
            elif model == "project.task":
                if domain == [("project_id", "=", 100)]:
                    # Return task with parent_id that doesn't match any feature
                    return [
                        {"id": 700, "name": "Orphan Story", "parent_id": [999, "Unknown Feature"]},
                    ]
                return [{"id": 500}]
            return []

        mock_client.search_read.side_effect = search_read_side_effect

        result = engine.sync(dry_run=False)

        assert result.user_stories_imported == 0

    def test_skips_features_with_task_id_zero(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Test that features with task_id=0 are not used for parent matching."""
        toml_content = '''
[metadata]
generated_at = "2025-12-18T13:18:27"

[features."Unsynced Feature"]
description = "Not synced yet"
sequence = 1
task_id = 0
tags = "Feature"

user_stories = []
'''
        studio_dir = tmp_path / "studio"
        studio_dir.mkdir()
        toml_path = studio_dir / "feature_user_story_map.toml"
        toml_path.write_text(toml_content)

        engine = SyncEngine(
            client=mock_client,
            project_id=100,
            project_root=tmp_path,
        )

        def search_read_side_effect(model, domain, fields, **kwargs):
            if model == "project.task.type":
                return [{"id": 1}]
            elif model == "project.task":
                if domain == [("project_id", "=", 100)]:
                    # Return task - but feature has task_id=0 so won't match
                    return [
                        {"id": 600, "name": "Story", "parent_id": [0, ""]},
                    ]
            return []

        mock_client.search_read.side_effect = search_read_side_effect
        mock_client.create.return_value = 1000  # For feature task creation

        result = engine.sync(dry_run=False)

        # Feature gets created but story won't be imported (parent_id=0 won't match)
        assert result.features_created == 1
        assert result.user_stories_imported == 0

    def test_imports_multiple_stories(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Test importing multiple stories from Odoo."""
        toml_content = '''
[metadata]
generated_at = "2025-12-18T13:18:27"

[features."Feature A"]
description = "Feature A"
sequence = 1
task_id = 100
tags = "Feature"

user_stories = []

[features."Feature B"]
description = "Feature B"
sequence = 2
task_id = 200
tags = "Feature"

user_stories = []
'''
        studio_dir = tmp_path / "studio"
        studio_dir.mkdir()
        toml_path = studio_dir / "feature_user_story_map.toml"
        toml_path.write_text(toml_content)

        engine = SyncEngine(
            client=mock_client,
            project_id=100,
            project_root=tmp_path,
        )

        def search_read_side_effect(model, domain, fields, **kwargs):
            if model == "project.task.type":
                return [{"id": 1}]
            elif model == "project.task":
                if domain == [("project_id", "=", 100)]:
                    return [
                        {"id": 100, "name": "Feature A", "parent_id": False},
                        {"id": 200, "name": "Feature B", "parent_id": False},
                        {"id": 301, "name": "Story A1", "parent_id": [100, "Feature A"]},
                        {"id": 302, "name": "Story A2", "parent_id": [100, "Feature A"]},
                        {"id": 401, "name": "Story B1", "parent_id": [200, "Feature B"]},
                    ]
                # For _task_exists checks
                return [{"id": domain[0][2]}] if domain else []
            return []

        mock_client.search_read.side_effect = search_read_side_effect

        result = engine.sync(dry_run=False)

        assert result.user_stories_imported == 3

        import tomllib
        with open(toml_path, "rb") as f:
            updated_toml = tomllib.load(f)
        
        assert len(updated_toml["features"]["Feature A"]["user_stories"]) == 2
        assert len(updated_toml["features"]["Feature B"]["user_stories"]) == 1

    def test_new_story_has_correct_sequence(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Test that imported stories get correct sequence numbers."""
        toml_content = '''
[metadata]
generated_at = "2025-12-18T13:18:27"

[features."Test Feature"]
description = "Test"
sequence = 1
task_id = 500
tags = "Feature"

user_stories = [
    { name = "Existing Story 1", description = "", sequence = 1, task_id = 601, tags = "Story", components = [] },
    { name = "Existing Story 2", description = "", sequence = 2, task_id = 602, tags = "Story", components = [] },
]
'''
        studio_dir = tmp_path / "studio"
        studio_dir.mkdir()
        toml_path = studio_dir / "feature_user_story_map.toml"
        toml_path.write_text(toml_content)

        engine = SyncEngine(
            client=mock_client,
            project_id=100,
            project_root=tmp_path,
        )

        def search_read_side_effect(model, domain, fields, **kwargs):
            if model == "project.task.type":
                return [{"id": 1}]
            elif model == "project.task":
                if domain == [("project_id", "=", 100)]:
                    return [
                        {"id": 700, "name": "New Story", "parent_id": [500, "Test Feature"]},
                    ]
                # For _task_exists checks
                return [{"id": domain[0][2]}] if domain else []
            return []

        mock_client.search_read.side_effect = search_read_side_effect

        result = engine.sync(dry_run=False)

        assert result.user_stories_imported == 1

        import tomllib
        with open(toml_path, "rb") as f:
            updated_toml = tomllib.load(f)
        
        stories = updated_toml["features"]["Test Feature"]["user_stories"]
        new_story = [s for s in stories if s["task_id"] == 700][0]
        assert new_story["sequence"] == 3  # After existing 1 and 2

    def test_skips_deprecated_features_for_import(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Test that deprecated features are not matched for imports."""
        toml_content = '''
[metadata]
generated_at = "2025-12-18T13:18:27"

[features."Deprecated Feature"]
description = "Deprecated"
sequence = 1
task_id = 500
tags = "Feature"
_deprecated = true

user_stories = []
'''
        studio_dir = tmp_path / "studio"
        studio_dir.mkdir()
        toml_path = studio_dir / "feature_user_story_map.toml"
        toml_path.write_text(toml_content)

        engine = SyncEngine(
            client=mock_client,
            project_id=100,
            project_root=tmp_path,
        )

        def search_read_side_effect(model, domain, fields, **kwargs):
            if model == "project.task.type":
                return [{"id": 1}]
            elif model == "project.task":
                if domain == [("project_id", "=", 100)]:
                    return [
                        {"id": 600, "name": "Story for Deprecated", "parent_id": [500, "Deprecated Feature"]},
                    ]
                return [{"id": 500}]
            return []

        mock_client.search_read.side_effect = search_read_side_effect

        result = engine.sync(dry_run=False)

        # Should not import - feature is deprecated
        assert result.user_stories_imported == 0
