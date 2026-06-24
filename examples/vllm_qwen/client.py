"""Test client for the LLM Router. Supports HTTP and OpenAI SDK modes."""
from __future__ import annotations

import argparse
import json
import sys

import httpx


def chat_http(base_url: str, model: str, prompt: str) -> dict[str, object]:
    resp = httpx.post(
        f"{base_url}/chat/completions",
        json={"model": model,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=300.0,
    )
    resp.raise_for_status()
    return resp.json()


def chat_openai_sdk(base_url: str, model: str, prompt: str) -> str:
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key="not-needed")
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content or ""


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM Router test client")
    parser.add_argument("--base-url", default="http://localhost:8080/v1")
    parser.add_argument("--model", default="qwen-0.5b")
    parser.add_argument("--prompt", default="讲个关于 K8s 的冷笑话")
    parser.add_argument("--mode", choices=["http", "openai"], default="openai")
    args = parser.parse_args()

    try:
        if args.mode == "http":
            print(json.dumps(chat_http(args.base_url, args.model, args.prompt),
                             ensure_ascii=False, indent=2))
        else:
            print(chat_openai_sdk(args.base_url, args.model, args.prompt))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
