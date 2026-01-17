# Odoo Project Sync

A standalone Python utility that automates the synchronization of Odoo projects. It extracts Odoo Studio customizations from an implementation instance, converts them into structured user stories and actionable tasks, and keeps them synchronized with a development Odoo instance for project management. The codebase has been recently refactored to improve modularity, maintainability, and adherence to best practices while preserving all existing functionality.

## Features

- **Data Extraction**: Pulls Studio customizations (fields, views, server actions, automations, reports) from Odoo instances
- **Module Generation**: Creates Odoo module-style source files from extracted data
- **Feature Mapping**: Analyzes source files to map features to user stories
- **Task Generation**: Produces actionable ToDo lists from feature mappings (standalone output for human consumption)
- **AI Enrichment**: Enhances user stories with business context using OpenAI or Anthropic models
- **Effort Estimation**: Analyzes source code complexity for accurate time estimates
- **Bidirectional Sync**: Synchronizes feature_user_story_map.toml with Odoo project tasks
- **Comparison Tools**: Compares TOML files and generates Markdown reports
- **Interactive Setup**: Guided configuration wizard for Odoo instances

## Prerequisites

- Python 3.8 or later
- pip (Python package manager)
- Access to two Odoo instances:
  - **Implementation Odoo**: Read-only instance with Studio customizations
  - **Development Odoo**: Read/write instance for project management
- API keys for both Odoo instances (obtain from Settings → Integrations → Access Tokens)

## Installation

1. Clone or download this repository
2. Run the installation script in your target project directory:

   ```bash
   cd /path/to/your/project
   /path/to/odoo-project-sync/install.sh
   ```

3. Set up environment variables:

   ```bash
   cp .env.example .env
   # Edit .env to add your Odoo API keys
   ```

## Usage

The tool provides a CLI interface. After installation, use the project-local wrapper:

```bash
# Initialize configuration
./.odoo-sync/cli.py init

# Check status
./.odoo-sync/cli.py status
```

### Database-Based Workflow (from Odoo Studio)

```bash
# Extract customizations
./.odoo-sync/cli.py extract --execute

# Generate modules
./.odoo-sync/cli.py generate-modules --execute

# Generate feature-user story map
./.odoo-sync/cli.py generate-feature-user-story-map --execute

# Optional: Enrich with AI and estimate effort
./.odoo-sync/cli.py enrich-all --execute

# Optional: Update HTML tables in Odoo (after manual TOML edits)
./.odoo-sync/cli.py update-task-tables --execute

# Generate ToDo list (standalone output for human reference)
./.odoo-sync/cli.py generate-todo --execute

# Import features to Odoo
./.odoo-sync/cli.py import --execute

# Sync feature map with Odoo tasks (TOML ↔ Odoo)
./.odoo-sync/cli.py sync --execute
```

### Source-Based Workflow (from existing Odoo modules)

```bash
# Generate feature-user story map from source code
./.odoo-sync/cli.py generate-feature-user-story-map --source /path/to/odoo/modules --execute

# Optional: Enrich with AI and estimate effort
./.odoo-sync/cli.py enrich-all --execute

# Optional: Update HTML tables in Odoo (after manual TOML edits)
./.odoo-sync/cli.py update-task-tables --execute

# Generate ToDo list (standalone output for human reference)
./.odoo-sync/cli.py generate-todo --execute

# Import features to Odoo
./.odoo-sync/cli.py import --execute

# Sync feature map with Odoo tasks (TOML ↔ Odoo)
./.odoo-sync/cli.py sync --execute
```

## Workflow

### Database-Based Workflow
1. **Extract**: Pull data from Odoo → `extract.json`, `module_model_map.toml`
2. **User Review**: Edit `module_model_map.toml` as needed
3. **Generate Modules**: Create source files from extraction
4. **Generate Feature Map**: Analyze sources → `studio/feature_user_story_map.toml`
5. **User Review**: Edit `studio/feature_user_story_map.toml` as needed
6. **Generate ToDo** (optional): Create human-readable task list → `studio/TODO.md`
7. **Sync**: Import to Odoo and sync feature_user_story_map.toml ↔ Odoo tasks bidirectionally

### Source-Based Workflow
1. **Generate Feature Map**: Analyze existing source files → `studio/feature_user_story_map.toml`
2. **User Review**: Edit `studio/feature_user_story_map.toml` as needed
3. **Generate ToDo** (optional): Create human-readable task list → `studio/TODO.md`
4. **Sync**: Import to Odoo and sync feature_user_story_map.toml ↔ Odoo tasks bidirectionally

## Dependencies

- requests>=2.28.0
- pytest>=7.0.0 (for testing)
- pytest-mock>=3.10.0 (for testing)
- responses>=0.23.0 (for testing)

## Documentation

- [How-To Guide](Odoo_Sync_HowTo.md) - Detailed usage instructions

## Contributing

This project includes a comprehensive test suite. Run tests with:

```bash
pytest
```

## License

[Specify license if applicable]</content>
<parameter name="filePath">/home/gdt/aa-work/odoo-project-sync/README.md
