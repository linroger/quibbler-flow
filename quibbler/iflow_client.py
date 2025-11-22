"""
Client for interacting with iFlow API, compatible with Quibbler's needs.
Mimics portions of ClaudeSDKClient interface but uses iFlow (OpenAI compatible) API.
"""

import os
import json
import asyncio
import httpx
from typing import AsyncGenerator, List, Optional, Any, Dict, Union
from dataclasses import dataclass, field

from claude_agent_sdk import AssistantMessage, TextBlock

from quibbler.logger import get_logger
from quibbler.iflow_config import get_iflow_auth_token, get_iflow_base_url, get_iflow_model

logger = get_logger(__name__)


class IflowClient:
    """
    A client for iFlow API that mimics the ClaudeSDKClient interface
    used by Quibbler, but talks to iFlow's OpenAI-compatible API.
    """

    def __init__(self, options: Any = None):
        self.api_key = get_iflow_auth_token()
        self.base_url = get_iflow_base_url()
        self.model = get_iflow_model()
        self.options = options
        self.history: List[Dict[str, Any]] = []

        # Configure pruning from options
        self.max_history_messages = 20
        self.smart_pruning = True

        if self.options and hasattr(self.options, "quibbler_config"):
            config = self.options.quibbler_config
            self.max_history_messages = config.max_history
            self.smart_pruning = config.smart_pruning
            logger.info(f"IflowClient configured with max_history={self.max_history_messages}, smart_pruning={self.smart_pruning}")

        if self.options and hasattr(self.options, "system_prompt"):
            self.history.append({"role": "system", "content": self.options.system_prompt})

        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=60.0
        )
        self._response_generator: Optional[AsyncGenerator] = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    async def query(self, prompt: str):
        """
        Send a user message to the conversation history.
        """
        self.history.append({"role": "user", "content": prompt})
        self._prune_history()

    def _prune_history(self):
        """Prune history for token efficiency."""
        if len(self.history) <= self.max_history_messages:
            return

        logger.info(f"Pruning history (current size: {len(self.history)})")

        # Identify key messages to preserve
        system_msg = None
        first_user_msg = None

        # Find system message (usually first)
        if self.history and self.history[0]["role"] == "system":
            system_msg = self.history[0]

        # Find first user message (if smart pruning is enabled)
        if self.smart_pruning:
            for msg in self.history:
                if msg["role"] == "user":
                    first_user_msg = msg
                    break

        # Calculate how many recent messages we can keep
        # Reserved slots: 1 for system (if exists) + 1 for first user (if exists and different)
        reserved_count = 0
        if system_msg: reserved_count += 1
        if first_user_msg and first_user_msg is not system_msg: reserved_count += 1

        keep_count = self.max_history_messages - reserved_count
        if keep_count < 1: keep_count = 1 # Always keep at least one recent message

        recent_msgs = self.history[-keep_count:]

        # Reconstruct history
        new_history = []
        if system_msg:
            new_history.append(system_msg)
        if first_user_msg and first_user_msg not in new_history and first_user_msg not in recent_msgs:
            new_history.append(first_user_msg)

        new_history.extend(recent_msgs)

        self.history = new_history
        logger.info(f"Pruned history to {len(self.history)} messages.")

    async def receive_response(self) -> AsyncGenerator[Union[AssistantMessage, Any], None]:
        """
        Stream the response from the API with retry logic.
        """
        if not self.api_key:
            logger.error("No iFlow API key found. Please login with iflow-cli.")
            yield AssistantMessage(content=[TextBlock(text="Error: No iFlow API key found. Please login with iflow-cli.")], model=self.model)
            return

        max_retries = 3
        retry_delay = 1.0

        for attempt in range(max_retries):
            try:
                async for chunk in self._stream_response():
                    yield chunk
                return # Success
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                logger.warning(f"API attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.error("All API retry attempts failed.")
                    yield AssistantMessage(content=[TextBlock(text=f"Error: API call failed after {max_retries} attempts: {str(e)}")], model=self.model)
            except Exception as e:
                logger.error(f"Unexpected error during API call: {e}")
                yield AssistantMessage(content=[TextBlock(text=f"Error: {str(e)}")], model=self.model)
                return

    async def _stream_response(self):
        """Internal helper to handle the actual streaming request."""
        async with self.client.stream(
            "POST",
            "/chat/completions",
            json={
                "model": self.model,
                "messages": self.history,
                "stream": True,
                "temperature": 0.7,
            },
        ) as response:
            if response.status_code != 200:
                error_text = await response.read()
                raise httpx.HTTPStatusError(
                    f"Status {response.status_code} - {error_text}",
                    request=response.request,
                    response=response
                )

            full_content = ""
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue

                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")

                    if content:
                        full_content += content
                        yield AssistantMessage(content=[TextBlock(text=content)], model=self.model)

                except json.JSONDecodeError:
                    pass

            # Update history with the full response
            self.history.append({"role": "assistant", "content": full_content})
