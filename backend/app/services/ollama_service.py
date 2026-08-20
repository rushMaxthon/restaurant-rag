import logging

import httpx
from fastapi import HTTPException

from app.config.settings import OLLAMA_BASE_URL, OLLAMA_MODEL

logger = logging.getLogger(__name__)

OLLAMA_GENERATE_URL = f"{OLLAMA_BASE_URL}/api/generate"
OLLAMA_TAGS_URL     = f"{OLLAMA_BASE_URL}/api/tags"

# Separate timeouts: connect fast, allow 120 s for the model to respond
TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=5.0)


async def chat(message: str) -> str:
    """Send a prompt to Ollama and return the generated text."""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": message,
        "stream": False,
    }

    logger.info("Chat request — model: %s", OLLAMA_MODEL)

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            logger.info("POST %s", OLLAMA_GENERATE_URL)
            response = await client.post(OLLAMA_GENERATE_URL, json=payload)
            response.raise_for_status()

    except httpx.ConnectError:
        logger.error("Cannot connect to Ollama at %s", OLLAMA_BASE_URL)
        raise HTTPException(
            status_code=502,
            detail="Cannot connect to Ollama. Make sure it is running: ollama serve",
        )

    except httpx.ReadTimeout:
        logger.error("Ollama read timeout after 120 s")
        raise HTTPException(
            status_code=504,
            detail=(
                "Ollama response timed out. "
                "The model may still be loading — try again in a few seconds."
            ),
        )

    except httpx.HTTPStatusError as e:
        logger.error("Ollama HTTP %s: %s", e.response.status_code, e.response.text)
        raise HTTPException(
            status_code=502,
            detail=f"Ollama error ({e.response.status_code}): {e.response.text}",
        )

    reply = response.json().get("response", "")
    logger.info("Response received — %d chars", len(reply))
    return reply


async def health() -> dict:
    """Check whether Ollama is reachable and list available models."""
    logger.info("Checking Ollama health")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            response = await client.get(OLLAMA_TAGS_URL)
            response.raise_for_status()

    except httpx.ConnectError:
        logger.warning("Ollama unreachable")
        return {"ollama": "unreachable", "models": []}

    except httpx.HTTPStatusError as e:
        logger.warning("Ollama tags error: %s", e.response.status_code)
        return {"ollama": "error", "detail": e.response.text, "models": []}

    models = [m["name"] for m in response.json().get("models", [])]
    logger.info("Ollama reachable — models: %s", models)
    return {"ollama": "reachable", "models": models}
