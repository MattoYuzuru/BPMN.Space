"""Legacy import path kept while callers move to the generic OpenAI-compatible adapter."""

from app.llm.openai_compatible import DeepSeekPipeline, OpenAICompatiblePipeline

__all__ = ["DeepSeekPipeline", "OpenAICompatiblePipeline"]
