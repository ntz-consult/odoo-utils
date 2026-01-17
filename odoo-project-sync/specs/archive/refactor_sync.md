# Sync Engine Specification

## Overview

The Sync Engine is a **single-purpose** component responsible for synchronizing project features and user stories from the local `feature_user_story_map.toml` file to Odoo tasks. It operates as a one-way synchronization tool focused exclusively on task creation in Odoo.

Features are created as top-level Odoo tasks, while user stories are created as subtasks linked to their parent feature tasks.

Bidirectional synchronization (e.g., pulling changes from Odoo back to the TOML file) is planned for future implementation but is currently out of scope.

---

## CRITICAL SCOPE BOUNDARIES

> **⚠️ THE SYNC ENGINE HAS STRICT BOUNDARIES. READ THIS SECTION CAREFULLY.**

### The Sync Engine MUST ONLY:

1. **Read from `feature_user_story_map.toml`** — This is the SOLE input file
2. **Write to `feature_user_story_map.toml`** — Only to update `task_id` fields after Odoo task creation
3. **Connect to Odoo** — To create tasks and subtasks
4. **Return task IDs** — From newly created Odoo tasks

### The Sync Engine MUST NOT:

| Prohibited Action | Reason |
|-------------------|--------|
| **Access extracted JSON files** | JSON extraction is a separate upstream process |
| **Perform TODO generation** | TODO generation is a standalone downstream process |
| **Perform enrichment** | Enrichment is a standalone process with its own workflow |
| **Read/write any file other than `feature_user_story_map.toml`** | Out of scope |
| **Perform change detection** | Out of scope for this component |
| **Perform conflict resolution** | Out of scope for this component |
| **Update existing Odoo tasks** | Only creates new tasks |
| **Delete Odoo tasks** | Out of scope |
| **Generate reports or logs** | Out of scope |

### Process Isolation

The sync process is **completely isolated** from other processes:

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│   EXTRACTION        │     │   SYNC ENGINE       │     │   TODO GENERATION   │
│   (Separate)        │     │   (This Spec)       │     │   (Separate)        │
│                     │     │                     │     │                     │
│ - Reads Odoo        │     │ - Reads TOML only   │     │ - Reads TOML        │
│ - Writes JSON       │ ──► │ - Writes TOML only  │ ──► │ - Generates TODOs   │
│ - Not sync's job    │     │ - Creates Odoo tasks│     │ - Not sync's job    │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘

┌─────────────────────┐
│   ENRICHMENT        │
│   (Separate)        │
│                     │
│ - Enriches stories  │
│ - Not sync's job    │
└─────────────────────┘
```

---

## Purpose

- **Primary Goal**: Create Odoo tasks for features and subtasks for user stories based on `feature_user_story_map.toml`, processing only items where `task_id == 0`.
- **Single Responsibility**: The engine performs ONLY Odoo task creation and TOML `task_id` updates. Nothing else.

---

## Inputs

### Single Input: `feature_user_story_map.toml`

This is the **ONLY** input file. The sync engine reads no other files.

**TOML Structure Example** (from actual `feature_user_story_map.toml`):

```toml
[features."Customer Product Information"]
description = "This feature allows customers to maintain their own product codes, names, and barcodes associated with the products they purchase from the company."
sequence = 1
enrich-status = "refresh-all"    # Ignored by sync
task_id = 0                       # 0 = needs sync, >0 = already synced
tags = "Feature"

