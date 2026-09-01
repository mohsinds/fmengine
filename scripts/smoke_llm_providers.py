#!/usr/bin/env python3
"""Live smoke test for Ollama / OpenAI / Anthropic via fmtrader LLM clients.

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
        MultiFrontierClient,
        OllamaLLMClient,
        OpenAILLMClient,
        default_router,
    )
    from fmtrader.config.settings import get_settings

    settings = get_settings()
    prompt = "Reply with exactly one word: pong"
    results: dict[str, dict] = {}

    print("=== Settings ===")
    print(f"ollama_url={settings.ollama_url}")
    print(f"openai_key_set={bool(settings.openai_api_key)}")
    print(f"anthropic_key_set={bool(settings.anthropic_api_key)}")

    checks = [
        (
            "ollama_7b",
            lambda: OllamaLLMClient(
                model="qwen2.5-coder:7b", base_url=settings.ollama_url
            ).complete(prompt, max_tokens=16),
        ),
        (
            "openai",
            lambda: OpenAILLMClient(api_key=settings.openai_api_key).complete(
                prompt, max_tokens=16
            ),
        ),
        (
            "anthropic",
            lambda: AnthropicLLMClient(api_key=settings.anthropic_api_key).complete(
                prompt, max_tokens=16
            ),
        ),
    ]

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
        except Exception as exc:  # noqa: BLE001 — smoke report
            results[name] = {"ok": False, "error": str(exc)}
            print("FAIL:", exc)

    print("\n=== default_router(stub=False) ===")
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
        )
        assert isinstance(router.frontier, MultiFrontierClient)
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
    return 0 if all(v.get("ok") for v in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
