# Feature-User Story Map and Enricher Refactor Specification

**Created:** 2024-12-18  
**Purpose:** Refactor the feature-user story map generation and enrichment process to work in-place with TOML files

---

## Critical Architecture Principles

### 🎯 Single Source of Truth

**`feature_user_story_map.toml` IS THE CENTERPIECE WHERE ALL INFORMATION COMES TOGETHER**

- **READ FROM:** `feature_user_story_map.toml` only
- **WRITE TO:** `feature_user_story_map.toml` only
- **TODO.md:** Simply a nice way to represent that information to the user (read-only view)
- **NEVER read from TODO.md for enrichment purposes**

### 📊 Data Flow

```
feature_user_story_map.toml (SOURCE OF TRUTH)
           ↓
     [Enrichment Process]
     - Reads from TOML
     - Enriches with AI (descriptions)
     - Calculates complexity/time
     - Writes back to TOML
           ↓ (reads and writes back to same file)
feature_user_story_map.toml (UPDATED with enrichment)
           ↓
     [generate-todo]
     - Reads from TOML only
     - Formats as markdown
     - Writes to TODO.md
           ↓ (reads TOML, generates presentation)
      TODO.md (READ-ONLY VIEW for humans)
```

### 🚫 What NOT To Do

❌ **DO NOT read from TODO.md for enrichment**  
❌ **DO NOT parse TODO.md to extract data**  
❌ **DO NOT create TODO.enriched.md as separate file**  
❌ **DO NOT rebuild existing enrichment logic**

✅ **DO read from feature_user_story_map.toml**  
✅ **DO write enrichment back to feature_user_story_map.toml**  
✅ **DO reuse existing UserStoryGenerator, EffortEstimator, ComplexityAnalyzer**  
✅ **DO regenerate TODO.md from updated TOML after enrichment**

### 🔧 Leverage Existing Implementations

This refactor reuses existing, proven components:
- `user_story_enricher.py` - Already reads from TOML, uses AI to enrich
- `effort_estimator.py` - Already reads from TOML, calculates complexity
- `enricher_config.py` - Configuration system
- `complexity_analyzer.py` - Source code analysis
- `time_estimator.py` - Time estimation logic
- `todo_generator.py` - Reads TOML and generates TODO.md

**DO NOT rebuild what already exists. Refactor to write back to TOML instead of generating markdown.**

### 🔒 What DOES NOT Change

**The enricher implementation already reads source code as defined in `source_location` from `feature_user_story_map.toml`**

- ✅ `TomlComponent.source_location` reading mechanism stays the same
- ✅ `ComplexityAnalyzer.analyze_source_file()` stays the same
- ✅ Source code parsing logic stays the same
- ✅ AI context building from source files stays the same
- ✅ All existing enrichment algorithms stay the same

**Only the OUTPUT destination changes:** Write enriched data back to TOML instead of to markdown files.

---

## Overview

This specification outlines changes to two components:

1. **`generate-feature-user-story-map`** - Add tracking fields to user stories
2. **Enricher** - Modify to update TOML in-place instead of creating separate enriched output

### Design Principle

Keep implementations simple:
- Direct read/write operations on `feature_user_story_map.toml`
- No elaborate processes or complex functions
- Backup existing files before modifications
- Update TOML structure directly
- Reuse existing enrichment logic

---

## Specification Clarifications (Resolved Ambiguities)

The following design decisions have been finalized based on project requirements:

### 1. **Tracking Fields Scope** ✅
- **Component-level only:** Tracking fields (`complexity`, `time_estimate`, `completion`) are ONLY on components
- **No user story tracking:** User stories do NOT have these fields
- **Aggregation:** Story/feature totals calculated on-the-fly when generating TODO.md (not stored)

### 2. **Default Values** ✅
- `complexity`: `"unknown"`
- `time_estimate`: `"0:00"`
- `completion`: `"100%"` (default assumes complete unless explicitly set otherwise)
- Completion field workflow: Manual editing only, implementation does not manage updates

### 3. **Error Handling** ✅
- **AI enrichment failure:** Write `"enrichment failed"` to description, continue processing
- **Source unavailable:** Write `"enrichment failed - source unavailable"`, set complexity=`"unknown"`, time=`"0:00"`, continue
- **No rollback:** Errors are logged, enrichment continues with fallback values
- **No partial data:** Failed enrichments get explicit failure markers, not half-baked content

### 4. **Dry Run Behavior** ✅
- Verifies AI connection (single test call)
- Does NOT make enrichment API calls (no cost)
- Does NOT create backups or write files
- Validates required files exist
- Reports what would be enriched

### 5. **TOML Writer** ✅
- **Use Option 1:** Reuse existing `FeatureUserStoryMapGenerator._write_toml()`
- Maintains consistency with initial generation
- Write TOML as-is, no special formatting embellishments

### 6. **Backward Compatibility** ✅
- **Convert all components:** On first enrichment, convert ALL string-format components to dict format
- **Preserve custom fields:** Don't overwrite manually-added fields in TOML

### 7. **Source Paths** ✅
- Always relative to `project_root`
- Format: `"studio/models/sale_order.py"`
- Resolution: `project_root / source_location`

### 8. **Incremental Enrichment** ✅
- **Default:** Skip already-enriched components (complexity != "unknown" and time != "0:00")
- **Flag:** `--force-reenrich` to re-enrich all components

### 9. **Backups** ✅
- Timestamp format: `YYYYMMDDHHMM` (no seconds)
- Keep maximum 5 backups per file type
- Auto-cleanup old backups after creating new ones

### 10. **Progress Reporting** ✅
- Simple print statements: `"Processing: [Feature] → [Story] → [Component]"`
- Show current item being enriched
- No fancy progress bars or elaborate logging

