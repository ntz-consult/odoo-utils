## Quick Reference: Complete Workflow

### Database Source Workflow (6+ Steps)

| Step | Action | Command / Description |
|------|--------|----------------------|
| 1 | **Extract** | `.odoo-sync/cli.py extract --execute` |
| 2 | **⚠️ USER EDIT** | Edit module_model_map.toml |
| 3 | **Generate Feature Map** | `.odoo-sync/cli.py generate-feature-user-story-map --execute` |
| 4 | **⚠️ USER EDIT** | Edit studio/feature_user_story_map.toml |
| 5 | **Generate Modules** | `.odoo-sync/cli.py generate-modules --execute` |
| 6a | **Enrich User Stories** *(optional)* | `.odoo-sync/cli.py enrich-stories --execute` |
| 6b | **Estimate Effort** *(optional)* | `.odoo-sync/cli.py estimate-effort --execute` |
| 6c | **Complete Enrichment** *(optional)* | `.odoo-sync/cli.py enrich-all --execute` |
| 6d | **Update HTML Tables** *(optional)* | `.odoo-sync/cli.py update-task-tables --execute` |
| 6 | **Sync** | `.odoo-sync/cli.py sync --execute` |

# Odoo Project Sync - User Guide

This utility automates the synchronization of Odoo projects through a sequential workflow. It supports two primary sources of truth:
- **Odoo database** with customizations (e.g., via Odoo Studio)
- **Existing Odoo custom module source code**

## Prerequisites

- Python 3.8 or later
- pip (Python package manager)
- Access to two Odoo instances:
  - **Implementation Odoo** - Where Studio customizations are built (read-only, required for database-based workflow)
  - **Development Odoo** - For project management (read/write)
  - API keys for both instances (get from Odoo: Settings → Integrations → Access Tokens)
- **Optional (for enrichers):** AI API key for user story enrichment:
  - OpenAI API key (default provider) OR
  - Anthropic API key (alternative provider)
- **Optional (for enrichers):** AI API key for user story enrichment:
  - OpenAI API key (default provider) OR
  - Anthropic API key (alternative provider)

## Installation

1. **Install the plugin**:
   ```bash
   cd /path/to/your/project
   /path/to/odoo-project-sync/install.sh
   ```

