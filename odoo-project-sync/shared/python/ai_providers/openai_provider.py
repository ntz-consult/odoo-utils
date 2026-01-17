"""OpenAI API provider implementation."""

import os
from typing import Any

from .base import AIProvider, AIProviderError, AIResponse


class OpenAIProvider(AIProvider):
    """OpenAI API provider for GPT models."""
    
    ENV_API_KEY = "OPENAI_API_KEY"
    
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ):
        """Initialize OpenAI provider.
        
        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Model to use (defaults to gpt-4)
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
        return "openai"
    
    @property
    def default_model(self) -> str:
        return "gpt-4"
    
    def _get_client(self) -> Any:
        """Get or create the OpenAI client."""
        if self._client is None:
            self.validate_api_key()
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key)
            except ImportError:
                raise AIProviderError(
                    "OpenAI package not installed. Run: pip install openai",
                    provider=self.provider_name
                )
        return self._client
    
    def generate(self, prompt: str, system_prompt: str | None = None) -> AIResponse:
        """Generate completion using OpenAI API.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            
        Returns:
            AIResponse with generated content
        """
        client = self._get_client()
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        try:
            response = client.chat.completions.create(
                model=self.get_model(),
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            
            content = response.choices[0].message.content or ""
            usage = {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
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
            retryable = "rate" in error_message.lower() or "timeout" in error_message.lower()
            raise AIProviderError(
                f"OpenAI API error: {error_message}",
                provider=self.provider_name,
                retryable=retryable
            ) from e