---

## Summary of Changes

### What Already Works ✅
- **TomlLoader** reads from `feature_user_story_map.toml` ✅
- **UserStoryGenerator** enriches with AI ✅
- **EffortEstimator** calculates complexity and time ✅
- **ComplexityAnalyzer** analyzes source code ✅
- **TodoGenerator** generates TODO.md from TOML ✅

### What Needs to Change ❌→✅
1. **Map Generator:** Add 3 tracking fields to **components** (complexity, time_estimate, completion)
2. **Enricher Output:** Change from "write to TODO.enriched.md" → "write back to feature_user_story_map.toml"
3. **Workflow:** Add backup step before modifying TOML
4. **Final Step:** Call TodoGenerator to regenerate TODO.md after enrichment

### Code to Write (Minimal)
- Add 3 fields to TOML structure in `feature_user_story_map_generator.py`
- Add `enrich_in_place()` method that reuses existing enrichment logic but writes to TOML
- Add TOML writer helper method (or reuse existing one)
- Update CLI command to call new method

**Total new code: ~200 lines. Total reused code: ~2000 lines.**

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│  feature_user_story_map.toml (SINGLE SOURCE OF TRUTH)       │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ [features."Sales Enhancements"]                        │ │
│  │   description = "Custom sales fields"                  │ │
│  │   user_stories = [                                     │ │
│  │     {                                                  │ │
│  │       description = "Add credit limit tracking"       │ │
│  │       components = [                                   │ │
│  │         {                                              │ │
│  │           ref = "field.sale.order.x_credit_limit",   │ │
│  │           source_location = "...",                    │ │
│  │           complexity = "medium",     ← ENRICHED       │ │
│  │           time_estimate = "4:30",    ← ENRICHED       │ │
│  │           completion = "100%"        ← TRACKING        │ │
│  │         }                                              │ │
│  │       ]                                                │ │
│  │     }                                                  │ │
│  │   ]                                                    │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            ↑
                    READ & WRITE
                            │
        ┌───────────────────┴───────────────────┐
        │                                       │
        ↓                                       ↓
┌──────────────────┐                  ┌──────────────────┐
│  Enricher        │                  │  TodoGenerator   │
│  (enrich_in_     │                  │  (READ ONLY)     │
│   place)         │                  │                  │
│                  │                  │  Reads TOML      │
│  1. Backup TOML  │                  │  Formats as MD   │
│  2. Read TOML    │                  │  Writes TODO.md  │
│  3. Enrich (AI)  │                  │                  │
│  4. Calc metrics │                  └──────────────────┘
│  5. Write TOML   │                           │
│  6. Call TODO    │                           ↓
│     generator    │──────────────────→  ┌──────────────┐
└──────────────────┘                     │  TODO.md     │
                                         │  (VIEW ONLY) │
    Uses existing:                       └──────────────┘
    • UserStoryGenerator
    • EffortEstimator
    • ComplexityAnalyzer
    • TimeEstimator
