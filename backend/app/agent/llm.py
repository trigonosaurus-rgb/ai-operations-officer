"""LLM client factory.

We use OpenAI's Responses API: on current reasoning models (gpt-5.x) it is the only
API that allows function tools *and* reasoning together — the older Chat
Completions API rejects tools unless reasoning is switched off.
"""

from llama_index.llms.openai import OpenAIResponses

from app.config import Settings


class LLMConfigError(RuntimeError):
    pass


def build_llm(settings: Settings) -> OpenAIResponses:
    if settings.openai_api_key is None:
        raise LLMConfigError("OPENAI_API_KEY is not set. Copy .env.example to .env and add it.")
    effort = settings.llm_reasoning_effort
    return OpenAIResponses(
        model=settings.llm_model,
        api_key=settings.openai_api_key.get_secret_value(),
        temperature=settings.llm_temperature,  # dropped automatically for reasoning models
        reasoning_options={"effort": effort} if effort else None,
        store=False,  # don't keep customer conversations on OpenAI's side
        timeout=settings.llm_timeout_s,
        max_retries=settings.llm_max_retries,  # SDK retries 429/5xx with exponential backoff
    )
