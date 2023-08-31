"""Slide GPT API

This module exposes the pipeline function to create a video from a prompt.
"""

from .main import Args, get_voices, pipeline

__all__ = ["pipeline", "Args", "get_voices"]
