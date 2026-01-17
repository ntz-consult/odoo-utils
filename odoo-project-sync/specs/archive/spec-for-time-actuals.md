# Time Actuals Enhancement Specification and Plan

## Purpose

Enhance the user story enricher to display both estimated and actual time tracking data in the HTML tables generated for Odoo task descriptions. This will provide visibility into both planned effort (estimates) and actual time spent (from Odoo timesheets) at both the feature and user story levels.

## Scope

### In Scope
- Modify HTML table generation for feature-level user story summary tables
- Modify HTML table generation for story-level component tables
- Fetch actual time data from Odoo timesheets (validated timesheets only)
- Display estimate vs. actual time comparison in Odoo task descriptions
- Add feature-level time tracking row
- Rename "Hours" column to "Estimate" and add "Actual" column
- Update total rows to distinguish between "Total Estimate" and "Total Actual"

### Out of Scope
- Modification of TOML file structure
- Changes to time estimation algorithms
- Timesheet creation or modification
- Reporting on non-validated timesheets
- Changes to TODO.md generation
- CLI interface modifications

## Inputs

- **Feature User Story Map TOML**: `studio/feature_user_story_map.toml`
  - Contains task_id for features and user stories
  - Contains time_estimate for components
  
- **Odoo Timesheets**: From `account.analytic.line` model
  - Filter: `validated = True`
  - Link: Via `task_id` field to project.task
  - Field: `unit_amount` (hours)

- **Odoo Configuration**: Instance configuration from `.odoo-sync/config/odoo-instances.json`

## Outputs

- **Modified HTML tables in Odoo task descriptions**:
  - Feature tasks: Enhanced user story summary table with Estimate and Actual columns
  - Story tasks: Enhanced component table with "Total Estimate" and "Total Actual" rows

## Process Steps

### 1. Analysis Phase

**Tasks:**
- ✓ Review current HTML table generation in `OdooHtmlGenerator` class
- ✓ Identify timesheet model and fields in Odoo
- ✓ Understand current table structure for features and stories
- ✓ Confirm OdooClient capabilities for fetching timesheets

**Key Files:**
- `shared/python/user_story_enricher.py` (lines 796-970)
- `shared/python/odoo_client.py`

### 2. Timesheet Data Fetching

**Implementation:**
- Add method to `OdooClient` or `UserStoryEnricher` to fetch timesheets
- Method signature: `fetch_task_timesheets(task_id: int, validated_only: bool = True) -> float`
- Use `search_read` on `account.analytic.line` model
- Domain: `[('task_id', '=', task_id), ('validated', '=', True)]`
- Sum `unit_amount` field values

### 3. Feature-Level Table Modification

**Current Structure (in `_generate_stories_table` method):**
```
Status | Name | Complexity | Hours
```

**New Structure:**
```
Status | Name | Complexity | Estimate | Actual
```

**Changes Required:**
- Rename "Hours" column header to "Estimate"
- Add "Actual" column header
- For each user story row:
  - Keep estimate calculation (sum of component time_estimate)
  - Add actual hours from Odoo timesheets for story task_id
- After Total row, add:
  - New row: "Time at feature level"
  - Style: Same as data rows
  - Only "Actual" column filled (from feature task timesheets)
  - Estimate columns empty

**Method to modify:** `OdooHtmlGenerator._generate_stories_table()`
**Location:** `shared/python/user_story_enricher.py:796-855`

### 4. Story-Level Table Modification

**Current Structure (in `_generate_components_table` method):**
```
Status | Component | Complexity | Hours
(...)
Total | - | - | [total_time]
```

**New Structure:**
```
Status | Component | Complexity | Estimate
(...)
Total Estimate | - | - | [total_estimate]
Total Actual | - | - | [total_actual]
```

**Changes Required:**
- Rename "Hours" column header to "Estimate"
- Update Total row text to "Total Estimate"
- Add new row after Total:
  - Text: "Total Actual"
  - Style: Same as header row (`tr_header` style)
  - Value: Sum of all validated timesheets for the story task

**Method to modify:** `OdooHtmlGenerator._generate_components_table()`
**Location:** `shared/python/user_story_enricher.py:867-935`

### 5. Integration with Enrichment Flow

**Modify `enrich_stories_in_place` method:**
- Pass `odoo_client` to HTML generation methods
- Fetch and aggregate timesheet data before HTML generation
- Store timesheet data in memory for efficient access during HTML generation

**Flow:**
1. When processing each feature/story
2. Fetch timesheets for feature task_id and all story task_ids
3. Pass timesheet data to `generate_feature_html()` and `generate_user_story_html()`
4. HTML generators use timesheet data to populate Actual columns

### 6. Error Handling

