"""Entrypoint CLI for ClipForge (run `--mcp` for MCP stdio server or default to Web UI)."""

from __future__ import annotations

import argparse
import multiprocessing
import threading
import time
import webbrowser

import uvicorn


def _open_browser_delayed(url: str) -> None:
    time.sleep(1.0)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main() -> None:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description="ClipForge AI Video Editor & MCP Server")
    parser.add_argument("--mcp", action="store_true", help="Run as MCP stdio server for AI agents")
    parser.add_argument("--host", default="127.0.0.1", help="Web UI bind host")
    parser.add_argument("--port", type=int, default=8765, help="Web UI port")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    args = parser.parse_args()

    if args.mcp:
        from clipforge.mcp_server import main as mcp_main

        mcp_main()
    else:
        from clipforge.web_server import app

        url = f"http://{args.host}:{args.port}"
        if not args.no_browser:
            threading.Thread(target=_open_browser_delayed, args=(url,), daemon=True).start()
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
