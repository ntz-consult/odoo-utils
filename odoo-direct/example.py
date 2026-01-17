#!/usr/bin/env python3
"""
Example: Update res.partner records where name starts with 'G'
"""

from odoo_direct import odoo

# Search for partners starting with "G"
partners = odoo.search_read('res.partner', [('name', '=like', 'G%')], ['name'])

print(f"Found {len(partners)} partners")

# Update each partner's name (one request per partner - necessary since each has different name)
for partner in partners:
    new_name = partner['name'] + ' ~ Goog Going'
    odoo.write('res.partner', [partner['id']], {'name': new_name})

print("Done!")