```

---

## Part 1: Refactor `generate-feature-user-story-map`

### Current Behavior

The `feature_user_story_map_generator.py` creates/updates `feature_user_story_map.toml` with this structure:

```toml
[features."Feature Name"]
description = "Feature description"
detected_by = "model:sale.order"
sequence = 10
user_stories = [
    { description = "User Story 1", sequence = 1, components = [
        { ref = "field.sale.order.x_custom_field", source_location = "studio/models/..." },
    ] },
]
```

### Required Changes

Add three new fields to each **component** in the TOML structure:

```toml
user_stories = [
    { 
        description = "User Story 1", 
        sequence = 1, 
        components = [
            { 
                ref = "field.sale.order.x_custom_field", 
                source_location = "...",
                complexity = "unknown",
                time_estimate = "0:00",
                completion = "100%"
            },
        ] 
    },
]
```

### Implementation Location

**File:** `shared/python/feature_user_story_map_generator.py`

**Method to modify:** `_build_map()` around line 120-400
- When creating new components, initialize with default tracking values
- When preserving existing components, retain existing tracking values if present

**Method to modify:** `_write_toml()` around line 620-690
- Update TOML serialization to include the three new fields on each component
- Ensure component fields are written in order: `ref`, `source_location`, `complexity`, `time_estimate`, `completion`

### Default Values

| Field | Default Value | Type |
|-------|--------------|------|
| `complexity` | `"unknown"` | string |
| `time_estimate` | `"0:00"` | string (format: H:MM or HH:MM) |
| `completion` | `"100%"` | string (format: N%) |

**Note:** Tracking fields are only on **components**, not on user stories. User story totals (time/complexity) are calculated on-the-fly when generating TODO.md.

### Backward Compatibility

- Existing `feature_user_story_map.toml` files without these component fields will have them added on next generation
- Existing component tracking values (if present) will be preserved during regeneration
- Components can be in old format (string refs) or new format (dicts with tracking fields)

---

## Part 2: Refactor Enricher to Update In-Place

### Current Behavior

The enricher (`user_story_enricher.py`) currently:
1. ✅ Reads `feature_user_story_map.toml` using `TomlLoader.load_features()`
2. ✅ Generates enriched user stories with AI using `UserStoryGenerator.enrich_feature()`
3. ❌ Writes to `TODO.enriched.md` (separate markdown output file)

The effort estimator (`effort_estimator.py`) currently:
1. ✅ Reads `feature_user_story_map.toml` using `TomlLoader.load_features()`
2. ✅ Analyzes source files using `ComplexityAnalyzer`
3. ✅ Calculates time estimates using `TimeEstimator`
4. ❌ Writes to markdown output file (separate)

**Both enrichers already have ALL the enrichment logic. They just write to the wrong place.**

### New Behavior

The enricher should:
1. **Create backups** of existing files with timestamps
2. **Read from TOML** using existing `TomlLoader` (already implemented)
3. **Enrich data** using existing `UserStoryGenerator` and `EffortEstimator` (already implemented)
4. **Write enriched data back to TOML** (NEW - this is the only new code needed)
5. **Regenerate TODO.md** using existing `TodoGenerator` (already implemented)

### Step-by-Step Process

#### Step 1: Create Backups

Before any modifications, create timestamped backups:

```
TODO.md → TODO_202512181752.md
feature_user_story_map.toml → feature_user_story_map_202512181752.toml
```

**Backup cleanup:** After creating backups, remove oldest backups if more than 5 exist.

**Timestamp format:** `YYYYMMDDHHMM` (year, month, day, hour, minute - no seconds)

**Backup location:** Same directory as original files

**Backup retention:** Keep maximum of 5 most recent backups per file type. Automatically clean up older backups.

**Implementation:**
- Use `datetime.now().strftime("%Y%m%d%H%M")` for timestamp
- Use `shutil.copy()` for backup
- After creating backup, clean up old backups keeping only 5 most recent

#### Step 2: Read Current TOML

**File:** `studio/feature_user_story_map.toml`

**Load using:** `tomllib.load()` (Python 3.11+) for reading

**Parse into structure:**
```python
{
    "features": {
        "Feature Name": {
            "description": "...",
            "user_stories": [
                {
                    "description": "...",
                    "sequence": 1,
                    "complexity": "unknown",
                    "time_estimate": "0:00", 
                    "completion": "0%",
                    "components": [...]
                }
            ]
        }
    }
}
```

#### Step 2b: Error Handling Strategy

**AI Enrichment Failures:**
- If enrichment fails for a feature/component, write `"enrichment failed"` to the description field
- Log the error and continue processing other features
- Do NOT write partial/half-baked enrichment data

**Source File Unavailable:**
- If `source_location` file doesn't exist, write `"enrichment failed - source unavailable"` to description
- Set complexity to `"unknown"` and time_estimate to `"0:00"`
- Continue processing other components

**Progress Reporting:**
- Print simple status: `"Processing: [Feature Name] → [User Story] → [Component ref]"`
- Show current item being enriched for visibility

#### Step 3: Enrich Descriptions with AI

**Use existing implementation:** `UserStoryGenerator.enrich_feature()` from `user_story_enricher.py`

This method already:
- Takes a `TomlFeature` object
- **Reads source code from `source_location` paths defined in TOML** ✅ (NO CHANGE)
- Calls AI with proper prompts and source code context
- Returns enriched `TomlFeature` with:
  - Enhanced feature description
  - Enhanced user story descriptions
  - Role, goal, benefit breakdown
  - Acceptance criteria

**Source code reading (UNCHANGED):**
```python
# Existing code in user_story_enricher.py already does this:
for comp in story.components:
    if comp.source_location:
        # Reads actual Python/XML source files
        source_content = comp.source_content  # Already loaded from source_location
        # AI uses this source code as context
```

**Implementation approach:**
```python
# Load features from TOML (existing code)
loader = TomlLoader(project_root)
toml_data = loader._load_raw_toml()  # Get raw dict

# Enrich using existing logic (which reads source files internally)
for feature_name, feature_def in toml_data["features"].items():
    # Progress reporting
    print(f"Processing: {feature_name}")
    
    # Convert to TomlFeature object
    feature_obj = loader._parse_feature(feature_name, feature_def)
    
    try:
        # Call existing enrichment (reads source_location internally)
        enriched_feature = user_story_generator.enrich_feature(feature_obj)
        
        # Write enriched data back to dict
        feature_def["description"] = enriched_feature.description
        for i, story in enumerate(enriched_feature.user_stories):
            print(f"  → User Story {i+1}")
            feature_def["user_stories"][i]["description"] = story.description
    except Exception as e:
        # On failure, mark as failed and continue
        logger.error(f"Enrichment failed for {feature_name}: {e}")
        feature_def["description"] = "enrichment failed"
        for story in feature_def.get("user_stories", []):
            story["description"] = "enrichment failed"
        continue
```

**Fields to enrich:**
- Feature-level `description`
- User story-level `description`

#### Step 4: Add/Update Complexity and Time Estimates

**Use existing implementation:** `EffortEstimator` from `effort_estimator.py`

This class already:
- Takes `TomlComponent` objects with source locations
- **Reads and analyzes source code from `source_location` paths** ✅ (NO CHANGE)
- Calls `ComplexityAnalyzer.analyze_source_file()` for each component
- Calculates complexity scores and labels
- Uses `TimeEstimator` to calculate hours
- Returns `EstimatedComponent` with all metrics

**Source code analysis (UNCHANGED):**
```python
# Existing code in effort_estimator.py already does this:
if comp.source_location:
    source_path = resolve_source_location(comp.source_location, project_root)
    complexity_result = analyzer.analyze_source_file(source_path)  # Reads actual file
