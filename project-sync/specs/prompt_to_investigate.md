# Investigation and Refactoring Guidelines Specification

## Purpose

This specification defines the standardized approach for conducting code investigations and refactoring tasks within the Odoo Project Sync utility. It establishes a methodology that prioritizes evidence-based analysis over assumptions, ensuring thorough understanding before making changes.

---

## ⚠️ MANDATORY Investigation Checklist

**STOP: Before drawing ANY conclusions, complete this checklist:**

- [ ] 1. Read the actual source code in `shared/python/` (not assumptions)
- [ ] 2. **`cd /home/gdt/awork/ropeworx`** - Enter the test environment folder
- [ ] 3. Read the test environment TOML: `cat studio/feature_user_story_map.toml`
- [ ] 4. Query Odoo using the test environment credentials (see examples below)
- [ ] 5. Compare Odoo data (task IDs, parent IDs, etc.) to TOML values
- [ ] 6. Run the CLI commands in the test environment to reproduce the issue

**If you skip any step, your investigation is incomplete.**

---

## 🚨 TEST ENVIRONMENT USAGE - MANDATORY

**You MUST use the test environment at `/home/gdt/awork/ropeworx` for all investigations.**

This is NOT optional. Do NOT rely solely on:
- Reading source code in the dev workspace
- Looking at the dev workspace's TOML files  
- Making assumptions about Odoo data

**You MUST run terminal commands in the test environment folder:**

```bash
# ALWAYS start by entering the test environment
cd /home/gdt/awork/ropeworx

# Run CLI commands from here
./.odoo-sync/cli.py sync --execute

# Read the actual TOML being used
cat studio/feature_user_story_map.toml

# Query Odoo with real credentials
cd .odoo-sync && export $(grep -v '^#' .env | xargs) && python3 << 'EOF'
# ... your query here
EOF
```

**The test environment has REAL data. The dev workspace does not.**

---

## Scope

This guideline applies to:
- All code investigation tasks within the Odoo Project Sync utility
- Refactoring activities across the Python codebase
- Analysis and modification of existing functionality
- Troubleshooting and debugging exercises
- Minor feature enhancement investigations

**Note**: If an investigation reveals the need for major feature enhancements, the AI must stop and prompt the user to create a separate, dedicated specification document for that feature rather than proceeding with implementation.

## Project Context

The Odoo Project Sync utility is a standalone Python application that automates the synchronization of Odoo projects. It performs the following core functions:
- Extracts Odoo Studio customizations from an implementation instance
- Converts customizations into structured user stories and actionable tasks
- Maintains synchronization with a development Odoo instance for project management

### Development Environment

- **Primary Development Location**: `/home/gdt/awork/odoo-project-sync`
- **Test Environment**: `/home/gdt/awork/ropeworx`
- **Test Environment Utility Instance**: `/home/gdt/awork/ropeworx.odoo-sync`

## Inputs

- Investigation or refactoring task description
- Specific code areas or modules to analyze
- User requirements or problem statements
- Existing codebase in `shared/python/`

## Outputs

- Evidence-based analysis findings
- Code modifications (if applicable)
- Updated documentation files (as needed):
  - `Odoo_Sync_HowTo.md`
  - `README.md`
  - `install.sh`
- Specification documents for complex changes

## Process Steps

### 1. Clarification Phase

**CRITICAL**: Before beginning any investigation or refactoring:
- **Do NOT proceed with assumptions** if the task requirements are unclear
- Ask targeted clarifying questions to ensure complete understanding
- Confirm the scope and expected outcomes
- Identify specific areas of concern or focus

### 2. Evidence-Based Analysis

**MANDATORY**: All investigations must be grounded in actual code review:
- **Read the actual source code** in `shared/python/` before drawing conclusions
- Trace execution paths through the codebase
- Identify dependencies and interconnections between modules
- Document findings based on code evidence, not assumptions

#### Test Environment Data Files

Always check these files in the **test environment** (not the dev workspace):

| File | Location | Purpose |
|------|----------|---------|
| Feature map TOML | `/home/gdt/awork/ropeworx/studio/feature_user_story_map.toml` | Actual task_ids and feature definitions |
| Odoo config | `/home/gdt/awork/ropeworx/.odoo-sync/odoo-instances.json` | Project ID, Odoo credentials |
| Environment vars | `/home/gdt/awork/ropeworx/.odoo-sync/.env` | API keys |

**Do NOT assume the dev workspace TOML matches the test environment TOML.**

### 3. Test Environment Validation

**REQUIRED**: Utilize the test environment for verification:
- Access the test environment at `/home/gdt/awork/ropeworx` for real-world data testing
- Verify behavior with already configured configs
- **NEVER make code changes** in `/home/gdt/awork/ropeworx.odoo-sync`
- Use the test environment for read-only verification and validation only
- when running python use *python3* not just python

#### How to Query Odoo from Test Environment

Use terminal commands to run Python scripts against the test environment:

```bash
# Navigate to test environment and load credentials
cd /home/gdt/awork/ropeworx/.odoo-sync
export $(grep -v '^#' .env | xargs)

# Example: Query a specific task from Odoo
python3 << 'EOF'
import json, sys, os
sys.path.insert(0, '/home/gdt/awork/odoo-project-sync/shared/python')
from odoo_client import OdooClient

client = OdooClient("https://www.ntz.co.za", "ntzc", "odoo@ntz.co.za", os.getenv("ODOO_NTZ_API_KEY"))
task = client.search_read('project.task', [('id', '=', YOUR_TASK_ID)], ['id', 'name', 'parent_id', 'project_id'])
print(json.dumps(task, indent=2, default=str))
EOF
```

#### ⚠️ STOP AND VERIFY: Sync Issues