2. **Set up environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env and add your Odoo API keys
   # For user story enrichment (optional), configure AI settings:
   #   OPENAI_API_KEY=sk-... (for OpenAI provider)
   #   ANTHROPIC_API_KEY=sk-ant-... (for Anthropic provider)
   #   AI_PROVIDER=openai (default provider: openai or anthropic)
   #   AI_MODEL=gpt-4 (for OpenAI) or claude-sonnet-4-5-20250929 (for Anthropic)
   # Use 'anthropic-models' command to see all available Claude models
   ```

3. **Initialize configuration**:
   ```bash
   .odoo-sync/cli.py init
   .odoo-sync/cli.py status
   ```


## Workflow

The workflow consists of up to 7 steps. **Steps 1-3 are only for database-based sources**; if you're starting from existing module source code, skip to Step 4.

### Step 1: Extract (Database Source Only)

Extract customizations from the Odoo database:

```bash
.odoo-sync/cli.py extract --execute
```

**Outputs:**
- `.odoo-sync/data/extraction-results/extract.json` - Raw extraction data
- `.odoo-sync/data/extraction-results/module_model_map.toml` - Initial mapping of modules to models

### Step 2: Review and Edit Mapping (Database Source Only)

**⚠️ CRITICAL USER ACTION REQUIRED**

You **must** manually edit and verify `module_model_map.toml` before proceeding to Step 3. This file determines how models are organized into modules.

**Location:** `.odoo-sync/data/extraction-results/module_model_map.toml`

**What to review:**
- Verify that models are assigned to the correct modules
- Check that module names follow Odoo conventions
- Ensure all extracted models are accounted for
- Adjust groupings based on your project structure

**Edit the file:**
```bash
vim .odoo-sync/data/extraction-results/module_model_map.toml
# Or use your preferred editor
```

**Do not proceed to Step 3 until you have reviewed and confirmed the mappings are accurate.**

### Step 3: Generate Feature Map (Database Source Only)

Analyze extracted components to create the feature-to-user-story mapping:

```bash
.odoo-sync/cli.py generate-feature-user-story-map --execute
```

**Outputs:** `studio/feature_user_story_map.toml`

### Step 4: Review and Edit Feature Map (All Sources)

**⚠️ CRITICAL USER ACTION REQUIRED**

You **must** manually edit and verify `studio/feature_user_story_map.toml` before proceeding to Step 5. This file defines the features, user stories, and their relationships.

**Location:** `studio/feature_user_story_map.toml`

**What to review:**
- Verify feature descriptions are complete and accurate
- Review and refine user story descriptions
- Check that all features are mapped to appropriate user stories
- Add missing features or stories identified during review
- Validate time estimates and complexity assessments
- Ensure feature dependencies are correctly captured
- **Remove any duplicate component references** (each component should appear only once)

**Edit the file:**
```bash
vim studio/feature_user_story_map.toml
# Or use your preferred editor
```

**Do not proceed to Step 5 until you have reviewed and confirmed the feature map is complete and accurate.**

### Step 5: Generate Modules (Database Source Only)

Generate custom Odoo module-style source files:

```bash
.odoo-sync/cli.py generate-modules --execute
```

**Note:** This step will check for duplicate components in `feature_user_story_map.toml` and refuse to proceed if any are found. Each component must appear in exactly one user story.

**Outputs:** Python, XML, and TOML files in a module structure. The `source_location` field in `feature_user_story_map.toml` is updated with the path to each generated file.

### Step 6a: Enrich User Stories (Optional)

Use AI to enrich user stories with business context, roles, and acceptance criteria.
**Updates `feature_user_story_map.toml` in-place and regenerates `TODO.md`:**

```bash
.odoo-sync/cli.py enrich-stories --execute
```

**How it works:**
- Creates timestamped backup of TOML before changes
- Reads from `studio/feature_user_story_map.toml` (the source of truth)
- Uses `source_location` in the TOML to load source files for AI context
- AI enriches feature and user story descriptions
- **Writes enriched data back to `feature_user_story_map.toml`**
- **Regenerates `TODO.md` from the updated TOML**

**Options:**
- Omit `--execute` for dry-run (preview what would be enriched)
- `--provider openai|anthropic` — Override AI provider from `.env`
- `--config <file>` — Path to enricher configuration TOML file

**Outputs:** 
- `studio/feature_user_story_map.toml` (updated in-place)
- `studio/TODO.md` (regenerated)
- Backup: `studio/feature_user_story_map_YYYYMMDDHHMM.toml`

**⚠️ Requirements:** 
- **AI API key required** - Must be set in `.env` file:
  - For OpenAI: `OPENAI_API_KEY=sk-...`
  - For Anthropic: `ANTHROPIC_API_KEY=sk-ant-...`

### Step 6b: Estimate Effort (Optional)

Analyze source code complexity and generate accurate effort estimates.
**Updates `feature_user_story_map.toml` in-place and regenerates `TODO.md`:**

```bash
.odoo-sync/cli.py estimate-effort --execute
```

**How it works:**
- Creates timestamped backup of TOML before changes
- Reads from `studio/feature_user_story_map.toml` (the source of truth)
- Uses `source_location` in the TOML to find and analyze source files
- Computes complexity metrics: LOC, cyclomatic complexity, SQL queries, etc.
- Checks `enrich-status` field to determine if estimation should run
- **Writes complexity and time_estimate back to `feature_user_story_map.toml`**
- **Sets enrich-status to "done" after processing**
- **Regenerates `TODO.md` from the updated TOML**

**Options:**
- Omit `--execute` for dry-run (preview component count)
- `--config <file>` — Path to enricher configuration TOML file

**Re-triggering estimation:**
- Edit `feature_user_story_map.toml` and change `enrich-status` from "done" back to:
  - "refresh-all" (for both AI + effort)
  - "refresh-effort" (for effort estimation only)

**Outputs:** 
- `studio/feature_user_story_map.toml` (updated in-place with complexity/time_estimate)
- `studio/TODO.md` (regenerated)
- Backup: `studio/feature_user_story_map_YYYYMMDDHHMM.toml`

**Note:** Components without `source_location` in the TOML will get `complexity="unknown"` and `time_estimate="0:00"`.

### Step 6c: Run Full Enrichment (Optional)

Run both AI enrichment AND effort estimation in one command:

```bash
.odoo-sync/cli.py enrich-all --execute
```

**How it works:**
- Runs `enrich-stories` (Step 6a) first
- Then runs `estimate-effort` (Step 6b)
- Each step checks `enrich-status` to determine if processing should occur
- Each step updates `feature_user_story_map.toml` in-place
- Each step sets `enrich-status` to "done" after processing
- `TODO.md` is regenerated after each step

**Options:**
- Omit `--execute` for dry-run (preview what would be enriched)
- `--provider openai|anthropic` — Override AI provider from `.env`
- `--config <file>` — Path to enricher configuration TOML file

**Re-triggering enrichment:**
- Edit `feature_user_story_map.toml` and change `enrich-status` from "done" back to:
  - "refresh-all" (for both AI + effort)
  - "refresh-stories" (for AI enrichment only)
  - "refresh-effort" (for effort estimation only)

**Outputs:** 
- `studio/feature_user_story_map.toml` (updated in-place with AI descriptions + complexity/time)
- `studio/TODO.md` (regenerated)
- Backup: `studio/feature_user_story_map_YYYYMMDDHHMM.toml`

**⚠️ Requirements:**
- **AI API key required** - Must be set in `.env` file:
  - For OpenAI: `OPENAI_API_KEY=sk-...`
  - For Anthropic: `ANTHROPIC_API_KEY=sk-ant-...`

### Step 6d: Update HTML Tables in Odoo (Optional)

Regenerate HTML tables in Odoo task descriptions without running AI or modifying the TOML file:

```bash
.odoo-sync/cli.py update-task-tables --execute
```

**Use case:** After manually editing complexity/time estimates in `feature_user_story_map.toml`, refresh the HTML tables displayed in Odoo task descriptions to reflect the updated values.

**How it works:**
- Reads complexity and time estimate data from `studio/feature_user_story_map.toml`
- Fetches timesheet actuals from Odoo for comparison tables
- Regenerates HTML tables (effort breakdown, time estimates, complexity badges)
- Updates Odoo task descriptions with new HTML
- **No AI calls are made**
- **No changes are written to the TOML file**

**Options:**
- Omit `--execute` for dry-run (preview what would be updated)
- `--features "Feature1" "Feature2"` — Update specific features only (default: all features)

**Examples:**
```bash
# Dry-run: preview what would be updated
.odoo-sync/cli.py update-task-tables

