# Odoo Project Sync

This project automates the synchronization of Odoo projects through a sequential workflow of data extraction, module generation, feature mapping, task generation, and final synchronization with Odoo. It supports two primary sources of truth: an Odoo database with customizations (e.g., via Odoo Studio) or existing Odoo custom module source code.

## Prerequisites
- Access to an Odoo instance (for database-based workflows).
- Odoo custom module source files (for code-based workflows).
- Tools for JSON/TOML parsing and Odoo API interactions (e.g., Python scripts or Odoo CLI).

## Workflow Overview

The workflow consists of up to 7 steps, depending on the source of truth. Steps 1-3 are skipped if the source is existing module source code.

1. **Extract** (Database Source Only):  
   Extract relevant data from the Odoo database, including customizations.  
   Outputs: `extract.json` (raw data) and `module_model_map.toml` (initial mapping of modules to models).

2. **User Interaction** (Database Source Only):  
   Manually edit and verify `module_model_map.toml` to ensure accuracy.

3. **Generate Modules** (Database Source Only):  
   Use `extract.json` and `module_model_map.toml` to generate custom Odoo module-style source files (e.g., Python, XML, and TOML files).

4. **Generate Feature Map** (All Sources):  
   Analyze the source files (generated or existing) to create `feature_user_story_map.toml`, mapping features to user stories.

5. **User Interaction** (All Sources):  
   Manually edit and verify `feature_user_story_map.toml` for completeness.

6. **Generate ToDo**:  
   Consume `feature_user_story_map.toml` and source files to generate `ToDo.md`, including actionable tasks, estimated time, and complexity metrics.

7. **Sync**:  
   Use `ToDo.md` (and optionally the feature map and source files) to create articles and project tasks in Odoo via API calls.

This workflow ensures a structured, automated approach to syncing Odoo projects, minimizing manual errors and enabling traceability.