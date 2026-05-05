# Enrich-Status Feature Specification

**Created:** 2025-12-19
**Purpose:** Add enrich-status control to feature_user_story_map.toml for selective enrichment

---

## Overview

Add a new `enrich-status` node to both features and user stories in `feature_user_story_map.toml` to control which enrichment operations should be performed.

## Breaking Changes

### Removal of `detected_by` Node

- The `detected_by` field is removed from `feature_user_story_map.toml` structure
- All references to `detected_by` in the codebase are removed
- Existing TOML files with `detected_by` will be automatically cleaned during processing

### Removal of `--force-reenrich` CLI Option

- The `--force-reenrich` command-line flag is completely removed
- Enrichment operations now rely solely on `enrich-status` values in the TOML file
- Users must manually edit the TOML to re-trigger enrichment

## Requirements

### New Node: enrich-status

- **Location**: Both feature level and user story level
- **Default Value**: `"refresh-all"`
- **Valid Values**:
  - `"refresh-all"`: Both enrich-stories and estimate-effort can run
  - `"refresh-effort"`: Only estimate-effort can run
  - `"refresh-stories"`: Only enrich-stories can run
  - `"done"`: No enrichment operations should run

### New Node: task_id

- **Location**: Both feature level and user story level
- **Default Value**: `0`
- **Purpose**: Unique identifier for tracking and linking to external task management systems

### New Node: tags

- **Location**: Both feature level and user story level
- **Default Value**: `""` (empty string)
- **Purpose**: Categorization and filtering tags for organization and reporting

### Behavior Rules

#### Status Evaluation

- **Feature Level**: Controls enrichment for feature description only
- **User Story Level**: Independent control per user story
- **Interaction**: User story status is checked separately for each story

#### Enrichment Operations

- **enrich-stories**: Updates user story descriptions with AI-generated content (Who/What/Why/How format)
- **estimate-effort**: Calculates complexity and time estimates for components

#### Status Updates

- After any enrichment operation runs, status is set to `"done"`
- Feature and user story statuses are updated independently
- Status becomes `"done"` regardless of which operation ran (even if only one of multiple operations completed)

### Implementation Details

#### TOML Structure

```toml
[features."Feature Name"]
description = "Feature description"
sequence = 1
enrich-status = "refresh-all"  # NEW
task_id = 0  # NEW
tags = "Feature"  # NEW

user_stories = [
    { name = "Story Name", description = "User story description", sequence = 1, enrich-status = "refresh-all", task_id = 0, tags = "Story", components = [...] }  # NEW
]
```

#### Backward Compatibility

- **Missing enrich-status**: Defaults to `"refresh-all"` (backward compatible)
- **Existing TOML files**: No migration required, defaults apply

#### Initial Generation

- When `feature_user_story_map.toml` is first generated, include `enrich-status = "refresh-all"` by default
- This ensures new files are ready for enrichment
- Set `task_id = 0` for both features and user stories
- Set `tags = "Feature"` for features and `tags = "Story"` for user stories

#### Re-triggering Enrichment

- **Manual**: User edits TOML to change status back from `"done"` to desired refresh mode

### Enricher Behavior

#### enrich_in_place() Method

- Checks status before each sub-enricher
- Respects the specific permissions per status value
- Runs appropriate sub-enrichers based on status

#### Status Transitions

- `"refresh-all"` → `"done"` (after any enrichment runs)
- `"refresh-effort"` → `"done"` (after effort estimation runs)
- `"refresh-stories"` → `"done"` (after story enrichment runs)
- `"done"` → No operations run

### Example Scenarios

#### Scenario 1: New Feature

```toml
[features."New Sales Feature"]
description = "New sales functionality"
enrich-status = "refresh-all"  # Default for new features
task_id = 0
tags = "Feature"

user_stories = [
    { name = "Custom Fields", description = "Basic description", enrich-status = "refresh-all", task_id = 0, tags = "Story", components = [...] }
]
```

#### Scenario 2: Partially Enriched Feature

```toml
[features."Existing Feature"]
description = "AI-enriched description"
enrich-status = "done"  # Stories enriched, effort estimated
task_id = 0
tags = "Feature"

user_stories = [
    { name = "Story 1", description = "AI-enriched Who/What/Why/How description", enrich-status = "done", task_id = 0, tags = "Story", components = [...] },
    { name = "Story 2", description = "Basic description", enrich-status = "refresh-stories", task_id = 0, tags = "Story", components = [...] }  # Only needs story enrichment
]
```

### Implementation Checklist

- [ ] Add `enrich-status` to feature level in TOML generation
- [ ] Add `enrich-status` to user story level in TOML generation
- [ ] Add `task_id` to feature level in TOML generation (default: 0)
- [ ] Add `task_id` to user story level in TOML generation (default: 0)
- [ ] Add `tags` to feature level in TOML generation (default: "Feature")
- [ ] Add `tags` to user story level in TOML generation (default: "Story")
- [ ] Update enrichers to check and respect `enrich-status`
- [ ] Update enrichers to set status to `"done"` after operations
- [ ] Add backward compatibility (default to `"refresh-all"`)
- [ ] Update CLI help and documentation
- [ ] Add unit tests for status evaluation logic
- [ ] Test partial enrichment scenarios
- [ ] Remove `detected_by` node from TOML generation and processing
- [ ] Remove all `detected_by` references from codebase
- [ ] Remove `--force-reenrich` CLI option completely


