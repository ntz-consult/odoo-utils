#!/usr/bin/env python3
"""Query Anthropic API to list available models."""

import os
import sys
from pathlib import Path

# Load environment variables
from utils import load_dotenv, find_project_root

project_root = find_project_root(Path.cwd())
if project_root:
    load_dotenv(project_root)

def list_anthropic_models():
    """List all available Anthropic models using the API."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not found in environment variables")
        print("Please set it in your .env file or run:")
        print("  ANTHROPIC_API_KEY=your-key python3 shared/python/list_anthropic_models.py")
        return
    
    try:
        from anthropic import Anthropic
    except ImportError:
        print("Error: anthropic package not installed")
        print("Run: pip install anthropic")
        return
    
    try:
        client = Anthropic(api_key=api_key)
        
        # List all available models
        print("Querying Anthropic API for available models...")
        print()
        
        response = client.models.list()
        
        if hasattr(response, 'data') and response.data:
            print(f"Found {len(response.data)} models:")
            print()
            for model in response.data:
                print(f"  • {model.id}")
                if hasattr(model, 'display_name'):
                    print(f"    Display Name: {model.display_name}")
                if hasattr(model, 'created_at'):
                    print(f"    Created: {model.created_at}")
                print()
        else:
            print("No models found or API doesn't support listing models")
            print()
            print("Common models you can try:")
            print("  • claude-3-5-sonnet-20241022")
            print("  • claude-3-5-sonnet-20240620")
            print("  • claude-3-opus-20240229")
            print("  • claude-3-sonnet-20240229")
            print("  • claude-3-haiku-20240307")
            
    except Exception as e:
        print(f"Error querying API: {e}")
        print()
        print("This might mean the API doesn't support model listing.")
        print()
        print("Common Claude models (as of early 2024):")
        print("  • claude-3-5-sonnet-20241022")
        print("  • claude-3-5-sonnet-20240620")
        print("  • claude-3-opus-20240229")
        print("  • claude-3-sonnet-20240229")
        print("  • claude-3-haiku-20240307")
        print()
        print("Try these models or check Anthropic documentation:")
        print("https://docs.anthropic.com/en/docs/about-claude/models")

if __name__ == "__main__":
    list_anthropic_models()
