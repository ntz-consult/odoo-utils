# Specification and Plan for Implementation Overview Task Creation

## Purpose

Automate the creation or update of an "Implementation Overview" task in Odoo during the execution of the `cli.py estimate-effort --execute` command. This task will summarize all components involved in the sync operation through structured tables.

## Scope

- Automate task creation or update in Odoo.
- Generate two tables summarizing component data:
  - **Component Type Summary**: Aggregated data by type.
  - **Detailed Component List**: Detailed data for each component type.
- Ensure idempotency, performance, and robust error handling.

## Inputs

- Component data in feature_user_story_map.toml from the `estimate-effort` process.
- Odoo project API for task management.

## Outputs

- An "Implementation Overview" task in Odoo with:
  - **Table 1**: Component Type Summary (e.g., type, quantity, total time).
  - **Table 2**: Detailed Component List (e.g., ref, complexity, time estimate).

## Requirements

### Functional Requirements

1. **Trigger Mechanism**: Automatically create/update the task during `cli.py estimate-effort --execute`.
2. **Task Details**:
   - **Name**: "Implementation Overview"
   - **Description**: Two tables summarizing component data.
3. **Table 1: Component Type Summary**:
   - Columns: `type`, `Quantity`, `Total Time`.
   - Includes a totals row.
4. **Table 2: Detailed Component List**:
   - Columns: `ref`, `complexity`, `time_estimate`.
   - Sorted by `time_estimate` (descending).
   - One table per component type.

### Non-Functional Requirements

1. **Idempotency**: Update existing tasks instead of creating duplicates.
2. **Performance**: Minimal impact on execution time.
3. **Error Handling**: Log failures without interrupting the sync process.

## Implementation Plan

### Phase 1: Analysis and Design ✅

1. Review `cli.py` structure and `estimate-effort` command flow.
2. Identify data aggregation points.
3. Design table generation logic.
4. Plan Odoo client integration.

### Phase 2: Development Preparation ✅

1. Define data structures for summaries and detailed lists.
2. Create utility functions for Markdown table formatting.
3. Ensure access to Odoo project details.

### Phase 3: Integration and Testing ✅

1. Modify `cli.py` to trigger task creation/update.
2. Implement task existence checks and update logic.
3. Add logging for task operations.
4. Test with sample data to verify accuracy and integration.

### Phase 4: Validation and Documentation ✅

1. Validate against acceptance criteria.
2. Update documentation (e.g., CLI usage, Odoo integration notes).
3. Ensure no regressions in existing functionality.

## Implementation Summary

### Files Created/Modified

1. **Created: `shared/python/implementation_overview_generator.py`**
   - New module for generating HTML tables from TOML data
   - `ImplementationOverviewGenerator` class with methods:
     - `load_and_analyze()`: Parse TOML and collect component data
     - `generate_component_type_summary_table()`: Create Table 1 (aggregated summary)
     - `generate_detailed_component_tables()`: Create Table 2 (detailed lists by type)
     - `generate_full_html()`: Generate complete HTML description
   - Handles time format conversion (HH:MM)
   - Applies color coding for complexity levels
   - Groups components by type with proper display names

2. **Modified: `shared/python/task_manager.py`**
   - Added `find_task_by_name()` method to search for existing tasks by name
   - Enables idempotent task creation/update

3. **Modified: `shared/python/cli.py`**
   - Imported `ImplementationOverviewGenerator`
   - Updated `cmd_estimate_effort()` method to:
     - Generate HTML overview after successful effort estimation
     - Create or update "Implementation Overview" task in Odoo
     - Handle errors with critical failure (fails entire command)
   - Added `_create_implementation_overview_task()` helper method:
     - Loads Odoo configuration
     - Creates OdooClient and TaskManager
     - Generates HTML from TOML
     - Searches for existing task by name
     - Creates new task or updates existing task
     - Places task in "Done" stage with "Stats" tag

4. **Created: `tests/test_implementation_overview_generator.py`**
   - Comprehensive unit tests for the generator
   - Tests for HTML generation, time parsing/formatting, component type extraction
   - Tests for complexity color coding and edge cases
   - All tests pass ✅

### Implementation Details

**Task Configuration:**
- **Name**: "Implementation Overview" (fixed, for idempotency)
- **Stage**: Done
- **Tags**: ["Stats"]
- **Description**: Nicely formatted HTML with two table sections

**Table 1 Format (Component Type Summary):**
```html
<h2>Component Type Summary</h2>
<table>
  <thead>
    <tr>
      <th>Type</th>
      <th>Quantity</th>
      <th>Total Time</th>
    </tr>
  </thead>
  <tbody>
    <tr><td>Fields</td><td>10</td><td>12:30</td></tr>
    ...
    <tr><td>TOTAL</td><td>50</td><td>75:30</td></tr>
  </tbody>
</table>
```

**Table 2 Format (Detailed Component Lists):**
- Multiple tables grouped by component type
- Each table sorted by time_estimate (descending)
- Color-coded complexity column
- Format:
```html
<h3>Fields</h3>
<table>
  <thead>
    <tr>
      <th>Ref</th>
      <th>Complexity</th>
      <th>Time Estimate</th>
      <th>Completion</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>field.sale_order.x_custom</td>
      <td style="background-color: #d4edda;">simple</td>
      <td>01:30</td>
      <td>100%</td>
    </tr>
    ...
  </tbody>
</table>
```

**Data Inclusion:**
- Includes ALL components from TOML (including 100% complete)
- Summarizes data from all features and user stories
- Time format: HH:MM (e.g., "01:30", "10:00")

**Error Handling:**
- If task creation/update fails, the entire `estimate-effort` command fails
- Error message displayed in red/bold format
- Debug mode shows full stack trace

**Idempotency:**
- Searches for existing task by name using `find_task_by_name()`
- Updates existing task if found
- Creates new task only if none exists

## Acceptance Criteria

✅ Task is created/updated in Odoo after each `cli.py estimate-effort --execute` run.
✅ Task description includes accurate tables.
✅ Tables are correctly sorted and totaled.
✅ Process completes without errors, with fallback logging for failures.
✅ Task is in "Done" stage with "Stats" tag.
✅ HTML is nicely formatted with proper styling.
✅ Time format is HH:MM.
✅ Tables are grouped by component type.
✅ All components (including 100% complete) are included.
✅ Critical error handling fails the entire command.

## Risks and Mitigations

1. **Odoo API changes or connectivity issues**:
   - Mitigation: ✅ Implemented robust error handling and critical failure logging.
2. **Data aggregation inaccuracies**:
   - Mitigation: ✅ Validated data sources and added comprehensive unit tests.
3. **Performance overhead**:
   - Mitigation: ✅ Efficient data collection and HTML generation. Minimal impact on execution time.

## Dependencies

✅ Access to Odoo project API.
✅ Existing component data collection in `estimate-effort` process.
✅ HTML table generation capabilities.
✅ TaskManager integration for Odoo task operations.
