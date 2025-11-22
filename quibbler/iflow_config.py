"""
Utilities for reading iFlow CLI configuration and authentication tokens.
"""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any

from quibbler.logger import get_logger

logger = get_logger(__name__)


def get_iflow_config_path() -> Path:
    """Get the path to the iFlow user settings file."""
    return Path.home() / ".iflow" / "settings.json"


def load_iflow_settings() -> Dict[str, Any]:
    """Load iFlow settings from the configuration file."""
    config_path = get_iflow_config_path()
    if not config_path.exists():
        logger.warning(f"iFlow settings file not found at {config_path}")
        return {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load iFlow settings: {e}")
        return {}


def get_iflow_auth_token() -> Optional[str]:
    """
    Retrieve the iFlow authentication token.

    Checks environment variables first, then settings.json.
    """
    # Check environment variables
    env_token = os.environ.get("IFLOW_API_KEY") or os.environ.get("IFLOW_apiKey")
    if env_token:
        return env_token

    # Check settings.json
    settings = load_iflow_settings()
    return settings.get("apiKey")


def get_iflow_base_url() -> str:
    """Get the iFlow base URL."""
    # Check environment variables
    env_url = os.environ.get("IFLOW_BASE_URL") or os.environ.get("IFLOW_baseUrl")
    if env_url:
        return env_url

    settings = load_iflow_settings()
    return settings.get("baseUrl", "https://apis.iflow.cn/v1")


def get_iflow_model() -> str:
    """Get the preferred iFlow model."""
    # Check environment variables
    env_model = os.environ.get("IFLOW_MODEL_NAME") or os.environ.get("IFLOW_modelName")
    if env_model:
        return env_model

    settings = load_iflow_settings()
    return settings.get("modelName", "Qwen3-Coder")
