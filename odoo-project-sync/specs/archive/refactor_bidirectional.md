# Bidirectional Sync and Enrich Refactor Specification

## ⚠️ VERY IMPORTANT - IMPLEMENTATION SCOPE ⚠️

**DO NOT CREATE NEW PROCESSES**

All processes referenced in this specification are **ALREADY IMPLEMENTED** in the codebase. This specification is about:

- **REORGANIZING** existing processes
- **MINOR ALTERATIONS** to existing processes
- **REORDERING** the execution sequence

This is **NOT** about:
- Building new functionality from scratch
- Creating new modules or classes
- Implementing new features

---

## Overview

This specification outlines the refactoring of the Odoo Project Sync tool to implement bidirectional synchronization between the `feature_user_story_map.toml` file and Odoo tasks, with enrichment writing directly to Odoo task descriptions in formatted HTML. The primary goals are:

- Ensure tasks exist bidirectionally between TOML and Odoo
- Move enrichment output from TOML updates to Odoo task descriptions
- Reorder the process sequence to ensure tasks exist before enrichment
- Maintain simplicity with no backwards compatibility or performance optimizations

## Current State Analysis

### Sync Engine (`shared/python/sync_engine.py`)
- **Current Behavior**: One-way synchronization from TOML to Odoo
  - Only processes items where `task_id == 0`
  - Creates Odoo tasks for features and user stories
  - Updates TOML with newly created `task_id` values
  - No validation of existing `task_id` values against Odoo
- **Limitations**: Does not handle cases where TOML contains `task_id` values that no longer exist in Odoo

### Enricher (`shared/python/user_story_enricher.py`)
- **Current Behavior**: Updates `feature_user_story_map.toml` in-place
  - Reads from TOML using `source_location` to access source files
  - Generates AI-enriched descriptions for features and user stories
  - Writes enriched descriptions back to TOML
  - Regenerates `TODO.md` from updated TOML
- **Limitations**: Enrichment results are stored in TOML, requiring separate sync to Odoo

### Process Sequence
Current sequence (from `Odoo_Sync_HowTo.md`):
1. Extract
2. User edit `module_model_map.toml`
3. Generate Feature Map
4. User edit `feature_user_story_map.toml`
5. Generate Modules
6. Generate ToDo
7. Import & Sync
8. Enrich Stories (optional)
9. Estimate Effort (optional)
10. Enrich All (optional)

## Proposed Changes

### 1. Bidirectional Task Synchronization

#### Sync Engine Modifications
- **Validation Logic**: For each feature/user story in TOML:
  - If `task_id == 0`: Create new task in Odoo, update TOML with new `task_id`
  - If `task_id > 0`: Query Odoo to verify task exists
    - If task exists: No action needed
    - If task does not exist: Create new task in Odoo, update TOML with new `task_id`
- **Error Handling**: If task validation or creation fails, stop process and display error in big red letters
- **No Backwards Compatibility**: Existing TOML files with invalid `task_id` values will be corrected automatically

#### Task Creation Rules
- Features: Create as parent tasks
- User Stories: Create as subtasks linked to parent feature task
- All tasks placed in "Backlog" stage initially
- Tags created if they don't exist

### 2. Enrichment Output Redirection

#### Enricher Modifications
- **Output Target**: Write formatted HTML descriptions directly to Odoo task descriptions instead of updating TOML
- **HTML Formatting**: Use Odoo-compatible CSS classes and the specified layout structure
- **No TOML Updates**: Enrichment no longer modifies `feature_user_story_map.toml`
- **Prerequisites**: Tasks must exist in Odoo before enrichment (enforced by process sequence)

#### HTML Layout Structure
Use the following layout for task descriptions:

```html
<h2>📋 [Feature/User Story Name]</h2>

<blockquote>
  <strong>Business Requirement:</strong><br>
  A single paragraph describing the business value and purpose.
</blockquote>

<h3>⚙️ User Stories</h3>

<table>
  <thead>
    <tr>
      <th>Status</th>
      <th>Name</th>
      <th>Complexity</th>
      <th>Hours</th>
    </tr>
  </thead>
  <tbody>
    <!-- Component rows -->
    <tr>
      <td>✅</td>
      <td>component_name.xml</td>
      <td>Medium</td>
      <td>00:48</td>
    </tr>
    <!-- Total row -->
    <tr>
      <td></td>
      <td><strong>Total</strong></td>
      <td></td>
      <td><strong>00:30</strong></td>
    </tr>
  </tbody>
</table>

<h3>📋 [User Story Name]</h3>

<blockquote>
  <strong>Business Requirement:</strong><br>
  <strong>Who [The persona/role]:</strong> Description<br>
  <strong>What [The action or capability]:</strong> Description<br>
  <strong>Why [The business value]:</strong> Description<br>
  <strong>How (Acceptance Criteria):</strong><br>
  <ul>
    <li>Criterion 1 - specific and testable</li>
    <li>Criterion 2</li>
  </ul>
</blockquote>

<h3>⚙️ Components</h3>

<table>
  <!-- Same structure as above -->
</table>
```