```

**Implementation approach:**
```python
# For each user story in TOML
for story_idx, story in enumerate(feature_def["user_stories"]):
    components = story.get("components", [])
    
    # Use existing effort estimator for EACH COMPONENT
    for i, comp_item in enumerate(components):
        # Convert to dict if it's a string (old format - backward compatibility)
        if isinstance(comp_item, str):
            comp_dict = {"ref": comp_item, "source_location": False}
            components[i] = comp_dict
        else:
            comp_dict = comp_item
        
        # Progress reporting
        print(f"    → Component: {comp_dict.get('ref', 'unknown')}")
        
        comp = TomlComponent.from_toml_item(comp_dict)
        
        try:
            # Call existing complexity analysis
            if comp.source_location:
                source_path = resolve_source_location(comp.source_location, project_root)
                if not source_path.exists():
                    raise FileNotFoundError(f"Source not found: {source_path}")
                
                complexity_result = analyzer.analyze_source_file(source_path)
                label = complexity_result.label
            else:
                # No source location - use unknown
                label = "unknown"
            
            # Call existing time estimation
            hours = time_estimator.estimate_component(comp.component_type, label)
            
            # Store tracking fields ON THE COMPONENT
            comp_dict["complexity"] = label
            
            # Format time estimate
            hours_int = int(hours)
            minutes = int((hours - hours_int) * 60)
            comp_dict["time_estimate"] = f"{hours_int}:{minutes:02d}"
            
        except FileNotFoundError as e:
            # Source file unavailable
            logger.warning(f"Source unavailable for {comp_dict['ref']}: {e}")
            comp_dict["complexity"] = "unknown"
            comp_dict["time_estimate"] = "0:00"
            if "description" in comp_dict:
                comp_dict["description"] = "enrichment failed - source unavailable"
        except Exception as e:
            # Other errors
            logger.error(f"Failed to analyze {comp_dict['ref']}: {e}")
            comp_dict["complexity"] = "unknown"
            comp_dict["time_estimate"] = "0:00"
        
        # Keep completion at existing or default
        if "completion" not in comp_dict:
            comp_dict["completion"] = "100%"
```

**Complexity labels:** "simple", "medium", "complex", "very_complex", "unknown"

**Time estimate format:** "H:MM" (e.g., "2:30", "8:00", "16:45")

**Completion format:** "N%" (e.g., "0%", "50%", "100%")

#### Step 5: Write Updated TOML

**File:** `studio/feature_user_story_map.toml` (overwrite)

**Write using:** Custom TOML writer (same as current `_write_toml()` method)

**Preserve:**
- All feature and user story structure
- Component assignments
- Sequences
- Source locations
- Any custom fields not mentioned above

**Format requirements:**
- Maintain readable formatting
- Preserve comments where possible
- Use inline table format for user stories (same as current)

#### Step 6: Regenerate TODO.md

After TOML is updated, regenerate TODO.md:

**Command equivalent:** `generate-todo --execute`

**Implementation:** 
- Call existing `TodoGenerator` class
- Read from updated `feature_user_story_map.toml`
- Write to `studio/TODO.md`

**Result:** TODO.md now reflects enriched descriptions and tracking data

---

## Existing Implementations to Reuse

These files already have the enrichment logic - we just need to redirect their output:

| File | What It Does | What We'll Reuse |
|------|-------------|------------------|
| `shared/python/user_story_enricher.py` | Reads TOML, enriches with AI, writes MD | ✅ `TomlLoader`, `UserStoryGenerator.enrich_feature()` |
| `shared/python/effort_estimator.py` | Reads TOML, calculates complexity, writes MD | ✅ `EffortEstimator._estimate_component()`, scoring logic |
| `shared/python/complexity_analyzer.py` | Analyzes source files for metrics | ✅ `ComplexityAnalyzer.analyze_source_file()` |
| `shared/python/time_estimator.py` | Calculates time from complexity | ✅ `TimeEstimator.estimate_component()` |
| `shared/python/todo_generator.py` | Reads TOML, generates TODO.md | ✅ `TodoGenerator.generate()` |
| `shared/python/feature_user_story_mapper.py` | Maps TOML to Feature objects | ✅ `FeatureUserStoryMapper.map_from_toml()` |
| `shared/python/enricher_config.py` | Configuration for enrichers | ✅ `EnricherConfig`, `UserStoryEnricherConfig` |

**Key insight:** The enrichment pipeline already exists and works perfectly. It just writes to the wrong place (markdown files instead of TOML).

---

## Modified Files Summary

| File | Modification Type | Key Changes |
|------|------------------|-------------|
| `shared/python/feature_user_story_map_generator.py` | Update | Add 3 new fields to **component** structure |
| `shared/python/user_story_enricher.py` | Refactor | Add `enrich_in_place()` method that writes to TOML instead of MD |
| `shared/python/cli.py` | Update | Modify `cmd_enrich_todo()` to use new in-place enrichment |

**Files NOT modified:** `effort_estimator.py`, `complexity_analyzer.py`, `time_estimator.py`, `todo_generator.py` - these are reused as-is.

---

## Enricher Refactor Details

### New Enricher Workflow

**Current file:** `shared/python/user_story_enricher.py`

**Class:** `UserStoryEnricher`

**Method to refactor:** `enrich()` method (currently around line 550-600)

#### Current signature:
```python
def enrich(self, project_root: Path, dry_run: bool = False) -> str:
    """Enrich features from TOML with AI-generated user stories.
    
    Returns:
        Enriched markdown content
    """
    # Load features directly from TOML
    loader = TomlLoader(project_root)
    features = loader.load_features()  # Returns list[TomlFeature]
    
    # Enrich each feature with AI
    enriched_features = []
    for feature in features:
        enriched = self.generator_ai.enrich_feature(feature)  # EXISTING LOGIC
        enriched_features.append(enriched)
    
    # Generate markdown output
    return self.markdown_gen.generate(enriched_features, project_name)  # WRITE TO MD
