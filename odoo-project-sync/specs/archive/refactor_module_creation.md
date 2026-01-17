# Refactor Module Creation for Report QWeb Views

## Purpose

This specification outlines the refactoring of the module generator to correctly handle report QWeb views that do not belong to a specific model. Currently, such views are placed in the "base" module or based on incomplete model detection. The refactoring ensures that QWeb views are placed in the same module as the report that uses them, maintaining logical organization and preventing module dependency issues.

## Status: IMPLEMENTED ✓

Implementation completed on 2026-01-05. All changes have been tested and validated.

## Scope

- Analysis of current view placement logic in module_generator.py
- Refactoring the _generate_views method to determine correct module placement for QWeb views
- Implementation of report-view dependency mapping
- Ensuring transitive dependencies (views called by other views) are handled correctly
- Documentation of changes without code implementation

## Inputs

- Current module_generator.py file
- feature_user_story_map.toml (for component references)
- views_metadata.json (containing QWeb view definitions)
- reports_output.json (containing report definitions with report_name fields)
- Extraction results with component data

## Outputs

- Refactored module_generator.py with updated view placement logic
- Updated documentation reflecting the new behavior
- Test cases validating correct view placement
- List of potential source files involved in the refactoring

## Implementation Summary

### New Methods Added to `module_generator.py`

1. **`_build_report_name_to_module_mapping()`** - Maps `report_name` to `(module, model)` tuples based on report's model

2. **`_extract_tcall_references(arch_db)`** - Extracts t-call template references from QWeb arch_db using regex pattern `t-call="..."`. Filters out `web.*` core templates.

3. **`_build_qweb_view_index()`** - Builds an index of QWeb views (type='qweb' with model=False) by their key/name for quick lookup

4. **`_resolve_all_tcall_dependencies(root_template_key, qweb_index)`** - Traverses t-call chains to find all transitive dependencies starting from a root template

5. **`_extract_all_report_templates(report_name, module, qweb_index, already_generated)`** - Extracts all QWeb templates for a report including transitive dependencies, placing them in the report's module

### Modified Methods

1. **`_generate_views()`** - Now skips QWeb views (type='qweb' with model=False) as they are handled by `_generate_reports()`

2. **`_generate_reports()`** - Completely refactored to:
   - Build report→module mapping
   - Build QWeb view index
   - Track already-generated templates to avoid duplicates
   - Generate report action files
   - Generate ALL associated QWeb templates (including transitive deps) in the same module as the report

### Key Design Decisions

1. **QWeb Identification**: Views with `type="qweb"` AND `model=False` (or empty) are considered report QWeb templates

2. **Module Placement**: QWeb templates are placed in the same module as their associated report, determined by the report's model

3. **Transitive Dependencies**: All templates called via `t-call` are recursively resolved and placed in the same module

4. **Core Template Filtering**: Templates starting with `web.*` are filtered out as they are Odoo core templates

5. **Duplicate Prevention**: Uses a `Set` to track already-generated templates across all reports

6. **First Match Priority**: If a template is used by multiple reports, the first report to process it determines its module placement

## Process Steps

### 1. Analysis of Current Implementation ✓

- Review _generate_views method in module_generator.py
- Examine _find_model_from_report method and its limitations
- Identify how reports are currently placed in modules
- Document current behavior for views without models (placed in "base" or based on pattern matching)

### 2. Design Report-View Dependency Mapping ✓

- Create a mapping from report_name to module (based on report's model)
- Parse QWeb view arch_db to extract t-call references
- Build a dependency graph of views (main template -> called templates)
- For each view, determine the root report that calls it (directly or indirectly)

### 3. Refactor View Placement Logic ✓

- Modify _generate_views to skip QWeb views (type='qweb', model=False)
- Move all QWeb handling to _generate_reports
- Ensure views are placed in the module of their associated report
- Handle cases where views are not associated with any report (not generated, as they should be linked to a report)

### 4. Handle Transitive Dependencies ✓

- Implement logic to traverse t-call chains using `_resolve_all_tcall_dependencies()`
- Ensure all called views are placed in the same module as the root report
- Prevent duplicates using a tracking Set

### 5. Update Component References ✓

- Ensure source_location updates in feature_user_story_map.toml reflect new placements via `_update_source_location_by_ref()`

### 6. Validation and Testing ✓

- Created test cases for various report-view scenarios
- Validated that views are placed correctly based on report modules
- Tested with ropeworx project data

## Constraints

- Maintain existing API and method signatures where possible
- Ensure performance impact is minimal for large numbers of views
- Preserve existing behavior for non-QWeb views

## Success Criteria ✓

- All QWeb views are placed in the same module as their associated report
- Transitive t-call dependencies are correctly resolved
- No views are placed in incorrect modules
- Existing functionality for model-based views remains unchanged
- Performance is maintained for large codebases

## Test Results

Tested with ropeworx project containing:
- 77 views (25 QWeb templates, 52 regular views)
- 10 reports

Results:
- 52 regular views generated in appropriate module/views folders
- 17 report files generated (10 report actions + 7 QWeb template files with transitive deps)
- All QWeb templates correctly placed in stock/reports (based on report models)
- No QWeb templates in base/views
- Transitive dependencies (ropeworx_label_donaghys, ropeworx_label_standard called by ropeworx_label_packaging_sml) correctly resolved

## Files Modified

- `shared/python/module_generator.py` - Main refactoring with 5 new methods and 2 modified methods
- `tests/test_module_generator.py` - Added 6 new test cases for QWeb handling

## Additional Feature: reports_map.md Generation

A new markdown document `reports_map.md` is generated in the `studio/` folder during module generation. This document provides a visual map of all reports and their associated QWeb templates.

### Format Example:

```markdown
## STOCK

### Packaging Label

- **Model:** `stock.move.line`
- **Report Name:** `studio_customization.ropeworx_label_packaging_sml`
- **Type:** qweb-pdf
- **Output Folder:** `studio/stock/reports/`

**QWeb Templates:**

- **`studio_customization.ropeworx_label_packaging_sml`**
  - File: `studio/stock/reports/ropeworx_label_packaging_sml_template.xml`
  - `studio_customization.ropeworx_label_donaghys` *(called by parent)*
    - File: `studio/stock/reports/ropeworx_label_donaghys_template.xml`
  - `studio_customization.ropeworx_label_standard` *(called by parent)*
    - File: `studio/stock/reports/ropeworx_label_standard_template.xml`
```

### New Methods Added:

- **`_generate_reports_map()`** - Main method that generates the markdown file
- **`_build_template_tree()`** - Recursively builds the template dependency tree
- **`_format_template_tree()`** - Formats the tree as indented markdown lines</content>
<parameter name="filePath">/home/gdt/awork/odoo-project-sync/specs/refactor_module_creation.md