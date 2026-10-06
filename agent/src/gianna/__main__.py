import argparse
import asyncio
import json
from gianna.config import settings


def main():
    p = argparse.ArgumentParser(prog="python -m gianna")
    p.add_argument("command", choices=["run", "piper", "doctor", "models", "profiles", "benchmark"])
    p.add_argument("subcommand", nargs="?", choices=["verify", "download", "validate"])
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()
    c = settings()
    if args.command in {"run", "piper"}:
        import uvicorn

        if args.command == "piper":
            from gianna.audio.tts_piper import piper_app

            app, port = piper_app(c), c.piper_port
        else:
            from gianna.server.app import create_app

            app, port = create_app(c, managed_browser=not args.no_browser), c.port
        import socket

        with socket.socket() as probe:
            probe.bind((c.host, port))  # Fail before loading models/starting owned children.
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=c.host,
                port=port,
                log_level="info",
                access_log=False,
                timeout_graceful_shutdown=5,
            )
        )
        if args.command == "run":
            app.state.runtime.shutdown_callback = lambda: setattr(server, "should_exit", True)
        server.run()
    elif args.command == "models":
        from gianna.audio.model_manifest import verify, download

        result = download(c) if args.subcommand == "download" else verify(c)
        print(json.dumps(result, indent=2))
    elif args.command == "profiles":
        from gianna.profiles.loader import load_profile, load_preferences
        from gianna.tools.registry import ToolRegistry
        from gianna.tools.tickets import install_tools
        from gianna.adapters.tickets_http import TicketsHTTP

        registry = ToolRegistry()
        install_tools(registry, TicketsHTTP(c, None), None, None)

        print(
            json.dumps(
                {
                    "profile": load_profile(c.profile, registry=registry)["profile_id"],
                    "preferences": load_preferences(),
                },
                indent=2,
            )
        )
    elif args.command == "doctor":
        from gianna.scripts.doctor import doctor

        result = asyncio.run(doctor(c))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["ready"] else 1)
    else:
        from gianna.scripts.benchmark import benchmark

        print(json.dumps(asyncio.run(benchmark(c)), indent=2))


if __name__ == "__main__":
    main()
