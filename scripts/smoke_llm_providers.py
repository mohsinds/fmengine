#!/usr/bin/env python3
"""Live smoke test for configured LLM layers (Ollama / OpenAI / Anthropic / Cloud).

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
        unload_ollama_model,
    )
    from fmtrader.agents.routing import LLMRoutingConfig, large_agent_routing
    from fmtrader.config.settings import get_settings

    settings = get_settings()
    prompt = "Reply with exactly one word: pong"
    results: dict[str, dict] = {}

    print("=== Settings ===")
    print(f"ollama_url={settings.ollama_url}")
    print(f"ollama_cloud_url={settings.ollama_cloud_url}")
    print(f"ollama_api_key_set={bool(settings.ollama_api_key)}")
    print(f"openai_key_set={bool(settings.openai_api_key)}")
    print(f"anthropic_key_set={bool(settings.anthropic_api_key)}")
    print(f"langsmith_tracing={settings.langsmith_tracing}")

    routing = LLMRoutingConfig()
    print("\n=== Default llm_routing ===")
    print(json.dumps({k: v.model_dump() for k, v in routing.as_map().items()}, indent=2))
    print("\n=== large_agent_routing ===")
    print(
        json.dumps(
            {k: v.model_dump() for k, v in large_agent_routing().as_map().items()},
            indent=2,
        )
    )

    checks = [
        (
            "ollama_7b",
            lambda: OllamaLLMClient(
                model="qwen2.5-coder:7b", base_url=settings.ollama_url
            ).complete(prompt, max_tokens=16),
        ),
    ]

    # Large local models — soft if not pulled yet
    for tag, model in (
        ("ollama_gpt_oss_20b", "gpt-oss:20b"),
        ("ollama_qwen38_27b", "qwen3.8:27b"),
    ):
        checks.append(
            (
                tag,
                lambda m=model: OllamaLLMClient(
                    model=m, base_url=settings.ollama_url
                ).complete(prompt, max_tokens=16),
            )
        )

    # kimi cloud — soft-fail if unsigned
    checks.append(
        (
            "ollama_cloud_kimi",
            lambda: OllamaLLMClient(
                provider="ollama_cloud",
                model="kimi-k2.6:cloud",
                base_url=settings.ollama_cloud_url or settings.ollama_url,
                api_key=settings.ollama_api_key or "",
            ).complete(prompt, max_tokens=16),
        )
    )

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

    soft = {"ollama_gpt_oss_20b", "ollama_qwen38_27b", "ollama_cloud_kimi"}

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
            # Unload heavy locals between smokes
            if "20b" in name or "27b" in name:
                unload_ollama_model(
                    "gpt-oss:20b" if "20b" in name else "qwen3.8:27b",
                    base_url=settings.ollama_url,
                )
        except Exception as exc:  # noqa: BLE001
            results[name] = {"ok": False, "error": str(exc), "soft": name in soft}
            print(("SOFT FAIL:" if name in soft else "FAIL:"), exc)

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
            sweep_active=False,
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
        k: {
            "ok": v.get("ok"),
            **(
                {}
                if v.get("ok")
                else {"error": v.get("error"), "soft": v.get("soft", False)}
            ),
        }
        for k, v in results.items()
    }
    print(json.dumps(summary, indent=2))
    # Require ollama 7b + router; large/cloud optional (soft)
    required = ["ollama_7b", "router"]
    return 0 if all(results.get(k, {}).get("ok") for k in required) else 1


if __name__ == "__main__":
    sys.exit(main())
