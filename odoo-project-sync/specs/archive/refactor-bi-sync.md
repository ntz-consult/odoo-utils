# Refactor Bidirectional Syncing to Odoo - Specification and Plan

## Purpose

This specification outlines the refactoring of the bidirectional syncing mechanism between the local feature user story map and Odoo tasks. The goal is to simplify and focus the sync logic to only handle the creation of new stories in the feature user story map when corresponding tasks exist in Odoo under existing features, while removing all other bidirectional synchronization logic.

## Scope

- Analysis and refactoring of bidirectional sync logic
- Implementation of targeted sync rules for Odoo task integration
- Removal of extraneous bidirectional synchronization features
- Documentation of the refactored specification and implementation plan
- Identification of potential source files involved in the changes

## Inputs

- Current bidirectional sync implementation
- Odoo task data with task_id and parent_id attributes
- Local feature_user_story_map.toml file containing features with task_id values
- Existing sync engine and related components

## Outputs

- Refactored bidirectional sync logic with simplified rules
- Updated feature_user_story_map.toml with newly created stories from Odoo tasks
- Cleaned codebase with removed unnecessary bidirectional logic
- Comprehensive list of potential source files requiring modification

## Process Steps

### 1. Analysis Phase

- Review current bidirectional sync implementation
- Identify all existing bidirectional logic components
- Document current sync behavior and edge cases
- Validate understanding of Odoo task structure (task_id, parent_id)

### 2. Design Phase

- Define simplified sync rules:
  - On each sync run, identify Odoo tasks not represented by task_id in feature_user_story_map.toml
  - For unmatched Odoo tasks:
    - If no parent_id: ignore completely
    - If parent_id matches a feature's task_id in the map: create as a new story within that feature
- Specify that new stories will initially have no components
- Confirm removal of all other bidirectional logic

### 3. Implementation Planning

- Identify code locations requiring changes
- Plan modifications to sync engine
- Design updates to feature user story map handling
- Prepare removal of obsolete bidirectional features

### 4. Implementation Steps

1. Modify sync engine to query Odoo for all tasks
2. Compare Odoo task_ids against feature_user_story_map.toml task_ids
3. Filter tasks: ignore those without parent_id
4. For tasks with parent_id, check if parent_id matches any feature task_id
5. Create new story entries in feature_user_story_map.toml for matching tasks
6. Remove all other bidirectional sync logic from the codebase
7. Update any related components to reflect simplified sync behavior

### 5. Testing and Validation

- Test sync with various Odoo task scenarios
- Verify ignored tasks are properly filtered
- Confirm new stories are created correctly in the map
- Ensure no regressions in existing sync functionality
- Validate removal of obsolete logic

## Potential Source Files Involved

Based on the workspace structure and sync requirements, the following files are likely to be involved in implementing this specification:

- `shared/python/sync_engine.py` - Core sync logic and engine
- `shared/python/feature_user_story_map_generator.py` - Generation and management of feature user story maps
- `shared/python/feature_user_story_mapper.py` - Mapping logic between features and stories
- `shared/python/odoo_client.py` - Odoo API client for task retrieval
- `shared/python/cli.py` - Command-line interface that may trigger sync operations
- `studio/feature_user_story_map.toml` - Target file for story creation
- `shared/python/change_detector.py` - May need updates for change detection logic
- `shared/python/task_manager.py` - Task management components
- `tests/test_sync_engine.py` - Sync engine tests requiring updates
- `tests/test_feature_user_story_map_generator.py` - Tests for map generation

## Clarifications (Resolved)

The following clarifications were obtained during implementation:

1. **New Story Structure**: New stories created from Odoo tasks will have only:
   - `name` (from Odoo task name)
   - `task_id` (from Odoo task id)
   - Default/empty values for other fields (`components = []`, `sequence`, `tags`, etc.)

2. **Existing TOML → Odoo Logic**: The existing sync logic (creating Odoo tasks from TOML, validation, recreation) is **preserved unchanged**. The new Odoo → TOML sync runs **after** the existing logic completes.

3. **Sync Flow**:
   - Step 1: Run existing TOML → Odoo sync (creates tasks, validates, recreates)
   - Step 2: Run new Odoo → TOML sync (imports new stories from Odoo)

4. **Project Scope**: Query all tasks in the configured `project_id`

5. **Duplicate Prevention**: Tasks already represented in TOML (by `task_id`) are skipped

6. **Feature Matching**: Only features with `task_id > 0` can be matched as parents

## Constraints

- Existing TOML → Odoo synchronization logic must be preserved unchanged
- New Odoo → TOML sync runs after the existing sync completes
- New stories created from Odoo tasks shall initially have only `name` and `task_id`
- Only Odoo tasks with a `parent_id` matching a feature's `task_id` (where `task_id > 0`) are imported
- Tasks without `parent_id` are ignored
- Tasks already in TOML (matched by `task_id`) are skipped
- Sync must run efficiently without unnecessary operations

## Success Criteria

- Existing TOML → Odoo sync continues to work unchanged
- New Odoo → TOML sync correctly identifies Odoo tasks with `parent_id`
- Tasks without `parent_id` are completely ignored
- Tasks with `parent_id` matching a feature's `task_id` are created as new stories
- Tasks already represented in TOML are not duplicated
- feature_user_story_map.toml is updated correctly with new stories
- SyncResult includes count of stories imported from Odoo


