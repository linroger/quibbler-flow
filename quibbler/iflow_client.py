"""
Client for interacting with iFlow API, compatible with Quibbler's needs.
Mimics portions of ClaudeSDKClient interface but uses iFlow (OpenAI compatible) API.
"""

import os
import json
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
        self.max_history_messages = 20 # Token efficiency optimization

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
        Unlike ClaudeSDKClient which might stream immediately,
        this prepares the request. The actual call happens in receive_response.
        """
        self.history.append({"role": "user", "content": prompt})

        # Token efficiency optimization: Prune history
        # Keep system prompt (index 0) and last N messages
        if len(self.history) > self.max_history_messages:
            system_msg = self.history[0] if self.history and self.history[0]["role"] == "system" else None
            # Keep last N-1 messages (to account for system msg)
            recent_msgs = self.history[-(self.max_history_messages - 1):]

            new_history = []
            if system_msg:
                new_history.append(system_msg)
            new_history.extend(recent_msgs)

            self.history = new_history
            logger.info(f"Pruned history to {len(self.history)} messages for token efficiency.")

    async def receive_response(self) -> AsyncGenerator[Union[AssistantMessage, Any], None]:
        """
        Stream the response from the API.
        Yields AssistantMessage objects containing TextBlocks.
        """
        if not self.api_key:
            logger.error("No iFlow API key found. Please login with iflow-cli.")
            yield AssistantMessage(content=[TextBlock(text="Error: No iFlow API key found. Please login with iflow-cli.")], model=self.model)
            return

        try:
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
                    logger.error(f"iFlow API Error: {response.status_code} - {error_text}")
                    yield AssistantMessage(content=[TextBlock(text=f"Error: iFlow API returned {response.status_code}")], model=self.model)
                    return

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

        except Exception as e:
            logger.error(f"Exception during iFlow API call: {e}")
            yield AssistantMessage(content=[TextBlock(text=f"Error: {str(e)}")], model=self.model)
