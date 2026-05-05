# Feature Implementation Prompt Specification

**Prompt:**

You are provided with a specification and plan in the attached file.

1. Analyze the content of the attached file thoroughly.
2. If there are any ambiguities, incomplete sections, or unclear requirements, ask targeted clarifying questions.
3. Wait until all your clarifying questions are answered.
4. Once all clarifications are resolved, implement the specification and plan as described in the attached file.

---

## Purpose

To provide a structured prompt template for analyzing a specification file, asking clarifying questions, and implementing new features within the Odoo Project Sync utility.

## Project Context

The Odoo Project Sync utility is a standalone Python application that automates the synchronization of Odoo projects. It performs the following core functions:
- Extracts Odoo Studio customizations from an implementation instance
- Converts customizations into structured user stories and actionable tasks
- Maintains synchronization with a development Odoo instance for project management

### Development Environment

- **Primary Development Location**: `/home/gdt/awork/odoo-project-sync`
- **Test Environment**: `/home/gdt/awork/ropeworx`
- **Test Environment Utility Instance**: `/home/gdt/awork/ropeworx/.odoo-sync`

---

## Scope

- Analysis of the target specification file's content
- Identification and documentation of ambiguities or unclear requirements
- Drafting clarifying questions as needed
- Implementation of new features as per the specification
- Validation against test environment with real-world data

## Inputs

- The attached file containing the specification and plan
- Any relevant context or requirements provided by stakeholders
- Existing codebase in `shared/python/`

## Outputs

- Updated specification and plan with clarifications incorporated
- The final implementation of the specification
- Updated documentation files (as needed):
  - `Odoo_Sync_HowTo.md`
  - `README.md`
  - `install.sh`

---

## Process Steps

### 1. Specification Analysis

- Read and understand the content of the target specification file
- Identify core concepts, requirements, and structure
- **Read the actual source code** in `shared/python/` to understand existing patterns
- Determine dependencies and interconnections between modules

### 2. Clarification Phase

**CRITICAL**: Before beginning implementation:
- **Do NOT proceed with assumptions** if requirements are unclear
- Identify ambiguous, incomplete, or unclear elements in the specification
- Ask targeted clarifying questions for stakeholders
- Confirm the scope and expected outcomes
- Document any assumptions made during analysis

### 3. Specification Refinement

- Transform the analyzed content and clarifications into a structured implementation plan
- Organize information into logical sections
- Ensure the plan is clear, actionable, and comprehensive
- **Get confirmation from the user BEFORE starting implementation**
- Present proposed code changes for approval

### 4. Implementation

Implement changes only in the primary development location (`/home/gdt/awork/odoo-project-sync`):
- Follow existing code patterns and conventions
- Ensure changes are targeted and well-structured
- **DO NOT go off on tangents with elaborate unnecessary additions**
- **DO NOT cater for backwards compatibility** (unless specified)
- **DO NOT duplicate code**
  - If the code change results in code duplication, extract the code into utils and use the utils in the relevant places
- When running Python, use `python3` not just `python`

### 5. Test Environment Validation

**REQUIRED**: Utilize the test environment for verification:
- Access the test environment at `/home/gdt/awork/ropeworx` for real-world data testing
- Verify behavior with already configured configs
- **NEVER make code changes** in `/home/gdt/awork/ropeworx/.odoo-sync`
- Use the test environment for read-only verification and validation only

#### Test Environment Data Files

| File | Location | Purpose |
|------|----------|---------|
| Feature map TOML | `/home/gdt/awork/ropeworx/studio/feature_user_story_map.toml` | Actual task_ids and feature definitions |
| Odoo config | `/home/gdt/awork/ropeworx/.odoo-sync/odoo-instances.json` | Project ID, Odoo credentials |
| Environment vars | `/home/gdt/awork/ropeworx/.odoo-sync/.env` | API keys |

#### How to Query Odoo from Test Environment

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

### 6. Documentation Updates

**MANDATORY**: After completing implementation, update the following files if relevant:
- `Odoo_Sync_HowTo.md` - User-facing how-to documentation
- `README.md` - Project overview and setup instructions
- `install.sh` - Installation script updates (if dependencies or setup changed)

### 7. Final Validation

- Verify all changes work correctly
- Test with real-world data from test environment
- Ensure no regressions are introduced
- Confirm documentation reflects current state

---

## Constraints

### Hard Rules

1. **No Assumptions**: Never proceed based on assumptions - always verify by reading the source code
2. **No Test Environment Modifications**: The test environment (`/home/gdt/awork/ropeworx/.odoo-sync`) is read-only for validation purposes
3. **Clarification Required**: If requirements are unclear, clarification is mandatory before proceeding
4. **User Confirmation**: Get explicit confirmation before starting implementation
5. **No Code Duplication**: Extract shared logic into utilities

### Best Practices

1. Read code in `shared/python/` to understand actual implementation patterns
2. Use test environment data for realistic validation
3. Keep changes focused on the specification
4. Document reasoning and decisions
5. Update all relevant documentation

---

## Potential Source Files

New features may involve the following source files in `shared/python/`:

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

---

## Success Criteria

An implementation is considered successful when:

1. **Clarity Achieved**: All requirements are fully understood before implementation begins
2. **User Approved**: Implementation plan was confirmed by user before coding started
3. **Validated**: Implementation is verified against test environment with real-world data
4. **Documented**: All relevant documentation files are updated to reflect changes
5. **No Regressions**: Existing functionality remains intact
6. **Professional Quality**: Code and documentation meet project standards
7. **No Duplication**: Shared logic is properly extracted into utilities