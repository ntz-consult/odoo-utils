"""Anthropic API provider implementation."""

import os
from typing import Any

from .base import AIProvider, AIProviderError, AIResponse


class AnthropicProvider(AIProvider):
    """Anthropic API provider for Claude models."""
    
    ENV_API_KEY = "ANTHROPIC_API_KEY"
    
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ):
        """Initialize Anthropic provider.
        
        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            model: Model to use (defaults to claude-3-5-sonnet-20241022)
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response
            **kwargs: Additional configuration
        """
        # Get API key from env if not provided
        api_key = api_key or os.environ.get(self.ENV_API_KEY)
        
        super().__init__(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
        
        self._client = None
    
    @property
    def provider_name(self) -> str:
        return "anthropic"
    
    @property
    def default_model(self) -> str:
        return "claude-3-5-sonnet-20241022"
    
    def _get_client(self) -> Any:
        """Get or create the Anthropic client."""
        if self._client is None:
            self.validate_api_key()
            try:
                from anthropic import Anthropic
                self._client = Anthropic(api_key=self.api_key)
            except ImportError:
                raise AIProviderError(
                    "Anthropic package not installed. Run: pip install anthropic",
                    provider=self.provider_name
                )
        return self._client
    
    def generate(self, prompt: str, system_prompt: str | None = None) -> AIResponse:
        """Generate completion using Anthropic API.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            
        Returns:
            AIResponse with generated content
        """
        client = self._get_client()
        
        try:
            # Anthropic uses a different message format
            kwargs = {
                "model": self.get_model(),
                "max_tokens": self.max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            
            # Anthropic's temperature must be between 0 and 1
            if self.temperature is not None:
                kwargs["temperature"] = min(1.0, max(0.0, self.temperature))
            
            if system_prompt:
                kwargs["system"] = system_prompt
            
            response = client.messages.create(**kwargs)
            
            # Extract text from content blocks
            content = ""
            for block in response.content:
                if hasattr(block, "text"):
                    content += block.text
            
            usage = {
                "prompt_tokens": response.usage.input_tokens if response.usage else 0,
                "completion_tokens": response.usage.output_tokens if response.usage else 0,
                "total_tokens": (
                    (response.usage.input_tokens if response.usage else 0) +
                    (response.usage.output_tokens if response.usage else 0)
                ),
            }
            
            return AIResponse(
                content=content,
                model=response.model,
                provider=self.provider_name,
                usage=usage,
                raw_response=response,
            )
            
        except Exception as e:
            error_message = str(e)
            retryable = "rate" in error_message.lower() or "overloaded" in error_message.lower()
            raise AIProviderError(
                f"Anthropic API error: {error_message}",
                provider=self.provider_name,
                retryable=retryable
            ) from e
