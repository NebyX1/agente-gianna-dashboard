"""Bounded observation of an owned, paired runtime. No model substitution or writes."""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
import httpx
from gianna.config import Settings


async def observe(seconds, output):
    config = Settings()
    pairing = os.getenv("GIANNA_PAIRING")
    if not pairing:
        raise SystemExit(
            "Usá /api/metrics desde la consola emparejada o GIANNA_PAIRING temporal en un test propio; nunca guardes esa clave en .env."
        )
    result = []
    async with httpx.AsyncClient(headers={"X-Gianna-Pairing": pairing}) as client:
        due = time.monotonic() + seconds
        while time.monotonic() < due:
            response = await client.get(config.console_origin + "/api/metrics", timeout=5)
            response.raise_for_status()
            result.append({"at": time.time(), "metrics": response.json()})
            await asyncio.sleep(min(5, max(0, due - time.monotonic())))
    Path(output).write_text(
        json.dumps({"duration_seconds": seconds, "observations": result}, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--output", default="observation.json")
    args = parser.parse_args()
    if not 1 <= args.seconds <= 43200:
        parser.error("seconds must be 1..43200; long soak is explicit opt-in")
    asyncio.run(observe(args.seconds, args.output))