```

**Problem:** Last step writes to markdown instead of back to TOML.

#### New signature:
```python
def enrich_in_place(self, project_root: Path, dry_run: bool = False, force_reenrich: bool = False) -> dict:
    """Updates TOML in-place with enrichment and regenerates TODO.md
    
    Args:
        project_root: Root directory of the project
        dry_run: If True, verify AI connection only, don't enrich or write
        force_reenrich: If True, re-enrich all components even if already enriched
    
    Uses existing enrichment logic from:
    - UserStoryGenerator.enrich_feature() for AI enrichment
    - EffortEstimator for complexity/time calculation
    
    Error handling:
    - On enrichment failure: write "enrichment failed" and continue
    - On missing source: write "enrichment failed - source unavailable" and continue
    
    Returns:
        dict with keys:
            - backup_todo: Path to backed up TODO.md
            - backup_toml: Path to backed up feature_user_story_map.toml  
            - updated_toml: Path to updated TOML file
            - regenerated_todo: Path to regenerated TODO.md
            - features_enriched: int count
            - user_stories_enriched: int count
            - components_enriched: int count
            - errors: list of error messages
    """
```

### New Method Structure

```python
def enrich_in_place(self, project_root: Path, dry_run: bool = False) -> dict:
    # 1. Validate files exist
    map_file = project_root / "studio" / "feature_user_story_map.toml"
    todo_file = project_root / "studio" / "TODO.md"
    
    if not map_file.exists():
        raise FileNotFoundError(f"Map file not found: {map_file}")
    
    # 2. Dry run: verify AI connection only
    if dry_run:
        print("🔍 Dry run mode: Verifying AI connection...")
        try:
            # Test AI connection with minimal call
            self.generator_ai.test_connection()
            print("✓ AI connection verified")
        except Exception as e:
            raise RuntimeError(f"AI connection failed: {e}")
        
        # Count what would be enriched
        loader = TomlLoader(project_root)
        features = loader.load_features()
        total_stories = sum(len(f.user_stories) for f in features)
        total_components = sum(len(c) for f in features for s in f.user_stories for c in s.components)
        
        return {
            "features_enriched": len(features),
            "user_stories_enriched": total_stories,
            "components_enriched": total_components,
            "errors": []
        }
    
    # 3. Create backups and clean up old ones
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    backup_todo = None
    backup_toml = None
    
    if todo_file.exists():
        backup_todo = todo_file.parent / f"TODO_{timestamp}.md"
        shutil.copy(todo_file, backup_todo)
        # Clean up old TODO backups (keep 5 most recent)
        _cleanup_old_backups(todo_file.parent, "TODO_*.md", keep=5)
    
    backup_toml = map_file.parent / f"feature_user_story_map_{timestamp}.toml"
    shutil.copy(map_file, backup_toml)
    # Clean up old TOML backups (keep 5 most recent)
    _cleanup_old_backups(map_file.parent, "feature_user_story_map_*.toml", keep=5)
    
    # 4. Load TOML using EXISTING TomlLoader
    loader = TomlLoader(project_root)
    features = loader.load_features()  # Returns list[TomlFeature]
    
    # Load raw TOML data for writing back
    with open(map_file, "rb") as f:
        toml_data = tomllib.load(f)
    
    # 5. Enrich descriptions with AI using EXISTING UserStoryGenerator
    features_enriched = 0
    user_stories_enriched = 0
    components_enriched = 0
    errors = []
    
    for feature in features:
        feature_name = feature.name
        
        # Call EXISTING enrichment logic
        enriched_feature = self.generator_ai.enrich_feature(feature)
        
        # Write enriched data back to TOML dict
        if enriched_feature.description != feature.description:
            toml_data["features"][feature_name]["description"] = enriched_feature.description
            features_enriched += 1
        
        # Update user stories
        for i, enriched_story in enumerate(enriched_feature.user_stories):
            original_story = feature.user_stories[i]
            
            if enriched_story.description != original_story.description:
                toml_data["features"][feature_name]["user_stories"][i]["description"] = (
                    enriched_story.description
                )
                user_stories_enriched += 1
    
    # 6. Add/update complexity and time_estimate ON COMPONENTS using EXISTING EffortEstimator
    effort_estimator = EffortEstimator(self.config)
    complexity_analyzer = ComplexityAnalyzer()
    
    for feature_name, feature_def in toml_data["features"].items():
        print(f"\nProcessing feature: {feature_name}")
        
        for story_idx, story_data in enumerate(feature_def.get("user_stories", [])):
            print(f"  → User Story {story_idx + 1}")
            components = story_data.get("components", [])
            
            # Process EACH COMPONENT individually
            for i, comp_item in enumerate(components):
                # Normalize to dict format (backward compatibility)
                if isinstance(comp_item, str):
                    comp_dict = {"ref": comp_item, "source_location": False}
                    components[i] = comp_dict
                else:
                    comp_dict = comp_item
                
                print(f"    → Component: {comp_dict.get('ref', 'unknown')}")
                
                # Skip if already enriched (unless force_reenrich)
                if not force_reenrich:
                    is_enriched = (
                        comp_dict.get("complexity", "unknown") != "unknown" and
                        comp_dict.get("time_estimate", "0:00") != "0:00"
                    )
                    if is_enriched:
                        print(f"      ↳ Skipping (already enriched)")
                        continue
                
                try:
                    comp = TomlComponent.from_toml_item(comp_dict)
                    
                    # Use existing effort estimator methods
                    estimated = effort_estimator._estimate_component(comp, project_root)
                    
                    # Store tracking fields ON THE COMPONENT
                    comp_dict["complexity"] = estimated.computed_label
                    
                    # Format time estimate
                    total_hours = estimated.adjusted_hours.total
                    hours = int(total_hours)
                    minutes = int((total_hours - hours) * 60)
                    comp_dict["time_estimate"] = f"{hours}:{minutes:02d}"
                    
                    components_enriched += 1
                    
                except FileNotFoundError as e:
                    error_msg = f"Source unavailable for {comp_dict.get('ref')}: {e}"
                    errors.append(error_msg)
                    print(f"      ⚠ {error_msg}")
                    comp_dict["complexity"] = "unknown"
                    comp_dict["time_estimate"] = "0:00"
                    if "description" in comp_dict:
                        comp_dict["description"] = "enrichment failed - source unavailable"
                
                except Exception as e:
                    error_msg = f"Failed to analyze {comp_dict.get('ref')}: {e}"
                    errors.append(error_msg)
                    print(f"      ✗ {error_msg}")
                    comp_dict["complexity"] = "unknown"
                    comp_dict["time_estimate"] = "0:00"
                
                # Ensure completion exists with correct default
                if "completion" not in comp_dict:
                    comp_dict["completion"] = "100%"
    
    # 7. Write updated TOML using EXISTING writer from feature_user_story_map_generator
    self._write_toml_file(map_file, toml_data)
    
    # 8. Regenerate TODO.md using EXISTING TodoGenerator
    regenerated_todo = None
        # Use existing todo generator
        from todo_generator import TodoGenerator
        from feature_user_story_mapper import FeatureUserStoryMapper
        
        mapper = FeatureUserStoryMapper(project_root)
        features_for_todo = mapper.map_from_toml()
        
        todo_gen = TodoGenerator(...)  # Use appropriate config
        content = todo_gen.generate(features_for_todo, dry_run=False)
        
        regenerated_todo = todo_file
    
    # 9. Return results
    return {
        "backup_todo": backup_todo,
        "backup_toml": backup_toml,
        "updated_toml": map_file,
        "regenerated_todo": regenerated_todo,
        "features_enriched": features_enriched,
        "user_stories_enriched": user_stories_enriched,
        "components_enriched": components_enriched,
        "errors": errors,
    }
