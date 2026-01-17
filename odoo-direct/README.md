# odoo-direct

Minimal, lightweight utility for direct JSON-RPC access to Odoo databases.

## Quick Start

### 1. Install Dependencies

```bash
pip install requests
```

Or using the requirements file:

```bash
pip install -r .odoo-direct/requirements.txt
```

### 2. Configure

Copy the example config and fill in your credentials:

```bash
cp .odoo-direct/config.json.example .odoo-direct/config.json
```

Edit `.odoo-direct/config.json`:

```json
{
    "url": "https://mycompany.odoo.com",
    "database": "my_database",
    "username": "user@example.com",
    "api_key": "your_api_key_here"
}
```

> **Getting an API Key**: In Odoo, go to Settings → Users → Select your user → 
> Preferences tab → Account Security → API Keys → New API Key

### 3. Use

```python
from odoo_direct import odoo

# Search for partners starting with "G"
partners = odoo.search_read('res.partner', [('name', '=like', 'G%')], ['name'])

print(f"Found {len(partners)} partners")

# Update each partner's name
for partner in partners:
    new_name = partner['name'] + ' ~ Updated'
    odoo.write('res.partner', [partner['id']], {'name': new_name})

print("Done!")
```

## Usage Examples

### Search and Read Records

```python
from odoo_direct import odoo

# Search with domain filter
partners = odoo.search_read(
    'res.partner',
    [('is_company', '=', True), ('country_id.code', '=', 'US')],
    ['name', 'email', 'phone'],
    limit=20,
    order='name asc'
)

# Just get IDs
partner_ids = odoo.search(
    'res.partner',
    [('customer_rank', '>', 0)],
    limit=100
)

# Read specific records by ID
records = odoo.read('res.partner', [1, 2, 3], ['name', 'email'])

# Count records
total = odoo.search_count('res.partner', [('is_company', '=', True)])
print(f"Total companies: {total}")
```

### Create Records

```python
from odoo_direct import odoo

# Create a new partner
partner_id = odoo.create('res.partner', {
    'name': 'New Company LLC',
    'email': 'contact@newcompany.com',
    'is_company': True,
    'phone': '+1 555 123 4567',
    'street': '123 Main St',
    'city': 'New York',
    'zip': '10001',
})

print(f"Created partner with ID: {partner_id}")
```

### Update Records

```python
from odoo_direct import odoo

# Find partners to update
partner_ids = odoo.search('res.partner', [('email', '=', 'old@example.com')])

# Update them
if partner_ids:
    odoo.write('res.partner', partner_ids, {
        'email': 'new@example.com',
        'phone': '+1 555 999 8888'
    })
    print(f"Updated {len(partner_ids)} partner(s)")
```

### Delete Records

```python
from odoo_direct import odoo

# Find test records
test_ids = odoo.search('res.partner', [('name', 'ilike', 'TEST%')])

# Delete them
if test_ids:
    odoo.unlink('res.partner', test_ids)
    print(f"Deleted {len(test_ids)} test record(s)")
```

### Execute Custom Methods

```python
from odoo_direct import odoo

# Post a draft invoice
move_ids = odoo.search('account.move', [
    ('state', '=', 'draft'),
    ('move_type', '=', 'out_invoice')
], limit=1)

if move_ids:
    odoo.execute_kw('account.move', 'action_post', [move_ids])
    print("Invoice posted!")

# Call any model method
result = odoo.execute_kw(
    'res.partner',
    'name_search',
    ['Acme'],  # args
    {'limit': 5}  # kwargs
)
```

## API Reference

### OdooDirect Class

The main class that provides Odoo JSON-RPC access.

#### Constructor

```python
from odoo_direct import OdooDirect

client = OdooDirect(config_path=None, timeout=30)
```

**Parameters:**
- `config_path`: Path to config.json (default: same directory as odoo_direct.py)
- `timeout`: Request timeout in seconds (default: 30)

#### Global Instance

For convenience, a pre-configured global instance is available:

```python
from odoo_direct import odoo

# Ready to use immediately
partners = odoo.search_read('res.partner', [], ['name'])

#### Methods

| Method | Description |
|--------|-------------|
| `search(model, domain, limit, offset, order)` | Search for record IDs |
| `search_read(model, domain, fields, limit, offset, order)` | Search and read in one call |
| `read(model, ids, fields)` | Read records by ID |
| `create(model, vals)` | Create a new record |
| `write(model, ids, vals)` | Update existing records |
| `unlink(model, ids)` | Delete records |
| `search_count(model, domain)` | Count matching records |
| `execute_kw(model, method, args, kwargs)` | Execute any model method |
| `test_connection()` | Test connection and return info |

### Configuration

Configuration is stored in `config.json`:

| Field | Description |
|-------|-------------|
| `url` | Odoo instance URL (e.g., `https://mycompany.odoo.com`) |
| `database` | Database name |
| `username` | Your Odoo username (usually email) |
| `api_key` | Your Odoo API key |

## Error Handling

```python
from odoo_direct import odoo, OdooError, OdooAuthError, OdooConfigError

try:
    partners = odoo.search_read('res.partner', [], ['name'])
except OdooConfigError as e:
    print(f"Configuration error: {e}")
except OdooAuthError as e:
    print(f"Authentication failed: {e}")
except OdooError as e:
    print(f"Odoo error: {e}")
```

**Exception Hierarchy:**
- `OdooError` - Base exception for all Odoo-related errors
- `OdooAuthError` - Authentication failed
- `OdooConfigError` - Configuration file issues

## Security

⚠️ **Important**: Never commit `config.json` to version control!

Add to your `.gitignore`:

```
.odoo-direct/config.json
```

Only `config.json.example` (with placeholder values) should be committed.

## Requirements

- Python 3.7+
- `requests` library
- Odoo 14+ (uses JSON-RPC endpoint)

## Project Structure

```
.odoo-direct/
├── odoo_direct.py        # Main module with OdooDirect class
├── example.py            # Example usage script
├── config.json.example   # Example configuration
├── config.json           # Your actual config (git-ignored)
├── requirements.txt      # Python dependencies
└── README.md            # This file
```

## Troubleshooting

### "Authentication failed"

- Verify your username (email) is correct
- Make sure you're using an API key, not your password
- Check that the API key hasn't been revoked
- Verify the database name is correct

### "Cannot connect to..."

- Check the URL is correct and accessible
- Verify there's no firewall blocking the connection
- Try accessing the URL in a browser

### "Config file not found"

- Make sure you copied `config.json.example` to `config.json`
- Check you're running from the project root directory

## License

MIT License - Use freely in any project.