**Scenarios to handle:**
- Task has no task_id (cannot fetch timesheets)
- Odoo API timeout or failure
- Missing or inaccessible timesheet data
- Timesheet model not available in Odoo instance

**Strategy:**
- Display "N/A" or "0:00" for Actual when timesheet fetch fails
- Log warnings for API errors
- Continue enrichment process even if timesheet fetch fails
- Add error messages to enrichment result dictionary

### 7. Testing

**Unit Tests to add/modify:**
- `test_generate_stories_table_with_actuals()` - Test feature table with actual hours
- `test_generate_components_table_with_actuals()` - Test story table with actual hours
- `test_timesheet_fetch()` - Test timesheet data retrieval
- `test_timesheet_fetch_failure()` - Test graceful handling of fetch failures
- `test_feature_level_time_row()` - Test "Time at feature level" row generation

**File:** `tests/test_user_story_enricher.py`

### 8. Documentation

**Updates needed:**
- Update method docstrings in `OdooHtmlGenerator`
- Add inline comments explaining timesheet aggregation
- Update any relevant specification documents
- Add example screenshots or HTML output samples

## Constraints

### Technical Constraints
- Must maintain backward compatibility with existing TOML structure
- Must not break existing enrichment workflows
- HTML must render correctly in Odoo task description field
- API calls to Odoo must be efficient (minimize requests)
- Must handle both dict and list formats for user stories (legacy support)

### Data Constraints
- Only validated timesheets (`validated = True`) should be included
- Timesheet data is read-only (no modifications)
- Task_id must exist to fetch timesheets (graceful degradation if missing)

### Performance Constraints
- Batch timesheet fetches where possible
- Cache timesheet data per enrichment run
- Avoid N+1 query problems

## Success Criteria

1. ✅ Feature-level tables display both "Estimate" and "Actual" columns
2. ✅ Story-level tables show "Total Estimate" and "Total Actual" rows
3. ✅ "Time at feature level" row appears in feature tables with actual hours from feature task timesheets
4. ✅ All actual time values correctly sum validated timesheets from Odoo
5. ✅ Tables render correctly in Odoo task descriptions
6. ✅ Enrichment process handles missing or failed timesheet fetches gracefully
7. ✅ Existing tests pass and new tests validate timesheet integration
8. ✅ HTML styling is consistent with existing table styles
9. ✅ No performance degradation in enrichment process
10. ✅ Code follows existing patterns and style conventions

## Potential Source Files Involved

### Primary Implementation Files
1. **`shared/python/user_story_enricher.py`** (Lines 796-970, 1130-1400)
   - `OdooHtmlGenerator` class
   - `_generate_stories_table()` method (feature-level table)
   - `_generate_components_table()` method (story-level table)
   - `generate_feature_html()` method
   - `generate_user_story_html()` method
   - `UserStoryEnricher.enrich_stories_in_place()` method

2. **`shared/python/odoo_client.py`** (Lines 1-414)
   - May need to add timesheet-specific fetch method
   - Or utilize existing `search_read()` method

### Testing Files
3. **`tests/test_user_story_enricher.py`** (Lines 440+)
   - `TestOdooHtmlGenerator` class
   - Add tests for actual time integration

### Configuration Files
4. **`.odoo-sync/config/odoo-instances.json`**
   - Odoo connection configuration (no changes needed)

### Reference/Documentation Files
5. **`specs/done/enrich_refactor.md`**
   - Reference for enrichment process flow
   - Context for in-place enrichment

6. **`studio/feature_user_story_map.toml`**
   - Data source for task_id values
   - No structural changes required

## Implementation Notes

### Odoo Timesheet Model
- **Model name**: `account.analytic.line`
- **Key fields**:
  - `task_id`: Reference to project.task (many2one)
  - `unit_amount`: Hours spent (float)
  - `validated`: Boolean flag
  - `date`: Date of timesheet entry
  - `employee_id`: Employee who logged time
  - `name`: Description of work

### Time Format
- **Estimate format**: "H:MM" (e.g., "2:30", "8:00", "16:45")
- **Display format**: "HH:MM" (e.g., "02:30", "08:00", "16:45")
- **Internal format**: Float hours for calculations

### HTML Styling
- Use existing `STYLES` dictionary from `OdooHtmlGenerator`
- Maintain consistency with current table styling
- "Total Actual" row should use `tr_header` style
- "Time at feature level" row should use regular `tr` style

## Assumptions

1. Timesheet model (`account.analytic.line`) is available in all target Odoo instances
2. Task IDs in TOML correspond to valid project.task records in Odoo
3. Validated timesheets are the authoritative source for actual time
4. Users have read access to timesheet data
5. Timesheet `unit_amount` is always in hours
6. OdooClient has sufficient permissions to read analytic lines
