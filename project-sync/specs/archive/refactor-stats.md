# HTML Color Palette Refactoring Specification and Plan

## Purpose

This specification outlines the process for refactoring all HTML content generated for Odoo project task descriptions to use a standardized color palette. The goal is to create a cohesive visual identity across all generated HTML while maintaining readability and professional appearance.

## Scope

- Update all HTML generation code in the codebase to use the specified color palette
- Modify inline styles and CSS classes used in HTML output
- Ensure color consistency across task descriptions, implementation overviews, and knowledge articles
- Maintain existing HTML structure and functionality while updating visual styling
- Update related test files to reflect new styling

## Inputs

- Color palette definition:
  - Dark Teal: #003339 (primary dark color for headers and text)
  - Rusty Spice: #af2e00 (accent color for borders and highlights)
  - Muted Teal: #899e8b (secondary background color)
  - Muted Teal 2: #99c5b5 (lighter background variations)
  - Icy Aqua: #afece7 (highlight and success colors)

## Outputs

- Updated HTML generation code using the new color palette
- Consistent visual styling across all Odoo task descriptions
- Modified source files with refactored color schemes
- Updated test expectations for new HTML output

## Process Steps

### 1. Color Mapping Analysis

- Analyze current color usage in HTML generation code
- Map existing colors to new palette equivalents:
  - Headers (#2c3e50, #34495e) → Dark Teal (#003339)
  - Accents/borders (#3498db, #2980b9) → Rusty Spice (#af2e00)
  - Backgrounds (#f8f9fa, #ecf0f1) → Muted Teal variants (#899e8b, #99c5b5)
  - Success highlights (#27ae60) → Icy Aqua (#afece7)
  - Warning colors (#f39c12, #e74c3c) → Rusty Spice variations

### 2. Code Refactoring

- Update STYLES dictionary in user_story_enricher.py with new color values
- Modify inline styles in implementation_overview_generator.py
- Update simple HTML generation in task_manager.py to include basic styling
- Refactor knowledge article HTML in knowledge_manager.py
- Ensure color contrast ratios meet accessibility standards

### 3. Testing and Validation

- Run existing tests to ensure HTML structure remains intact
- Update test snapshots that include HTML output
- Manual verification of color rendering in Odoo interface
- Cross-browser compatibility check for color display

### 4. Documentation Update

- Update any documentation referencing old color schemes
- Document the new color palette usage guidelines

## Potential Source Files Involved

The following files contain HTML generation code that will be refactored:

- `shared/python/user_story_enricher.py` - Main HTML styling definitions (STYLES dict)
- `shared/python/task_manager.py` - Simple HTML generation for task descriptions
- `shared/python/implementation_overview_generator.py` - Complex HTML tables for implementation overviews
- `shared/python/knowledge_manager.py` - HTML generation for knowledge articles
- `tests/test_user_story_enricher.py` - Test cases that validate HTML output
- `shared/python/cli.py` - Integration points that use HTML generation functions

## Constraints

- No changes to HTML structure or content, only visual styling
- Maintain backward compatibility with existing Odoo installations
- Ensure all colors meet WCAG accessibility guidelines for contrast
- Preserve existing functionality and data flow

## Success Criteria

- All HTML output uses only the specified color palette
- Visual consistency across different types of task descriptions
- No breaking changes to existing functionality
- All tests pass with updated HTML expectations
- Professional appearance maintained in Odoo interface

## Assumptions

- The color palette has been approved by stakeholders
- Odoo supports the specified CSS color values
- No additional CSS framework dependencies will be introduced
- Color accessibility has been verified externally

## Implementation Decisions

Based on clarifications received, the following implementation approach will be used:

1. **Error States**: Error HTML templates (red backgrounds and borders) will remain unchanged to ensure universal recognition of error conditions.

2. **Complexity Badges**: Badge colors (green/orange/red) will be kept for semantic clarity but adjusted to be more compatible with the new palette while maintaining their semantic meaning.

3. **Tag Colors**: Odoo system tag colors (TAG_COLOR_MODULE, TAG_COLOR_SIMPLE, etc.) will remain unchanged as they use Odoo's built-in color system (integers 0-11), not HTML hex codes.

4. **Gradients**: All CSS gradient effects will be removed entirely in favor of flat design using solid colors from the palette.

5. **Knowledge Manager**: The knowledge_manager.py file will be skipped as it does not contain HTML generation code. Only existing HTML styling will be adjusted.

6. **Accessibility**: Proceed with implementation without programmatic accessibility validation, assuming external verification has been completed.