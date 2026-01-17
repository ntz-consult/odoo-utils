# Refactor Effort Calculation Specification and Plan

## Purpose

This specification outlines the refactoring of the effort calculation mechanism in the feature user story mapping system. The goal is to enhance the accuracy of time estimates by incorporating statistical data and applying a time factor adjustment.

## Scope

- Addition of statistical nodes to the `feature_user_story_map.toml` file
- Calculation of total lines of code (LOC) and total time estimates across all features
- Modification of the time effort calculation to include a time factor multiplier
- ✅ **Implementation completed successfully**

## Inputs

- `feature_user_story_map.toml`: The configuration file containing feature mappings and time estimates

## Outputs

- Updated `feature_user_story_map.toml` with new statistical nodes:
  - `time_factor`: A multiplier value (set to 0.4)
  - `total_loc`: Sum of all lines of code across features
  - `total_time`: Sum of all time estimates across features
- Modified time effort calculation process that multiplies time estimates by the time factor before writing

## Process Steps

### 1. Analysis Phase

- Review the current structure of `feature_user_story_map.toml`
- Identify existing time_estimate fields for each feature
- Determine how lines of code are currently tracked

### 2. Statistical Nodes Addition

- Add `time_factor = 0.4` as a new configuration parameter
- Calculate and add `total_loc` as the sum of all LOC values in the file
- Calculate and add `total_time` as the sum of all time_estimate values in the file

### 3. Calculation Modification

- Locate the code responsible for writing time_estimate values
- Modify the calculation to multiply the computed time estimate by the time_factor
- Ensure the multiplication occurs just before writing the final time_estimate

### 4. Validation

- Verify that statistical nodes are correctly added
- Confirm that total calculations are accurate
- Test that the time factor multiplication is applied correctly

## Constraints

- Time factor is read from TOML `[statistics]` section (configurable, defaults to 0.4)
- Time factor only affects newly calculated estimates (no backwards compatibility)
- Changes maintain existing feature detection and mapping logic
- Statistics are calculated from existing TOML values (no component recalculation)

## Success Criteria

✅ `feature_user_story_map.toml` contains the new statistical nodes  
✅ Total LOC and total time calculations are accurate  
✅ Time estimates are adjusted by the time_factor during calculation  
✅ No regression in existing functionality  
✅ All code changes tested and validated

## Implementation Summary

### Changes Made

#### 1. TOML File Structure Enhancement
- Added `time_factor = 0.4` to the `[statistics]` section
- Added `total_loc` (calculated sum of all LOC values)
- Added `total_time` (calculated sum of all time_estimate values in HH:MM format)

#### 2. Statistics Calculation (`feature_user_story_map_generator.py`)
- Added `_calculate_statistics()` method to automatically calculate:
  - `total_components`: Count of all components
  - `total_loc`: Sum of all LOC values from components
  - `total_time`: Sum of all time estimates (formatted as HH:MM)
  - `time_factor`: Preserved from existing value or defaults to 0.4
- Modified `_write_toml()` to call `_calculate_statistics()` before writing
- Statistics are calculated from existing values in TOML (no recalculation of components)

#### 3. Time Factor Application (`user_story_enricher.py`)
- Modified `estimate_effort_in_place()` method to:
  - Read `time_factor` from TOML `[statistics]` section
  - Apply time_factor to calculated time estimates before writing to TOML
  - Formula: `adjusted_hours = base_hours * time_factor`
- Time factor is applied just before writing the final time_estimate
- Only affects newly calculated estimates (no backwards compatibility)

#### 4. Sync Engine Updates (`sync_engine.py`)
- Added `_calculate_statistics()` method (same logic as feature_user_story_map_generator)
- Modified `_write_toml()` to calculate and update statistics when syncing with Odoo
- Ensures statistics remain accurate after Odoo synchronization

### Time Factor Application Example
```python
# Base calculation for a simple field
base_hours = 1.0  # Development: 0.5, Requirements: 0.25, Testing: 0.25

# Apply time_factor from TOML
time_factor = 0.4  # From [statistics] section
adjusted_hours = base_hours * time_factor  # = 0.4 hours

# Format as HH:MM
time_estimate = "0:24"  # 24 minutes
```

### Files Modified
1. **feature_user_story_map_generator.py** - Statistics calculation and TOML writing
2. **user_story_enricher.py** - Time factor application during effort estimation
3. **sync_engine.py** - Statistics calculation during Odoo sync
4. **studio/feature_user_story_map.toml** - Updated with statistical nodes
