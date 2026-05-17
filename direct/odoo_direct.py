#!/usr/bin/env python3
"""
Odoo-Direct - All-in-one Odoo connection
Configuration loading + JSON-RPC client in one file
"""

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
import requests


class OdooError(Exception):
    """Base Odoo error"""
    pass


class OdooAuthError(OdooError):
    """Authentication failed"""
    pass


class OdooConfigError(OdooError):
    """Configuration error"""
    pass


class OdooDirect:
    """Simple Odoo JSON-RPC client with built-in config loading."""
    
    def __init__(self, config_path=None, config=None, timeout=30):
        """Initialize from config dict, config file, or environment variables.
        
        Args:
            config_path: Path to config.json (default: same dir as this file)
            config: Configuration dict with keys: url, database, username, api_key
            timeout: Request timeout in seconds
        """
        cfg = {}
        
        if config is not None:
            cfg = dict(config)
        else:
            # Try config file
            if config_path is None:
                config_path = Path(__file__).parent / 'config.json'
            else:
                config_path = Path(config_path)
            
            if config_path.exists():
                try:
                    with open(config_path, 'r') as f:
                        cfg = json.load(f)
                except json.JSONDecodeError as e:
                    raise OdooConfigError(f"Invalid JSON: {e}")
        
        # Environment variables always override file/config values
        env_map = {
            'url': 'ODOO_DIRECT_URL',
            'database': 'ODOO_DIRECT_DB',
            'username': 'ODOO_DIRECT_USER',
            'api_key': 'ODOO_DIRECT_API_KEY',
        }
        for key, env_var in env_map.items():
            val = os.environ.get(env_var, '')
            if val:
                cfg[key] = val
        
        # Validate required fields
        required = ['url', 'database', 'username', 'api_key']
        missing = [f for f in required if not cfg.get(f)]
        if missing:
            raise OdooConfigError(f"Missing fields: {', '.join(missing)}")
        
        self.url = cfg['url'].rstrip('/')
        self.database = cfg['database']
        self.username = cfg['username']
        self.api_key = cfg['api_key']
        self.timeout = timeout
        
        self._uid = None
        self._request_id = 0
    
    @property
    def uid(self):
        """Get user ID, authenticate if needed"""
        if self._uid is None:
            self._authenticate()
        return self._uid
    
    def _next_id(self):
        """Get next JSON-RPC request ID"""
        self._request_id += 1
        return self._request_id
    
    def _jsonrpc(self, service, method, args):
        """Make JSON-RPC call"""
        endpoint = urljoin(self.url, '/jsonrpc')
        
        payload = {
            'jsonrpc': '2.0',
            'method': 'call',
            'params': {
                'service': service,
                'method': method,
                'args': args
            },
            'id': self._next_id()
        }
        
        try:
            response = requests.post(
                endpoint,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=self.timeout
            )
            response.raise_for_status()
        except requests.ConnectionError as e:
            raise OdooError(f"Cannot connect to {self.url}: {e}")
        except requests.Timeout:
            raise OdooError(f"Request timed out after {self.timeout}s")
        except requests.RequestException as e:
            raise OdooError(f"Request failed: {e}")
        
        try:
            result = response.json()
        except json.JSONDecodeError as e:
            raise OdooError(f"Invalid JSON response: {e}")
        
        if 'error' in result:
            error = result['error']
            message = error.get('data', {}).get('message') or error.get('message', str(error))
            raise OdooError(f"Odoo error: {message}")
        
        return result.get('result')
    
    def _authenticate(self):
        """Authenticate and get user ID"""
        try:
            uid = self._jsonrpc(
                'common',
                'authenticate',
                [self.database, self.username, self.api_key, {}]
            )
        except OdooError as e:
            raise OdooAuthError(f"Authentication failed: {e}")
        
        if not uid:
            raise OdooAuthError(
                f"Authentication failed for {self.username}@{self.database}. "
                "Check credentials and API key."
            )
        
        self._uid = uid
        return uid
    
    def _execute(self, model, method, args, kwargs=None):
        """Execute model method"""
        return self._jsonrpc(
            'object',
            'execute_kw',
            [self.database, self.uid, self.api_key, model, method, args, kwargs or {}]
        )
    
    def search(self, model, domain=None, limit=None, offset=0, order=None):
        """Search for record IDs"""
        kwargs = {}
        if limit is not None:
            kwargs['limit'] = limit
        if offset:
            kwargs['offset'] = offset
        if order:
            kwargs['order'] = order
        return self._execute(model, 'search', [domain or []], kwargs)
    
    def search_read(self, model, domain=None, fields=None, limit=None, offset=0, order=None):
        """Search and read records"""
        kwargs = {}
        if fields:
            kwargs['fields'] = fields
        if limit is not None:
            kwargs['limit'] = limit
        if offset:
            kwargs['offset'] = offset
        if order:
            kwargs['order'] = order
        return self._execute(model, 'search_read', [domain or []], kwargs)
    
    def read(self, model, ids, fields=None):
        """Read records by ID"""
        kwargs = {'fields': fields} if fields else {}
        return self._execute(model, 'read', [ids], kwargs)
    
    def create(self, model, vals):
        """Create a record"""
        return self._execute(model, 'create', [vals])
    
    def write(self, model, ids, vals):
        """Update records"""
        return self._execute(model, 'write', [ids, vals])
    
    def unlink(self, model, ids):
        """Delete records"""
        return self._execute(model, 'unlink', [ids])
    
    def search_count(self, model, domain=None):
        """Count matching records"""
        return self._execute(model, 'search_count', [domain or []])
    
    def execute_kw(self, model, method, args, kwargs=None):
        """Execute any model method"""
        return self._execute(model, method, args, kwargs)


# Create global instance (lazy — safe to import even without config)
_odoo_instance = None

def _get_odoo():
    global _odoo_instance
    if _odoo_instance is None:
        _odoo_instance = OdooDirect()
    return _odoo_instance


class _OdooProxy:
    """Proxy that delegates all attribute access to the lazy global instance."""
    
    def __getattr__(self, name):
        return getattr(_get_odoo(), name)
    
    def __setattr__(self, name, value):
        return setattr(_get_odoo(), name, value)


odoo = _OdooProxy()