```

**Key changes from original proposal:**
- ✅ Use `TomlLoader.load_features()` instead of raw dict parsing
- ✅ Use `UserStoryGenerator.enrich_feature()` for AI enrichment
- ✅ Use `EffortEstimator` for complexity/time calculation
- ✅ Use `TodoGenerator` for regenerating TODO.md
- ✅ Simple read-TOML → enrich-data → write-TOML flow

### Helper Methods Needed

**Two new helper methods needed - everything else already exists!**

```python
def _cleanup_old_backups(directory: Path, pattern: str, keep: int = 5) -> None:
    """Remove old backup files, keeping only the most recent N.
    
    Args:
        directory: Directory containing backups
        pattern: Glob pattern to match (e.g., "TODO_*.md")
        keep: Number of most recent backups to keep
    """
    backups = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    for old_backup in backups[keep:]:
        old_backup.unlink()
        print(f"  Cleaned up old backup: {old_backup.name}")

def _write_toml_file(self, path: Path, data: dict) -> None:
    """Write TOML data to file.
    
    Reuse the TOML writing logic from FeatureUserStoryMapGenerator._write_toml()
    OR use the tomlkit library for preserving formatting.
    """
    # Option 1: Import and reuse existing writer
    from feature_user_story_map_generator import FeatureUserStoryMapGenerator
    
    generator = FeatureUserStoryMapGenerator(path.parent.parent, verbose=False)
    generator._write_toml(data)
    
    # Option 2: Use tomlkit (if available)
    # import tomlkit
    # with open(path, "w") as f:
    #     tomlkit.dump(data, f)
```

**All other methods already exist:**

| Function | Existing Location |
|----------|------------------|
| Load features from TOML | `TomlLoader.load_features()` in `user_story_enricher.py` |
| Enrich with AI | `UserStoryGenerator.enrich_feature()` in `user_story_enricher.py` |
| Calculate complexity | `EffortEstimator._estimate_component()` in `effort_estimator.py` |
| Calculate time | `TimeEstimator.estimate_component()` in `effort_estimator.py` |
| Analyze source code | `ComplexityAnalyzer.analyze_source_file()` in `complexity_analyzer.py` |
| Generate TODO.md | `TodoGenerator.generate()` in `todo_generator.py` |
| Load mapper data | `FeatureUserStoryMapper.map_from_toml()` in `feature_user_story_mapper.py` |

---

## CLI Command Updates

### Current Command

```bash
./.odoo-sync/cli.py enrich-all --execute
```

**Current behavior:**
- Reads `feature_user_story_map.toml`
- Writes `TODO.enriched.md`

### Updated Command

```bash
./.odoo-sync/cli.py enrich-all --execute

