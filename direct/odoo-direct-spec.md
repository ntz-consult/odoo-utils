# odoo-direct Specification

## Purpose

Create a minimal, lightweight utility for any Odoo project that enables direct RPC-based read/write access to an Odoo database from local Python scripts. This utility will reside in a `.odoo-direct` folder within any Odoo project and provide the simplest possible setup for connecting to Odoo instances.

## Scope

- Minimal configuration system using environment variables or a simple JSON configuration file
- Lightweight Odoo JSON-RPC client for read and write operations
- Simple authentication mechanism using API keys
- Utility functions for common Odoo operations (search, read, write, create, unlink)
- No complex features like sync, conflict resolution, or project management
- Single instance support (no multi-instance management)
- Self-contained in `.odoo-direct` folder

## Inputs

- Odoo instance credentials:
  - URL (e.g., https://mycompany.odoo.com)
  - Database name
  - Username (email)
  - API key or password
- Configuration method: `.env` file or simple JSON config
- Python scripts that need to interact with Odoo

## Outputs

- Functional Odoo RPC client accessible from any Python script in the project
- Simple API for:
  - Authenticating with Odoo
  - Reading records (search_read, read)
  - Writing records (write, create, unlink)
  - Executing model methods
- Basic error handling and logging
- Simple usage examples/documentation

## Architecture

### Directory Structure
```
.odoo-direct/
├── __init__.py           # Makes it a Python package
├── client.py             # Minimal Odoo RPC client
├── config.py             # Configuration loader
├── config.json.example   # Example JSON config
└── README.md             # Usage documentation
```

### Core Components

#### 1. Configuration System (`config.py`)
- **Purpose**: Load connection details from simple JSON file
- **Configuration**: Simple `config.json` in `.odoo-direct/` folder:
  ```json
  {
    "url": "https://mycompany.odoo.com",
    "database": "my_database",
    "username": "user@example.com",
    "api_key": "your_api_key_here"
  }
  ```
- **Advantages**: Uses built-in `json` module - ZERO external dependencies
- **Features**:
  - Single function to load config: `get_config()`
  - Loads from `.odoo-direct/config.json`
  - Basic validation of required fields
  - Clear error messages if config is missing

#### 2. Odoo Client (`client.py`)
- **Purpose**: Minimal JSON-RPC client for Odoo communication
- **Based on**: `/home/gdt/awork/odoo-project-sync/shared/python/odoo_client.py`
- **Simplified Features**:
  - Authenticate with Odoo and cache UID
  - JSON-RPC /jsonrpc endpoint support (Odoo 14+)
  - Core CRUD operations:
    - `search(model, domain, limit, offset, order)`
    - `search_read(model, domain, fields, limit, offset, order)`
    - `read(model, ids, fields)`
    - `write(model, ids, values)`
    - `create(model, values)`
    - `unlink(model, ids)`
    - `execute_kw(model, method, args, kwargs)` - for any other method
  - Basic error handling
  - Request timeout configuration
- **Removed Complexity**:
  - No read_only mode enforcement (trust the user)
  - No legacy XML-RPC support
  - No interface/protocol abstractions
  - No complex error handler decorators
- **Key Methods**:
  ```python
  client = OdooClient.from_config()  # Load from config.json
  
  # Search and read
  records = client.search_read('res.partner', [('is_company', '=', True)], ['name', 'email'])
  
  # Create
  partner_id = client.create('res.partner', {'name': 'New Partner', 'email': 'new@example.com'})
  
  # Write
  client.write('res.partner', [partner_id], {'phone': '+1234567890'})
  
  # Delete
  client.unlink('res.partner', [partner_id])
  
  # Custom method
  result = client.execute_kw('account.move', 'action_post', [[move_id]])
  ```

#### 3. Package Initialization (`__init__.py`)
- **Purpose**: Make `.odoo-direct` importable as a Python package
- **Exports**:
  - `OdooClient` class
  - `get_config()` function
  - Simple usage example in docstring

#### 4. Documentation (`README.md`)
- **Purpose**: Quick start guide for using odoo-direct
- **Contents**:
  - Installation/setup steps
  - Configuration options (`.env` vs `config.json`)
  - Basic usage examples
  - Common patterns (search, create, update, delete)
  - Troubleshooting tips

## Implementation Plan

### Step 1: Setup Directory Structure
- Create `.odoo-direct/` folder in project root
- Create empty Python files: `__init__.py`, `client.py`, `config.py`
- Create example files: `.env.example`, `config.json.example`, `README.md`

### Step 2: Implement Configuration Loader (`config.py`)
- Create simple dataclass or dict for config
- Implement JSON config loader using built-in `json` module
- Create `get_config()` function that:
  - Loads from `.odoo-direct/config.json`
  - Raises clear error if file doesn't exist
  - Validates required fields (url, database, username, api_key)

### Step 3: Implement Odoo Client (`client.py`)
- Extract minimal client from `/home/gdt/awork/odoo-project-sync/shared/python/odoo_client.py`
- Remove all unnecessary complexity:
  - No read_only enforcement
  - No protocol interfaces
  - No complex error handling decorators
  - No legacy XML-RPC support
- Implement core methods:
  - `__init__(url, database, username, api_key, timeout=30)`
  - `from_config()` class method - loads from config.json
  - `authenticate()` - get and cache UID
  - `_jsonrpc(service, method, args)` - low-level RPC call
  - `execute_kw(model, method, args, kwargs)` - generic method executor
  - Convenience methods: `search()`, `search_read()`, `read()`, `write()`, `create()`, `unlink()`
- Basic error handling:
  - Connection errors
  - Authentication errors
  - Odoo API errors
- Request timeout support

### Step 4: Wire Up Package (`__init__.py`)
- Import and expose `OdooClient`
- Import and expose `get_config`
- Add module docstring with quick example

### Step 5: Create Documentation (`README.md`)
- Write setup instructions
- Document both config methods
- Provide usage examples for common operations:
  - Connecting to Odoo
  - Searching records
  - Reading records
  - Creating records
  - Updating records
  - Deleting records
  - Calling custom methods
- Add troubleshooting section

### Step 6: Create Example Config
- Create `config.json.example` with placeholder values
- Add comments/instructions in JSON

## Dependencies

### Required Python Packages
- `requests` - for HTTP/JSON-RPC calls
- `json` - built-in Python module (no install needed)

### Minimal requirements.txt
```
requests>=2.28.0
```

## Configuration

**File location**: `.odoo-direct/config.json`

**Format**:
```json
{
  "url": "https://mycompany.odoo.com",
  "database": "my_database",
  "username": "user@example.com",
  "api_key": "your_api_key_here"
}
```

**Advantages**:
- Self-contained in `.odoo-direct`
- ZERO external dependencies (uses built-in `json` module)
- Simple and readable
- Easy to version control with placeholders

## Usage Examples

### Basic Connection and Query
```python
# Import from .odoo-direct
from odoo_direct import OdooClient

# Connect using config.json
client = OdooClient.from_config()

# Search and read partners
partners = client.search_read(
    'res.partner',
    [('is_company', '=', True)],
    ['name', 'email', 'phone'],
    limit=10
)

for partner in partners:
    print(f"{partner['name']}: {partner['email']}")
```

### Creating Records
```python
from odoo_direct import OdooClient

client = OdooClient.from_config()

# Create a new partner
partner_id = client.create('res.partner', {
    'name': 'New Company',
    'email': 'contact@newcompany.com',
    'is_company': True,
    'phone': '+1234567890'
})

print(f"Created partner with ID: {partner_id}")
```

### Updating Records
```python
from odoo_direct import OdooClient

client = OdooClient.from_config()

# Find partners to update
partner_ids = client.search('res.partner', [('email', '=', 'old@example.com')])

# Update their email
if partner_ids:
    client.write('res.partner', partner_ids, {
        'email': 'new@example.com'
    })
    print(f"Updated {len(partner_ids)} partner(s)")
```

### Deleting Records
```python
from odoo_direct import OdooClient

client = OdooClient.from_config()

# Search for test records
test_ids = client.search('res.partner', [('name', 'ilike', 'TEST')])

# Delete them
if test_ids:
    client.unlink('res.partner', test_ids)
    print(f"Deleted {len(test_ids)} test record(s)")
```

### Using Custom Methods
```python
from odoo_direct import OdooClient

client = OdooClient.from_config()

# Post an account move
move_ids = client.search('account.move', [('state', '=', 'draft')], limit=1)

if move_ids:
    result = client.execute_kw('account.move', 'action_post', [move_ids])
    print("Move posted successfully")
```

## Differences from odoo-project-sync

| Feature | odoo-project-sync | odoo-direct |
|---------|-------------------|-------------|
| **Purpose** | Full project sync with multiple instances, conflict resolution, time tracking | Simple RPC access to single instance |
| **Configuration** | Complex JSON with multiple instances, sync rules, filters | Simple `config.json` with 4 fields |
| **Instances** | Multiple instances (dev, prod, etc.) | Single instance only |
| **Read-only Mode** | Enforced at client level | No enforcement (user responsibility) |
| **Sync Features** | Yes (bidirectional sync, conflict resolution) | No |
| **Project Management** | Yes (tasks, time tracking, knowledge articles) | No |
| **Extraction Filters** | Yes | No |
| **API** | Complex with interfaces and protocols | Simple direct methods |
| **Dependencies** | Many (openai, anthropic, pytest, sphinx, etc.) | Minimal (requests, optional python-dotenv) |
| **File Count** | ~50+ files | ~5 files |
| **Lines of Code** | ~10,000+ | ~200-300 |

## Constraints

- **No Implementation**: This is a specification only, no code implementation at this stage
- **No Changes to odoo-project-sync**: Reference only, do not modify
- **Minimal Dependencies**: Only `requests` library (+ built-in `json` module)
- **Single Instance**: No multi-instance support
- **No Sync Logic**: Pure RPC client, no synchronization features
- **Self-Contained**: Everything in `.odoo-direct` folder
- **Simple Configuration**: Single `config.json` file with 4 required fields

## Success Criteria

- User can drop `.odoo-direct` folder into any Odoo project
- Configuration requires only 4 values in `config.json` (URL, database, username, API key)
- Connection to Odoo works with a single line: `client = OdooClient.from_config()`
- All basic CRUD operations (create, read, update, delete) work correctly
- Custom method execution works via `execute_kw()`
- Clear error messages for connection/authentication issues
- Complete README with copy-paste examples
- Only ONE external dependency: `requests` (built-in `json` module otherwise)
- Total implementation under 300 lines of code
- Works with Odoo 14+ (JSON-RPC endpoint)

## Security Considerations

- API keys should never be committed to version control
- `config.json` must be in `.gitignore`
- Provide `config.json.example` with placeholder values for version control
- Document security best practices in README

## Testing Considerations

While no tests are required for initial implementation, future testing should cover:
- Configuration loading from `config.json`
- Authentication success and failure
- All CRUD operations
- Custom method execution
- Error handling (connection errors, auth errors, API errors)
- Timeout handling

## Potential Source Files (from odoo-project-sync for reference)

These files from `/home/gdt/awork/odoo-project-sync` will serve as reference but will be greatly simplified:

1. `/home/gdt/awork/odoo-project-sync/shared/python/odoo_client.py` (lines 1-200)
   - Simplify authentication mechanism
   - Extract JSON-RPC implementation
   - Remove read-only enforcement
   - Remove interface abstractions
   - Keep core CRUD methods

2. `/home/gdt/awork/odoo-project-sync/shared/python/config.py` (lines 1-100)
   - Simplify to single instance config
   - Remove ProjectConfig, SyncConfig, ExtractionFilters
   - Keep only basic InstanceConfig equivalent

3. `/home/gdt/awork/odoo-project-sync/templates/odoo-instances.json.template`
   - Reference for JSON structure
   - Simplify to single instance without metadata

4. `/home/gdt/awork/odoo-project-sync/requirements.txt`
   - Extract only `requests` dependency

## Future Enhancements (Out of Scope)

These features are explicitly excluded from the initial specification but could be added later:
- Multi-instance support
- Read-only mode enforcement
- Batch operations optimization
- Connection pooling
- Retry logic
- Advanced logging
- CLI interface
- Type hints and mypy support
- Comprehensive test suite
- Integration with odoo-project-sync

## Notes

- This is intentionally minimal - a starting point for any project needing Odoo RPC access
- Users requiring advanced features (sync, conflict resolution, multi-instance) should use odoo-project-sync
- The goal is "works in 5 minutes" not "handles every edge case"
- Prefer simplicity over features
- Prefer explicit over implicit
- Prefer clear errors over silent failures
