#!/usr/bin/env python3
"""Serve staged output on loopback and fail closed on HTTP/API smoke failures."""

import argparse
import json
import threading
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-root", type=Path, required=True)
    parser.add_argument("--api-root", type=Path, required=True)
    args = parser.parse_args()
    index = args.api_root / "index.json"
    copied = args.dist_root / "api" / args.api_root.name / "index.json"
    if not all(
        path.is_file() for path in (args.dist_root / "index.html", index, copied)
    ):
        raise SystemExit("staged deploy smoke failed")
    payload = json.loads(index.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("data"), dict)
        or not isinstance(payload["data"].get("protocols"), list)
    ):
        raise SystemExit("staged deploy smoke failed")
    def handler(*handler_args: object) -> QuietHandler:
        return QuietHandler(*handler_args, directory=str(args.dist_root))

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        for route in ("/", "/api/v1.7.0/index.json"):
            with urllib.request.urlopen(base + route, timeout=5) as response:
                if response.status != 200:
                    raise SystemExit("staged deploy smoke failed")
    finally:
        server.shutdown()
        thread.join()


if __name__ == "__main__":
    main()
