"""
Client for interacting with iFlow API, compatible with Quibbler's needs.
Mimics portions of ClaudeSDKClient interface but uses iFlow (OpenAI compatible) API.
"""

import os
import json
import httpx
import asyncio
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

        # Dynamic Token Management Configuration
        # Default to no restriction (very high number) if not set, or use env var
        # User requested "no restrictions on the max tokens" but "auto-compaction... when 70-80% of limit"
        # We need a reasonable "limit" to calculate 80% of.
        # If the model has a known limit (e.g. 128k), we should ideally use that.
        # But for generic usage, we can default to a safe high value or let user configure it.
        # 128k tokens is a common modern context window.
        default_max_tokens = 128000

        env_max_tokens = os.environ.get("QUIBBLER_MAX_CONTEXT_TOKENS")
        self.max_context_tokens = int(env_max_tokens) if env_max_tokens else default_max_tokens

        # Compaction threshold (default 80%)
        env_threshold = os.environ.get("QUIBBLER_COMPACTION_THRESHOLD")
        self.compaction_threshold = float(env_threshold) if env_threshold else 0.8

        # Message length truncation (still good to have for safety against massive single messages)
        # But user said "no restrictions on max tokens", so we should probably relax this or remove it?
        # "Place no restrictions on the max tokens" likely refers to the CONVERSATION HISTORY limit I had (20 messages).
        # But huge single messages can still break things. I'll increase it significantly.
        self.max_message_length = 100000 # 100k chars ~ 25k tokens. Safe enough.

        if self.options and hasattr(self.options, "system_prompt"):
            self.history.append({"role": "system", "content": self.options.system_prompt})

        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=120.0  # Increased timeout
        )
        self._response_generator: Optional[AsyncGenerator] = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count (approx 4 chars per token)."""
        if not text:
            return 0
        return len(text) // 4

    def _get_history_token_count(self) -> int:
        """Calculate total estimated tokens in history."""
        total = 0
        for msg in self.history:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += self._estimate_tokens(content)
            elif isinstance(content, list):
                # Handle list content (e.g. multimodal or tool use blocks if we supported them fully)
                # For now assuming simple string content or stringifiable
                total += self._estimate_tokens(str(content))
        return total

    def _compact_history(self):
        """
        Compact history when usage exceeds threshold.
        Strategy: Keep system prompt. Prune oldest user/assistant messages until usage is safe (e.g. < 60%).
        """
        current_tokens = self._get_history_token_count()
        limit = self.max_context_tokens
        threshold = int(limit * self.compaction_threshold)

        if current_tokens < threshold:
            return

        logger.info(f"Token usage {current_tokens} exceeded threshold {threshold}. Compacting history...")

        # Target: Reduce to 60% to avoid frequent compaction
        target = int(limit * 0.6)

        # Separate system prompt
        system_msgs = [m for m in self.history if m["role"] == "system"]
        other_msgs = [m for m in self.history if m["role"] != "system"]

        # Calculate system tokens
        system_tokens = sum(self._estimate_tokens(m.get("content", "")) for m in system_msgs)

        # Available for others
        available = target - system_tokens
        if available < 0:
            logger.warning("System prompt is too large for target token count! Keeping as is.")
            return

        # Keep messages from the END until we fill 'available'
        kept_others = []
        current_count = 0

        # Iterate backwards
        for msg in reversed(other_msgs):
            msg_tokens = self._estimate_tokens(msg.get("content", ""))
            if current_count + msg_tokens <= available:
                kept_others.insert(0, msg)
                current_count += msg_tokens
            else:
                # Stop once we can't fit the next message
                # Note: This simply drops older messages.
                # A smarter approach might summarize, but that requires an LLM call which might recurse/complicate.
                # Dropping is standard "context window" behavior.
                break

        # Reconstruct history
        self.history = system_msgs + kept_others

        final_tokens = self._get_history_token_count()
        logger.info(f"Compaction complete. History reduced from {current_tokens} to {final_tokens} tokens ({len(self.history)} messages).")


    async def query(self, prompt: str):
        """
        Send a user message to the conversation history.
        """
        # Add new message (no truncation on input unless it's insane, handled by max_message_length check if needed)
        # But we verify max_message_length locally to avoid sending massive blobs if user wants protection.
        if len(prompt) > self.max_message_length:
             prompt = prompt[:self.max_message_length] + f"\n... [Truncated {len(prompt) - self.max_message_length} chars] ..."

        self.history.append({"role": "user", "content": prompt})

        # Trigger auto-compaction check
        self._compact_history()

    async def receive_response(self) -> AsyncGenerator[Union[AssistantMessage, Any], None]:
        """
        Stream the response from the API.
        Yields AssistantMessage objects containing TextBlocks.
        """
        if not self.api_key:
            logger.error("No iFlow API key found. Please login with iflow-cli.")
            yield AssistantMessage(content=[TextBlock(text="Error: No iFlow API key found. Please login with iflow-cli.")], model=self.model)
            return

        retries = 3
        backoff = 1.0

        for attempt in range(retries):
            try:
                # We do NOT pass max_tokens here unless configured, effectively "no restrictions" on output (up to provider limit)
                # OpenAI API has max_tokens param, but if omitted it often defaults to model max.

                async with self.client.stream(
                    "POST",
                    "/chat/completions",
                    json={
                        "model": self.model,
                        "messages": self.history,
                        "stream": True,
                        "temperature": 0.0,
                        # "max_tokens": ... # Omitted to allow full model capacity
                    },
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.read()
                        logger.error(f"iFlow API Error (Attempt {attempt+1}): {response.status_code} - {error_text}")
                        if attempt < retries - 1 and response.status_code in [429, 500, 502, 503, 504]:
                            await asyncio.sleep(backoff)
                            backoff *= 2
                            continue

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

                    # Check compaction again after response (so we are ready for next turn)
                    self._compact_history()

                    return # Success

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as e:
                 logger.error(f"Connection error (Attempt {attempt+1}): {e}")
                 if attempt < retries - 1:
                     await asyncio.sleep(backoff)
                     backoff *= 2
                     continue
                 yield AssistantMessage(content=[TextBlock(text=f"Error: Connection failed - {str(e)}")], model=self.model)
            except Exception as e:
                logger.error(f"Exception during iFlow API call: {e}")
                yield AssistantMessage(content=[TextBlock(text=f"Error: {str(e)}")], model=self.model)
                return
