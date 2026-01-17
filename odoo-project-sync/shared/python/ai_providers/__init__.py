"""AI Provider abstraction for user story generation.

Supports multiple LLM providers (OpenAI, Anthropic) with a common interface.
"""

from .base import AIProvider, AIProviderError, AIResponse
from .openai_provider import OpenAIProvider
from .anthropic_provider import AnthropicProvider

__all__ = [
    "AIProvider",
    "AIProviderError", 
    "AIResponse",
    "OpenAIProvider",
    "AnthropicProvider",
    "get_provider",
    "get_available_models",
    "validate_model",
]


def get_available_models(provider_name: str) -> list[str]:
    """Get list of commonly used models for a provider.
    
    Args:
        provider_name: Name of the provider ('openai' or 'anthropic')
        
    Returns:
        List of model names
        
    Raises:
        ValueError: If provider_name is not recognized
    """
    models = {
        "openai": [
            "gpt-4o",
            "gpt-4",
            "gpt-4-turbo",
            "gpt-3.5-turbo",
        ],
        "anthropic": [
            "claude-3-5-sonnet-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
        ],
    }
    
    provider_models = models.get(provider_name.lower())
    if provider_models is None:
        raise ValueError(f"Unknown AI provider: {provider_name}. Supported: {list(models.keys())}")
    
    return provider_models


def validate_model(provider_name: str, model: str) -> tuple[bool, str]:
    """Validate if a model name is valid for a provider.
    
    Args:
        provider_name: Name of the provider ('openai' or 'anthropic')
        model: Model name to validate
        
    Returns:
        Tuple of (is_valid, message)
    """
    try:
        available = get_available_models(provider_name)
    except ValueError as e:
        return False, str(e)
    
    # Check exact match
    if model in available:
        return True, "Valid model"
    
    # Check partial match (e.g., "gpt-4" matches "gpt-4-0613")
    for available_model in available:
        if model in available_model or available_model.startswith(model):
            return True, f"Valid model (matches {available_model})"
    
    # Not found
    return False, f"Unknown model '{model}' for {provider_name}. Available models: {', '.join(available)}"


def get_provider(provider_name: str, **kwargs) -> AIProvider:
    """Factory function to get an AI provider by name.
    
    Args:
        provider_name: Name of the provider ('openai' or 'anthropic')
        **kwargs: Provider-specific configuration
        
    Returns:
        Configured AIProvider instance
        
    Raises:
        ValueError: If provider_name is not recognized
    """
    providers = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
    }
    
    provider_class = providers.get(provider_name.lower())
    if not provider_class:
        raise ValueError(f"Unknown AI provider: {provider_name}. Supported: {list(providers.keys())}")
    
    return provider_class(**kwargs)