# Update all features and user stories
.odoo-sync/cli.py update-task-tables --execute

# Update specific features only
.odoo-sync/cli.py update-task-tables --features "Ropeworx Sales" "Stock Management" --execute
```

**Outputs:** 
- Odoo task descriptions (updated HTML only)
- No TOML changes
- No backups created

**⚠️ Requirements:**
- Odoo connection configured (uses Development Odoo instance)
- Features and user stories must have valid `task_id` values in the TOML

### Step 6: Sync with Odoo

Sync `feature_user_story_map.toml` to Odoo tasks (creates tasks for features and user stories):

```bash
.odoo-sync/cli.py sync --execute
```

**How the sync command works:**
- Reads `studio/feature_user_story_map.toml`
- For each feature with `task_id = 0`: creates an Odoo task
- For each user story with `task_id = 0`: creates an Odoo subtask (linked to parent feature task)
- Updates `feature_user_story_map.toml` with the created task IDs
- Creates tags in Odoo if they don't exist
- All new tasks are placed in the "Backlog" stage

**Options:**
- Omit `--execute` for dry-run (validates Odoo connectivity only)

## Command Reference

### Core Workflow Commands

| Command | Description | When to Use |
|---------|-------------|-------------|
| `init` | Initialize configuration (interactive setup) | Once during initial setup |
| `extract` | Extract Studio customizations from Implementation Odoo | Step 1 (database source only) |
| `generate-feature-user-story-map` | Generate `studio/feature_user_story_map.toml` from extracted components | Step 3 (database source only) |
| `generate-modules` | Generate module structure and update `source_location` in TOML | Step 5 (database source only) |
| `sync` | Create Odoo tasks from `feature_user_story_map.toml` | Step 6 (task creation) |
| `status` | Display configuration and connection status | Anytime for diagnostics |

### Enricher Commands (Optional Post-Processing)

| Command | Description | When to Use | Requirements |
|---------|-------------|-------------|--------------|
| `enrich-stories` | AI-enrich user stories with roles and acceptance criteria | Step 6a (optional) | AI API key in `.env` |
| `estimate-effort` | Compute source-based complexity and effort estimates | Step 6b (optional) | None (code analysis only) |
| `enrich-all` | Run complete enrichment pipeline (stories + effort) | Step 6c (optional) | AI API key in `.env` |
| `update-task-tables` | Update HTML tables in Odoo task descriptions (no AI, no TOML changes) | Step 6d (optional) | None (reads from TOML, writes to Odoo) |

**Enricher Key Principles:**
- All enrichers read directly from `feature_user_story_map.toml` and use the `source_location` field to access source files
- No elaborate source scanning - just direct path lookup from TOML
- User story enrichment requires an AI API key (OpenAI or Anthropic) set in `.env`
  - Configure defaults in `.env`: `AI_PROVIDER` (openai/anthropic) and `AI_MODEL`
  - OpenAI default model: `gpt-4`
  - Anthropic default model: `claude-sonnet-4-5-20250929` (Claude Sonnet 4.5)
  - Use `anthropic-models` command to list all available Claude models
  - Override with `--provider` and `--model` flags if needed
- Effort estimation is pure code analysis and requires no API keys

**Important:** Use `--execute` flag to actually run the enrichers (default is dry-run preview).

### Utility Commands

| Command | Description | Usage |
|---------|-------------|-------|
| `anthropic-models` | List available Anthropic Claude models from API | `.odoo-sync/cli.py anthropic-models` |
| `compare-toml` | Compare two TOML files and produce a Markdown report | `.odoo-sync/cli.py compare-toml <file1.toml> <file2.toml> --output report.md` |
| `anthropic-models` | List available Anthropic Claude models from API | `.odoo-sync/cli.py anthropic-models` |

### Common Flags

- `--execute` / `-e` — Execute changes (default is dry-run for preview)
- `--debug` / `-d` — Show stack traces on error
- `--config-path` / `-c` — Override the `.odoo-sync` directory path
- `--help` — Show help for commands
- `--version` — Show CLI version

### Sync-Specific Flags

- `--no-confirm` / `-y` — Skip confirmation prompts
- `--conflict-resolution` — Choose strategy: `prefer_local`, `prefer_remote`, `prefer_newer`, `manual`

## Usage Examples

### Complete Workflow (Database Source)

```bash
# Step 1: Extract from database
.odoo-sync/cli.py extract --execute

