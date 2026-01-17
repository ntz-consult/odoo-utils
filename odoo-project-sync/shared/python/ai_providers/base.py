"""Base classes and interfaces for AI providers.

Defines the abstract interface that all AI providers must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class AIProviderError(Exception):
    """Base exception for AI provider errors."""
    
    def __init__(self, message: str, provider: str = "unknown", retryable: bool = False):
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


@dataclass
class AIResponse:
    """Response from an AI provider."""
    
    content: str
    model: str
    provider: str
    usage: dict[str, int] = field(default_factory=dict)
    raw_response: Any = None
    
    @property
    def prompt_tokens(self) -> int:
        """Number of tokens in the prompt."""
        return self.usage.get("prompt_tokens", 0)
    
    @property
    def completion_tokens(self) -> int:
        """Number of tokens in the completion."""
        return self.usage.get("completion_tokens", 0)
    
    @property
    def total_tokens(self) -> int:
        """Total tokens used."""
        return self.usage.get("total_tokens", self.prompt_tokens + self.completion_tokens)


class AIProvider(ABC):
    """Abstract base class for AI providers.
    
    All AI providers must implement the generate() method to produce
    text completions from prompts.
    """
    
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ):
        """Initialize the AI provider.
        
        Args:
            api_key: API key for the provider (can also be set via env var)
            model: Model name to use
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens in response
            **kwargs: Additional provider-specific configuration
        """
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.config = kwargs
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g., 'openai', 'anthropic')."""
        pass
    
    @property
    @abstractmethod
    def default_model(self) -> str:
        """Return the default model for this provider."""
        pass
    
    @abstractmethod
    def generate(self, prompt: str, system_prompt: str | None = None) -> AIResponse:
        """Generate a completion from the given prompt.
        
        Args:
            prompt: The user prompt to send to the model
            system_prompt: Optional system prompt for context
            
        Returns:
            AIResponse with the generated content
            
        Raises:
            AIProviderError: If the API call fails
        """
        pass
    
    def get_model(self) -> str:
        """Get the model to use, falling back to default if not set."""
        return self.model or self.default_model
    
    def validate_api_key(self) -> None:
        """Validate that an API key is configured.
        
        Raises:
            AIProviderError: If no API key is set
        """
        if not self.api_key:
            raise AIProviderError(
                f"No API key configured for {self.provider_name}. "
                f"Set via constructor or environment variable.",
                provider=self.provider_name
            )
