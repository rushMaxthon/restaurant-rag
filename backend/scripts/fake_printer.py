"""A printer that is not a printer: listens on 9100 and shows what arrives.

So the whole chain can be watched before any hardware exists. Place an order,
and the ticket appears in this window exactly as it would appear on paper.

It is also the honest way to test the failure paths. A real printer that is
switched on always works; this one can be killed mid-session to see what the
queue does when a printer disappears, and restarted to watch the tickets that
were waiting come through.

    ./.venv/Scripts/python.exe scripts/fake_printer.py
    ./.venv/Scripts/python.exe scripts/fake_printer.py --port 9100 --save tickets.log

ESC/POS arrives as bytes with escape codes in it. Those are decoded back into
something readable — `[bold]`, `[2x]`, `[CUT]` — rather than printed raw,
because the point is to check the ticket, and a terminal full of `\\x1b!\\x11`
answers nothing. Unknown escapes are shown as their hex so a wrong command is
visible rather than silently swallowed.
"""

from __future__ import annotations

import argparse
import socket
import socketserver
import sys
import threading
from datetime import datetime
from pathlib import Path

ESC = 0x1B
GS = 0x1D

#: The commands this project's agent sends. Anything else is reported as hex,
#: deliberately: a printer silently ignoring a command it does not know is how
#: a bold line comes out plain and nobody finds out until a customer complains.
KNOWN = {
    (ESC, ord("@")): "[init]",
    (ESC, ord("a"), 0): "",  # align left is the default; not worth the noise
    (ESC, ord("a"), 1): "[center]",
    (ESC, ord("a"), 2): "[right]",
    (ESC, ord("E"), 1): "[bold]",
    (ESC, ord("E"), 0): "[/bold]",
    (GS, ord("!"), 0x00): "",  # normal size, likewise
    (GS, ord("!"), 0x11): "[2x]",
}

_write_lock = threading.Lock()


def decode(payload: bytes) -> str:
    """ESC/POS back into something a person can check."""

    out: list[str] = []
    i = 0
    while i < len(payload):
        byte = payload[i]
        if byte in (ESC, GS):
            # Every command this agent sends is two or three bytes.
            for length in (3, 2):
                key = tuple(payload[i : i + length])
                if key in KNOWN:
                    out.append(KNOWN[key])
                    i += length
                    break
            else:
                if payload[i : i + 2] == bytes([GS, ord("V")]):
                    out.append("\n[CUT]\n")
                    i += 4
                else:
                    out.append(f"[?{payload[i]:02x}{payload[i + 1]:02x}]")
                    i += 2
            continue
        out.append(chr(byte) if 9 <= byte < 127 else f"[{byte:02x}]")
        i += 1
    return "".join(out)


class Handler(socketserver.BaseRequestHandler):
    save_to: Path | None = None

    def handle(self) -> None:
        self.request.settimeout(3.0)
        chunks: list[bytes] = []
        while True:
            try:
                data = self.request.recv(8192)
            except socket.timeout:
                # A print job is a one-way write with no terminator, so the
                # only signal that it is finished is the sender going quiet.
                break
            if not data:
                break
            chunks.append(data)

        payload = b"".join(chunks)
        if not payload:
            return

        stamp = datetime.now().strftime("%H:%M:%S")
        header = f"\n{'=' * 60}\n{stamp}  {len(payload)} bytes from {self.client_address[0]}\n{'=' * 60}"
        body = decode(payload)

        with _write_lock:
            print(header)
            print(body)
            sys.stdout.flush()
            if self.save_to is not None:
                with self.save_to.open("a", encoding="utf-8") as handle:
                    handle.write(f"{header}\n{body}\n")


class Server(socketserver.ThreadingTCPServer):
    # So a restart does not wait out TIME_WAIT. This gets stopped and started
    # repeatedly while testing, which is most of what it is for.
    allow_reuse_address = True
    daemon_threads = True


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--save", help="Also append every ticket to this file")
    args = parser.parse_args()

    Handler.save_to = Path(args.save) if args.save else None

    with Server((args.host, args.port), Handler) as server:
        print(f"Fake printer listening on {args.host}:{args.port}")
        print("Tickets will appear below. Ctrl-C to stop.\n")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