Before concluding why a task wasn't synced:
1. **Get the task details from Odoo** (id, name, parent_id, project_id)
2. **Compare parent_id** against all feature task_ids in the TOML
3. **Verify project_id** matches the configured project in odoo-instances.json
4. **Check if task qualifies for import** - the sync only imports tasks that:
   - Have a parent_id (are subtasks)
   - Whose parent_id matches a feature's task_id in the TOML
   - Are not already in the TOML

### 4. Scope Assessment

**CRITICAL DECISION POINT**: Evaluate whether the investigation findings require major feature work:
- If the solution requires **major feature enhancements** (significant new functionality, architectural changes, or substantial refactoring):
  - **STOP implementation immediately**
  - Document the findings and requirements
  - **Prompt the user** to create a dedicated specification document for the feature enhancement
  - Recommend using the specification process for proper planning
- If the solution requires only **minor changes** (bug fixes, small improvements, limited refactoring):
  - Proceed to implementation phase

### 5. Implementation (if applicable)

If code changes are required and scope is appropriate:
- Implement changes only in the primary development location (`/home/gdt/awork/odoo-project-sync`)
- Follow existing code patterns and conventions
- Ensure changes are minimal and targeted
- DO NOT go off in a tangent with elaborate unnececary stuff
- DO NOT cater for backwards compatibuilty
- DO NOT duplicate code
  - If the code change results in code duplication, extract the code into utils and use the utils in the relevant places
- Validate changes against test environment
- **Do not implement major features** - these require separate specifications
- **DO NOT ruch off and start implementation**
  - Get Confirmation from the user FIRST
  - Present proposed code chages

### 5. Documentation Updates

**MANDATORY** for agent mode operations:
After completing investigation or refactoring, update the following files if relevant:
- `Odoo_Sync_HowTo.md` - User-facing how-to documentation
- `README.md` - Project overview and setup instructions
- `install.sh` - Installation script updates (if dependencies or setup changed)

### 6. Validation and Testing

- Verify all changes work correctly
- Test with real-world data from test environment
- Ensure no regressions are introduced
- Confirm documentation reflects current state

## Constraints

### Hard Rules

1. **No Assumptions**: Never proceed based on assumptions about code behavior - always verify by reading the source
2. **No Test Environment Modifications**: The test environment (`/home/gdt/awork/ropeworx.odoo-sync`) is read-only for validation purposes
3. **Clarification Required**: If task requirements are unclear, clarification is mandatory before proceeding
4. **Evidence-Based**: All findings and recommendations must be supported by code evidence
5. **Major Feature Specification Required**: If investigation reveals need for major feature enhancements, stop and prompt user to create a dedicated specification document - do not implement major features under investigation guidelines

### Best Practices

1. Read code in `shared/python/` to understand actual implementation
2. Use test environment data for realistic validation
3. Keep changes minimal and focused
4. Document reasoning and decisions
5. Update all relevant documentation

## Success Criteria

An investigation or refactoring task is considered successful when:

1. **Clarity Achieved**: Task requirements are fully understood before work begins
2. **Evidence-Based**: All conclusions are derived from actual code inspection, not assumptions
3. **Validated**: Changes (if any) are verified against test environment with real-world data
4. **Documented**: All relevant documentation files are updated to reflect changes
5. **Traceable**: Clear reasoning and evidence trails exist for all decisions
6. **No Regressions**: Existing functionality remains intact
7. **Professional Quality**: Code and documentation meet project standards

## Potential Source Files

Investigations and refactoring tasks may involve the following source files in `shared/python/`:

### Core Modules
- `sync_engine.py` - Main synchronization engine
- `odoo_client.py` - Odoo API client interactions
- `task_manager.py` - Task management functionality
- `config_manager.py` - Configuration handling
- `config.py` - Configuration definitions

### Extraction and Generation
- `source_extractors.py` - Source code extraction logic
- `extractor_factory.py` - Factory for extractors
- `odoo_source_scanner.py` - Odoo source scanning
- `model_generator.py` - Model generation
- `module_generator.py` - Module generation
- `view_generator.py` - View generation
- `xml_generator.py` - XML generation
- `qweb_resolver.py` - QWeb template resolution

### User Story and Feature Management
- `user_story_enricher.py` - User story enrichment
- `feature_detector.py` - Feature detection
- `feature_user_story_mapper.py` - Feature to user story mapping
- `feature_user_story_map_generator.py` - Map generation
- `map_generator.py` - General map generation
- `module_mapper.py` - Module mapping

### Analysis and Reporting
- `complexity_analyzer.py` - Code complexity analysis
- `effort_estimator.py` - Effort estimation
- `time_estimator.py` - Time estimation
- `report_generator.py` - Report generation
- `implementation_overview_generator.py` - Implementation overview

### Utilities
- `cli.py` - Command-line interface
- `utils.py` - Utility functions
- `file_manager.py` - File management
- `data_validation.py` - Data validation
- `error_handling.py` - Error handling
- `exceptions.py` - Custom exceptions
- `interfaces.py` - Interface definitions
- `component_ref_utils.py` - Component reference utilities
- `action_generator.py` - Action generation
- `enricher_config.py` - Enricher configuration
- `toml_compare.py` - TOML comparison utilities

### AI Integration
- `ai_providers/` - AI provider implementations

### Specialized Extractors
- `extractors/` - Specialized extraction modules

## Documentation Files

- `Odoo_Sync_HowTo.md` - User-facing documentation
- `README.md` - Project overview
- `install.sh` - Installation script
- `requirements.txt` - Python dependencies

## Configuration Files

- Test environment configs in `/home/gdt/awork/ropeworx`
- Template files in `templates/`
- Studio files in `studio/`

## The issue to investigate or refactor.

- why are there so many source_location = "" in the test env feature map