# Force re-enrich all (ignore existing enrichment)
./.odoo-sync/cli.py enrich-all --execute --force-reenrich
```

**New behavior:**
- Creates backups: `TODO_YYYYMMDDHHMM.md`, `feature_user_story_map_YYYYMMDDHHMM.toml`
- Cleans up old backups (keeps max 5)
- Updates `feature_user_story_map.toml` in-place
- On errors: writes "enrichment failed" and continues
- Regenerates `TODO.md` from updated TOML
- Shows progress: current feature → user story → component

### CLI Method Update

**File:** `shared/python/cli.py`

**Method:** `cmd_enrich_todo()` (around line 1988-2050)

**Changes:**
```python
def cmd_enrich_todo(self, args):
    """Run full enrichment pipeline: enriches TOML and regenerates TODO."""
    try:
        project_root = self.project_root
        map_file = project_root / "studio" / "feature_user_story_map.toml"
        
        if not map_file.exists():
            raise CLIError(
                f"feature_user_story_map.toml not found: {map_file}\n"
                "Run 'generate-feature-user-story-map --execute' first."
            )
        
        # Load config
        if args.config and Path(args.config).exists():
            config = EnricherConfig.from_file(Path(args.config))
        else:
            config = EnricherConfig.default()
        
        if args.provider:
            config.user_story_enricher.ai_provider = args.provider
        
        dry_run = not args.execute
        
        self.log(f"🚀 Running enrichment pipeline (in-place mode)...")
        self.log(f"   Source: {map_file}")
        
        if dry_run:
            self.log("   Mode: Dry run (preview only, no backups created)")
        
        # Report results
        enricher = UserStoryEnricher(config)
        force_reenrich = getattr(args, 'force_reenrich', False)
        result = enricher.enrich_in_place(project_root, dry_run=dry_run, force_reenrich=force_reenrich)
        
        # Report results
        if not dry_run:
            self.log(f"\n✅ Enrichment complete!")
            self.log(f"   Backups created:")
            if result["backup_todo"]:
                self.log(f"     - {result['backup_todo'].name}")
            self.log(f"     - {result['backup_toml'].name}")
            self.log(f"\n   Updated files:")
            self.log(f"     - feature_user_story_map.toml")
            self.log(f"     - TODO.md (regenerated)")
            self.log(f"\n   Enrichment stats:")
            self.log(f"     - Features: {result['features_enriched']}")
            self.log(f"     - User stories: {result['user_stories_enriched']}")
            self.log(f"     - Components: {result['components_enriched']}")
            
            if result['errors']:
                self.log(f"\n   ⚠ Errors encountered: {len(result['errors'])}")
                for error in result['errors'][:5]:  # Show first 5
                    self.log(f"     - {error}")
                if len(result['errors']) > 5:
                    self.log(f"     ... and {len(result['errors']) - 5} more")
        else:
            self.log(f"\n📋 Dry run results:")
            self.log(f"   Would enrich:")
            self.log(f"     - {result['features_enriched']} features")
            self.log(f"     - {result['user_stories_enriched']} user stories")
            self.log(f"     - {result['components_enriched']} components")
        
        return 0
        
    except Exception as e:
        self.log_error(f"Enrichment failed: {e}")
        return 1