# Step 2: ⚠️ REQUIRED - Edit and confirm module_model_map.toml
vim .odoo-sync/data/extraction-results/module_model_map.toml
# Review all model-to-module mappings before proceeding

# Step 3: Generate feature map
.odoo-sync/cli.py generate-feature-user-story-map --execute

# Step 4: ⚠️ REQUIRED - Edit and confirm feature_user_story_map.toml
vim studio/feature_user_story_map.toml
# Review all features, user stories, and mappings
# IMPORTANT: Remove any duplicate component references

# Step 5: Generate modules (updates source_location in TOML)
.odoo-sync/cli.py generate-modules --execute

# Step 6a (Optional): Enrich with AI descriptions (updates TOML in-place)
# ⚠️ Requires OPENAI_API_KEY or ANTHROPIC_API_KEY in .env
.odoo-sync/cli.py enrich-stories --execute
# Or dry-run first: .odoo-sync/cli.py enrich-stories

# Step 6b (Optional): Add complexity/time estimates (updates TOML in-place)
.odoo-sync/cli.py estimate-effort --execute
# Or dry-run first: .odoo-sync/cli.py estimate-effort

# To re-trigger: Edit TOML and change enrich-status from "done" to "refresh-effort"

# Step 6c (Optional): Run both AI + effort estimation together
.odoo-sync/cli.py enrich-all --execute

# Step 6d (Optional): Update HTML tables in Odoo (no AI, no TOML changes)
# Use case: After manually editing complexity/time in TOML
.odoo-sync/cli.py update-task-tables --execute
# Or for specific features:
.odoo-sync/cli.py update-task-tables --features "Feature Name" --execute

# Step 6: Sync with Odoo
.odoo-sync/cli.py sync --execute
```

### Abbreviated Workflow (Existing Module Source)

```bash
# Step 4: Generate feature map from existing source
.odoo-sync/cli.py generate-feature-user-story-map --execute

# Step 5: ⚠️ REQUIRED - Edit and confirm feature_user_story_map.toml
vim studio/feature_user_story_map.toml
# Review all features, user stories, and mappings before proceeding
# Ensure source_location is set for each component

# Step 6a (Optional): Enrich with AI descriptions
.odoo-sync/cli.py enrich-stories --execute

# Step 6b (Optional): Add complexity/time estimates
.odoo-sync/cli.py estimate-effort --execute

# Step 6c (Optional): Run both together
.odoo-sync/cli.py enrich-all --execute

# Step 6: Sync with Odoo
.odoo-sync/cli.py sync --execute
```

### Comparing Feature Maps

```bash
# Compare two versions of the feature map
.odoo-sync/cli.py compare-toml \
  studio/feature_user_story_map.toml \
  studio/feature_user_story_map.updated.toml \
  --output toml_comparison_report.md
```

## Troubleshooting

- Use `.odoo-sync/cli.py status` to verify configuration and connectivity
- Add `--debug` flag to see detailed error information
- Review dry-run output before using `--execute` to apply changes
- Check `.odoo-sync/data/extraction-results/` for intermediate files
  