user_stories = [
    { 
        name = "Maintain product information for Customer", 
        description = "As a sales representative, I want to view and maintain customer-specific product codes...", 
        sequence = 1, 
        enrich-status = "done",   # Ignored by sync
        task_id = 0,              # 0 = needs sync, >0 = already synced
        tags = "Story",
        components = [            # Ignored by sync (TODO generation uses this)
            { ref = "field.res_partner.x_customer_procuct_codes", ... },
        ]
    },
]
```

### Task Field Mapping

**Feature → Odoo Task:**

| TOML Source | Odoo Task Field | Notes |
|-------------|-----------------|-------|
| Feature name (table key) | `name` | e.g., `"Customer Product Information"` |
| `description` | `description` | Full text description |
| `tags` | `tag_ids` | Created if missing (see Tag Handling) |
| - | `project_id` | From configuration |
| - | `stage_id` | "Backlog" stage (see Stage Management) |

**User Story → Odoo Subtask:**

| TOML Source | Odoo Subtask Field | Notes |
|-------------|-------------------|-------|
| `name` | `name` | e.g., `"Maintain product information for Customer"` |
| `description` | `description` | Full text description |
| `tags` | `tag_ids` | Created if missing |
| - | `project_id` | From configuration |
| - | `parent_id` | Links to parent feature task |
| - | `stage_id` | "Backlog" stage |

**Fields Ignored by Sync** (preserved in TOML but not sent to Odoo):

| Field | Reason |
|-------|--------|
| `sequence` | Ordering is handled separately |
| `enrich-status` | Enrichment is a separate process |
| `components` | TODO generation uses this, not sync |

### Odoo Connection

Provided via configuration (URL, credentials). Assumed pre-configured.

---

## Outputs

### Single Output: Updated `feature_user_story_map.toml`

The **ONLY** file modification is updating `task_id` fields in the input TOML file.

**Before sync:**
```toml
task_id = 0
```

**After sync:**
```toml
task_id = 12345  # Odoo task ID
```

### Odoo Side Effects

- Features → Created as Odoo tasks
- User Stories → Created as Odoo subtasks with `parent_id` referencing the feature task

### No Other Outputs

- ❌ No JSON files
- ❌ No TODO files
- ❌ No enrichment files
- ❌ No logs
- ❌ No reports

---

## Behavior

### Core Synchronization Logic

1. **Parse TOML**: Read `feature_user_story_map.toml`
2. **Iterate Features**:
   - For each feature where `task_id == 0`:
     - Create Odoo task (`name`, `description`, `tags`)
     - Update TOML with new `task_id`
3. **Iterate User Stories**:
   - For each user story where `task_id == 0`:
     - Create Odoo subtask (`name`, `description`, `tags`, `parent_id`)
     - Update TOML with new `task_id`
4. **Write TOML**: Save updated file

### Dry Run Mode

- Validates Odoo connectivity only
- No tasks created
- No TOML modifications

### Error Handling

- **Fail Fast**: Stop immediately on any error
- **No Rollback**: Partial progress is preserved in TOML
- **Clear Messages**: Raise exceptions with descriptive errors

---

## Bidirectional Synchronization (Future/Stub)

- **Current Status**: Not implemented
- **Planned**: Detect Odoo changes and update TOML
- **Implementation**: Placeholder stubs for future expansion

---

## Interfaces

```python
class SyncEngine:
    def sync(dry_run: bool = False) -> None:
        """
        Synchronize feature_user_story_map.toml to Odoo.
        
        ONLY reads/writes feature_user_story_map.toml.
        ONLY creates Odoo tasks.
        
        Does NOT:
        - Access JSON files
        - Generate TODOs
        - Perform enrichment
        """
        pass
```

### Dependencies

- Odoo API client (task creation only)
- TOML parser/writer

---

## Assumptions and Constraints

- Odoo supports subtasks via `parent_id`
- TOML file is well-formed and accessible
- No concurrent modifications during sync
- Task creation failures halt the process

---

## Stage Management

The Sync Engine manages Odoo project stages to ensure new tasks are properly categorized.

### Default Stages

| Stage Name | Sequence | Purpose |
|------------|----------|--------|
| Backlog | 1 | **Default for new tasks** |
| Up Next | 2 | Tasks ready to start |
| In Progress | 3 | Active work |
| User Acceptance | 4 | Testing/review |
| Done | 5 | Completed |
| Archive | 6 | Archived tasks |

### Stage Behavior

- All new tasks are assigned to the **"Backlog"** stage
- If the Backlog stage doesn't exist for the project, it is **created automatically**
- Stage IDs are cached to avoid repeated Odoo lookups
- The `ensure_stages()` method can create all stages if needed

---

## Tag Handling

Tags provide categorization for tasks in Odoo.

### Tag Processing

1. Tags are parsed from the TOML `tags` field (comma-separated string)
2. Each tag is looked up in Odoo by exact name match
3. **If a tag doesn't exist, it is created automatically**
4. Tag IDs are cached to avoid repeated lookups

### Tag Sources

- **Only tags defined in the TOML are used**
- No external tag sources are consulted
- Common tags: `"Feature"`, `"Story"`

### Example

```toml
# TOML
tags = "Feature"

# Results in Odoo:
# - Looks for tag named "Feature"
# - If not found, creates it
# - Associates tag with the task
```

---

## Edge Cases

| Case | Behavior |
|------|----------|
| Empty TOML | No operations |
| All `task_id != 0` | No operations (everything already synced) |
| Missing tags | Created automatically in Odoo |
| Missing Backlog stage | Created automatically for project |
| Tag creation fails | Silently skipped, task created without that tag |
| Odoo API limits | Respect rate limits |
| File locked | Fail with error |

---

## Testing Considerations

- Unit tests for TOML parsing
- Mocked Odoo API tests
- Dry run validation
- Error scenario coverage

---

## Summary

**The Sync Engine does ONE thing:**

> Read `feature_user_story_map.toml` → Create Odoo tasks → Write `task_id` back to TOML

**It does NOT do anything else. Period.**