```

---

## Testing Considerations

### Manual Testing Steps

1. **Test Part 1: New fields in map generation**
   ```bash
   # Generate fresh map
   ./.odoo-sync/cli.py generate-feature-user-story-map --execute
   
   # Verify TOML contains complexity, time_estimate, completion
   cat studio/feature_user_story_map.toml | grep -A5 user_stories
   ```

2. **Test Part 2: In-place enrichment**
   ```bash
   # Dry run first
   ./.odoo-sync/cli.py enrich-all
   
   # Real run
   ./.odoo-sync/cli.py enrich-all --execute
   
   # Verify backups created
   ls -la studio/TODO_*.md studio/feature_user_story_map_*.toml
   
   # Verify TOML updated
   cat studio/feature_user_story_map.toml
   
   # Verify TODO regenerated
   cat studio/TODO.md
   ```

3. **Test backward compatibility**
   - Use existing TOML without new fields
   - Run enrichment
   - Verify fields added properly

### Unit Test Requirements

**New test files:**
- `tests/test_feature_user_story_map_generator_tracking.py` - Test new fields
- `tests/test_enricher_in_place.py` - Test in-place enrichment

**Test cases:**
1. Generate map with new fields (default values)
2. Preserve existing tracking values during regeneration
3. Create backups with correct timestamp format
4. Update TOML descriptions in-place
5. Update complexity and time_estimate
6. Regenerate TODO.md after enrichment
7. Dry run mode (no file modifications)
8. Handle missing files gracefully

---

## Migration Notes

### For Existing Projects

Projects with existing `feature_user_story_map.toml` files:

1. **First run after update:**
   - New fields will be added with default values
   - Existing assignments and descriptions preserved
   - No backups created on first map regeneration

2. **First enrichment after update:**
   - Backups will be created
   - TOML updated in-place
   - Old `TODO.enriched.md` files can be deleted (no longer generated)

### Backward Compatibility

- Old TOML format (without tracking fields) → Supported, fields added automatically
- Old enrichment workflow (TODO.enriched.md output) → Replaced with in-place updates
- CLI commands → Same commands, different behavior (more intuitive)

---

## File Locations Reference

| File | Purpose | Modified? |
|------|---------|-----------|
| `studio/feature_user_story_map.toml` | Source of truth for features and user stories | ✅ Updated in-place |
| `studio/TODO.md` | Generated task list | ✅ Regenerated after enrichment |
| `studio/TODO_YYYYMMDDHHSS.md` | Backup of TODO.md | ✅ Created before enrichment |
| `studio/feature_user_story_map_YYYYMMDDHHSS.toml` | Backup of TOML | ✅ Created before enrichment |
| `studio/TODO.enriched.md` | Old enriched output | ❌ No longer created |

---

## Implementation Order

1. **Phase 1: Add tracking fields to map generator**
   - Modify `feature_user_story_map_generator.py`
   - Add fields to user story structure
   - Update TOML writer
   - Test with existing projects

2. **Phase 2: Refactor enricher for in-place updates**
   - Create backup mechanism
   - Modify enricher to update TOML
   - Add complexity/time estimation
   - Add TODO regeneration step
   - Test enrichment workflow

3. **Phase 3: Update CLI command**
   - Modify `cmd_enrich_todo()` to use new enricher method
   - Update help text and documentation
   - Test full workflow from CLI

4. **Phase 4: Testing and validation**
   - Write unit tests
   - Manual testing with sample projects
   - Update documentation

---

## Success Criteria

✅ User stories in `feature_user_story_map.toml` have three new fields: `complexity`, `time_estimate`, `completion`

✅ Enrichment creates timestamped backups before modifications

✅ Enrichment updates TOML in-place (no `TODO.enriched.md` file)

✅ TODO.md is automatically regenerated after enrichment

✅ All existing functionality preserved (backward compatible)

✅ Simple implementation (no elaborate processes)

---

## Key Principles Summary

### 🎯 Architecture Principles

1. **feature_user_story_map.toml is the single source of truth**
   - All data lives here
   - All enrichment writes back here
   - TODO.md is just a formatted view

2. **Reuse existing implementations**
   - UserStoryGenerator for AI enrichment (DONE ✅)
   - EffortEstimator for complexity calculation (DONE ✅)
   - ComplexityAnalyzer for source analysis (DONE ✅)
   - TodoGenerator for markdown generation (DONE ✅)

3. **Simple workflow**
   - Read TOML
   - Enrich data (using existing logic)
   - Write back to TOML
   - Regenerate TODO.md

4. **Never read from TODO.md**
   - TODO.md is output only
   - All input comes from TOML
   - TODO.md is regenerated on demand

### ✅ Implementation Checklist

**Part 1: Map Generator Updates**
- [ ] Add 3 tracking fields (`complexity`, `time_estimate`, `completion`) to **component** structure
- [ ] Set default: `completion = "100%"` (not 0%)
- [ ] Update `_build_map()` to initialize tracking fields on new components
- [ ] Update `_write_toml()` to serialize tracking fields

**Part 2: Enricher In-Place Updates**
- [ ] Add `_cleanup_old_backups()` helper (keep max 5 backups)
- [ ] Add `_write_toml_file()` helper (reuse existing writer)
- [ ] Create `enrich_in_place()` method with:
  - [ ] Dry run: verify AI connection only, no enrichment calls
  - [ ] Backup mechanism with `YYYYMMDDHHMM` timestamp
  - [ ] Backup cleanup (keep 5 most recent)
  - [ ] Error handling: write "enrichment failed" and continue
  - [ ] Source unavailable handling: write "enrichment failed - source unavailable"
  - [ ] Progress reporting: print feature → story → component
  - [ ] Incremental enrichment: skip if already enriched (unless `--force-reenrich`)
  - [ ] Convert ALL string components to dict format (backward compatibility)
  - [ ] Preserve custom fields in TOML
  - [ ] Call existing `UserStoryGenerator.enrich_feature()`
  - [ ] Call existing `EffortEstimator._estimate_component()`
  - [ ] Write enriched data back to TOML
  - [ ] Regenerate TODO.md using `TodoGenerator`

**Part 3: CLI Updates**
- [ ] Add `--force-reenrich` flag to `enrich-all` command
- [ ] Update `cmd_enrich_all()` to call `enrich_in_place()` with flags
- [ ] Update reporting to show components count and errors
- [ ] Handle dry run mode properly

**Part 4: Testing**
- [ ] Test Part 1: new tracking fields in generated TOML
- [ ] Test Part 2: in-place enrichment with backups
- [ ] Test backward compatibility: old string format → dict format
- [ ] Test error handling: missing source files
- [ ] Test dry run: no writes, AI connection only
- [ ] Test incremental: skip already enriched
- [ ] Test force-reenrich: re-enrich all
- [ ] Test backup cleanup: max 5 kept

---

## Implementation Requirements Summary

### New Code Required (~200 lines)

**File: `shared/python/feature_user_story_map_generator.py`**
- Modify component initialization to add 3 tracking fields with defaults
- Update TOML writer to serialize new fields

**File: `shared/python/user_story_enricher.py`**
- Add `_cleanup_old_backups(directory, pattern, keep=5)` helper (~10 lines)
- Add `_write_toml_file(path, data)` helper that reuses existing writer (~5 lines)
- Add `enrich_in_place(project_root, dry_run=False, force_reenrich=False)` method (~150 lines)
  - Includes: backup, cleanup, error handling, progress reporting, skip logic, TOML writing

**File: `shared/python/cli.py`**
- Update `cmd_enrich_todo()` to add `--force-reenrich` flag (~5 lines)
- Update result reporting to include components and errors (~10 lines)

### Reused Code (~2000 lines)
- `TomlLoader.load_features()` - Load TOML structure
- `UserStoryGenerator.enrich_feature()` - AI enrichment with source code context
- `EffortEstimator._estimate_component()` - Complexity and time calculation
- `ComplexityAnalyzer.analyze_source_file()` - Source code analysis
- `TimeEstimator.estimate_component()` - Time estimation
- `TodoGenerator.generate()` - Markdown generation from TOML
- `FeatureUserStoryMapGenerator._write_toml()` - TOML writing

### Configuration Changes
None required. Use existing `EnricherConfig` and `UserStoryEnricherConfig`.

### Breaking Changes
None. Fully backward compatible. Old TOML files work, get upgraded automatically.

---

## Questions & Clarifications

All ambiguities resolved. Specification is complete and actionable.

**All Clarifications Received and Documented:**
1. ✅ Tracking fields on components only (not user stories)
2. ✅ User story totals calculated on-the-fly (not stored)
3. ✅ Completion defaults to "100%" (not "0%")
4. ✅ Error handling: write "enrichment failed" and continue
5. ✅ Dry run: verify AI connection only, no enrichment calls
6. ✅ TOML writer: reuse existing (Option 1)
7. ✅ Backward compatibility: convert all to dict format on first run
8. ✅ Source paths: always relative to project_root
9. ✅ Incremental enrichment: skip already enriched unless --force-reenrich
10. ✅ Backups: YYYYMMDDHHMM format, keep max 5, auto-cleanup
11. ✅ Progress: simple print statements per item

---

**End of Specification**
