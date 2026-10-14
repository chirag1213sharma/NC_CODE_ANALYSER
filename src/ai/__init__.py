"""
NC Code Analyser - AI Module
"""

from src.ai.gemini_classifier import OllamaClassifier, OllamaClassifierSync

# Backward-compatible aliases
GeminiClassifier = OllamaClassifier
GeminiClassifierSync = OllamaClassifierSync

__all__ = [
    "OllamaClassifier",
    "OllamaClassifierSync",
    "GeminiClassifier",
    "GeminiClassifierSync",
]