#### CSS Classes
- Use standard Odoo CSS classes for styling
- Ensure tables are responsive and readable in Odoo interface
- No external CSS or images (media support not required)

#### Enrichment Failure Handling
- If HTML update fails for a task: Write "Enrichment failed" in big red letters in the task description
- Continue processing other tasks
- Report failures at the end

### 3. Process Sequence Changes

New sequence:
1. Extract
2. User edit `module_model_map.toml`
3. Generate Feature Map
4. User edit `feature_user_story_map.toml`
5. Generate Modules
6. Import & Sync (creates/updates tasks bidirectionally)
7. Enrich Stories (optional - writes to Odoo task descriptions)
8. Estimate Effort (optional - writes to Odoo task descriptions)
9. Enrich All (optional - runs both enrichment types)
10. Generate ToDo (standalone, reads from TOML for task references)

#### Key Changes
- **Import & Sync moved before enrichment**: Ensures tasks exist before enrichment attempts to write to them
- **Generate ToDo moved to end**: Now a standalone reporting step that doesn't affect Odoo state
- **Enrichment no longer updates TOML**: Only writes to Odoo tasks

### 4. Effort Estimation Integration

#### Current Behavior
- Updates TOML with complexity and time_estimate fields
- Sets enrich-status to "done"

#### Proposed Changes
- **Output Target**: Write effort estimation results to Odoo task descriptions in HTML table format
- **No TOML Updates**: Remove complexity/time_estimate updates from TOML
- **Status Tracking**: Since enrich-status is no longer needed for enrichment control, consider removing or repurposing

### 5. Command Interface Changes

#### enrich-stories Command
- **Behavior**: Generate HTML and update Odoo task descriptions
- **Prerequisites**: Valid Odoo connection and existing tasks
- **Error Handling**: Stop on critical failures, continue on individual task failures

#### sync Command
- **Behavior**: Ensure bidirectional task existence
- **Validation**: Check existing task_ids against Odoo
- **Creation**: Create missing tasks and update TOML

#### generate-todo Command
- **Behavior**: Unchanged - generates TODO.md from TOML
- **Independence**: No longer affected by enrichment status

### 6. Error Handling and User Feedback

#### Principles
- **Simple Error Handling**: If something fails, stop and tell the user in big red letters
- **No Recovery**: No automatic retry or complex conflict resolution
- **Clear Messaging**: Use terminal colors and prominent text for errors
- **No Performance Concerns**: No optimizations needed for large projects

#### Specific Scenarios
- **Sync Failures**: If task creation/validation fails, abort entire sync
- **Enrichment Failures**: Continue with other tasks, mark failed tasks with error message
- **Connection Issues**: Fail fast with clear error message
- **TOML Parsing Errors**: Fail with descriptive error

### 7. Data Integrity

#### TOML as Source of Truth
- TOML remains the authoritative source for feature/user story definitions
- Odoo tasks are projections of TOML data
- Task descriptions in Odoo are enhanced views, not authoritative

#### Task ID Management
- TOML task_ids are validated against Odoo on each sync
- Invalid task_ids trigger recreation
- No merging or conflict resolution - recreate on mismatch

### 8. Testing and Validation

#### Unit Tests
- Update existing tests for sync engine bidirectional logic
- Add tests for enricher HTML output to Odoo
- Test error scenarios and failure handling

#### Integration Tests
- End-to-end workflow testing with mock Odoo
- Validate HTML formatting in task descriptions
- Test task recreation on invalid task_ids

## Implementation Considerations

### Dependencies
- No new dependencies required
- Leverage existing OdooClient for task operations
- Reuse existing AI providers for enrichment

### Migration
- **No Backwards Compatibility**: Existing enriched TOML files will be ignored for enrichment
- **Clean State**: Recommend re-running sync after refactor to ensure task validity
- **Data Preservation**: Odoo task descriptions will be overwritten on re-enrichment

### Future Extensions
- Bidirectional content sync (TOML ↔ Odoo descriptions)
- Conflict resolution strategies
- Incremental updates
- Performance optimizations for large projects

## Open Questions

1. **Task ID Validation Details**: Should sync query Odoo for every task_id > 0, or cache results? (Recommendation: Query each time for simplicity)

2. **Enrich Status Field**: Since enrich-status is no longer needed for enrichment control, should it be removed from TOML schema?

3. **HTML Update Strategy**: Should enrichment append to existing descriptions or replace them entirely?

4. **User Story Enrichment Scope**: Should enrichment update both feature and user story tasks, or only user story tasks?

5. **Error Recovery**: For failed task creations during sync, should we rollback successful creations or leave them?

Please provide clarification on these points to finalize the specification.