#!/usr/bin/env python3
"""Live smoke test for configured LLM layers (Ollama / OpenAI / Anthropic).

Run from repo root:
  uv run python scripts/smoke_llm_providers.py
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    from fmtrader.agents.budget import BudgetCaps
    from fmtrader.agents.ledger import CostLedger
    from fmtrader.agents.llm import (
        AnthropicLLMClient,
        OllamaLLMClient,
        OpenAILLMClient,
        default_router,
    )
    from fmtrader.agents.routing import LLMRoutingConfig
    from fmtrader.config.settings import get_settings

    settings = get_settings()
    prompt = "Reply with exactly one word: pong"
    results: dict[str, dict] = {}

    print("=== Settings ===")
    print(f"ollama_url={settings.ollama_url}")
    print(f"openai_key_set={bool(settings.openai_api_key)}")
    print(f"anthropic_key_set={bool(settings.anthropic_api_key)}")
    print(f"langsmith_tracing={settings.langsmith_tracing}")

    routing = LLMRoutingConfig()
    print("\n=== Default llm_routing ===")
    print(json.dumps({k: v.model_dump() for k, v in routing.as_map().items()}, indent=2))

    checks = [
        (
            "ollama_7b",
            lambda: OllamaLLMClient(
                model="qwen2.5-coder:7b", base_url=settings.ollama_url
            ).complete(prompt, max_tokens=16),
        ),
    ]
    if settings.openai_api_key:
        checks.append(
            (
                "openai",
                lambda: OpenAILLMClient(api_key=settings.openai_api_key).complete(
                    prompt, max_tokens=16
                ),
            )
        )
    if settings.anthropic_api_key:
        checks.append(
            (
                "anthropic",
                lambda: AnthropicLLMClient(api_key=settings.anthropic_api_key).complete(
                    prompt, max_tokens=16
                ),
            )
        )

    for name, fn in checks:
        print(f"\n=== {name} ===")
        try:
            text, pt, ct = fn()
            results[name] = {
                "ok": True,
                "text": (text or "")[:120],
                "prompt_tokens": pt,
                "completion_tokens": ct,
            }
            print(json.dumps(results[name], indent=2))
        except Exception as exc:  # noqa: BLE001
            results[name] = {"ok": False, "error": str(exc)}
            print("FAIL:", exc)

    print("\n=== default_router(stub=False, all-local routing) ===")
    try:
        router = default_router(
            caps=BudgetCaps(
                per_campaign_usd=8.0,
                per_day_usd=8.0,
                per_generation_usd=1.0,
                openai_usd=3.0,
                anthropic_usd=5.0,
            ),
            ledger=CostLedger(),
            stub=False,
            campaign_id="smoke-llm-providers",
            sweep_active=True,
            routing=routing,
        )
        h = router.complete(
            prompt,
            purpose="hypothesize",
            campaign_id="smoke-llm-providers",
            generation=0,
            max_tokens=16,
        )
        c = router.complete(
            prompt,
            purpose="critique",
            campaign_id="smoke-llm-providers",
            generation=0,
            max_tokens=16,
        )
        r = router.complete(
            prompt,
            purpose="report",
            campaign_id="smoke-llm-providers",
            generation=0,
            max_tokens=16,
        )
        results["router"] = {
            "ok": True,
            "hypothesize": f"{h['provider']}:{h['model']}",
            "critique": f"{c['provider']}:{c['model']}",
            "report": f"{r['provider']}:{r['model']}",
        }
        print(json.dumps(results["router"], indent=2))
    except Exception as exc:  # noqa: BLE001
        results["router"] = {"ok": False, "error": str(exc)}
        print("FAIL:", exc)

    print("\n=== SUMMARY ===")
    summary = {
        k: {"ok": v.get("ok"), **({} if v.get("ok") else {"error": v.get("error")})}
        for k, v in results.items()
    }
    print(json.dumps(summary, indent=2))
    # Require ollama + router; cloud optional
    required = ["ollama_7b", "router"]
    return 0 if all(results.get(k, {}).get("ok") for k in required) else 1


if __name__ == "__main__":
    sys.exit(main())
