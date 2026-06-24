"""Concurrent load test for the LLM Router."""
from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx


async def one_request(client: httpx.AsyncClient, base_url: str, model: str,
                      prompt: str, idx: int) -> dict[str, object]:
    t0 = time.time()
    try:
        r = await client.post(
            f"{base_url}/chat/completions",
            json={"model": model,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=300.0,
        )
        elapsed = time.time() - t0
        body = r.json() if r.status_code == 200 else {}
        return {
            "idx": idx, "status": r.status_code, "latency_s": elapsed,
            "tokens": body.get("usage", {}).get("completion_tokens", 0),
        }
    except Exception as exc:
        return {"idx": idx, "status": -1,
                "latency_s": time.time() - t0, "error": str(exc)}


async def run(args):
    sem = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient() as client:
        async def task(i):
            async with sem:
                return await one_request(client, args.base_url,
                                         args.model, args.prompt, i)
        results = await asyncio.gather(*[task(i) for i in range(args.total)])

    successes = [r for r in results if 200 <= r["status"] < 300]
    failures = [r for r in results if r not in successes]
    latencies: list[float] = sorted(r["latency_s"] for r in successes)

    print("\n=== Benchmark Summary ===")
    print(f"Total:    {len(results)}")
    print(f"OK:       {len(successes)}")
    print(f"Failed:   {len(failures)}")
    print(f"Concurr:  {args.concurrency}")
    if latencies:
        print(f"p50:      {statistics.median(latencies):.2f}s")
        p95 = latencies[int(len(latencies) * 0.95)] if len(latencies) > 1 else latencies[0]
        print(f"p95:      {p95:.2f}s")
        total_tokens = sum(int(r["tokens"]) for r in successes)
        if max(latencies) > 0:
            print(f"Throughput:{total_tokens / max(latencies):.1f} tok/s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080/v1")
    parser.add_argument("--model", default="qwen-0.5b")
    parser.add_argument("--prompt", default="写一句关于云计算的话")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--total", type=int, default=20)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
