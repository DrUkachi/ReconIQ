"""Two-turn provider check using harmless prompts; no Slack messages are sent."""
from app.core.config import get_settings
from app.services.llm.openrouter import OpenRouterClient, OpenRouterUnavailable


def main():
    client = OpenRouterClient()
    messages = [{"role": "user", "content": "How many r letters are in the word strawberry? Reply briefly."}]
    try:
        first = client.complete(messages)
        messages.extend([first, {"role": "user", "content": "Are you sure? Check and reply briefly."}])
        second = client.complete(messages)
    except OpenRouterUnavailable as exc:
        print("OpenRouter check failed:", str(exc))
        return 1
    print("Model:", get_settings().openrouter_model)
    print("First answer:", first["content"])
    print("Follow-up answer:", second["content"])
    print("Reasoning metadata returned:", "reasoning_details" in first)
    print("Follow-up preserves any returned reasoning metadata unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
