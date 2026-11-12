"""Terminal client for Cheat.

Usage:
  python client.py NAME                          # server on this machine
  python client.py NAME --host 192.168.1.20      # server on another machine
  python client.py NAME --host HOST --port 6000  # non-default port

Commands:  start | play 1 4 5 (hand positions) | call | pass | quit
"""
import argparse
import json
import socket
import sys
import threading

from common import DEFAULT_HOST, DEFAULT_PORT, port_number


def render(msg):
    kind = msg.get("type")
    if kind == "error":
        print(f"!! {msg.get('msg')}")
    elif kind == "lobby":
        if msg.get("note"):
            print(f"* {msg['note']}")
        print(f"Lobby: {', '.join(msg.get('players', []))}  (type 'start' when ready)")
    elif kind == "state":
        if msg.get("note"):
            print(f"* {msg['note']}")
        if msg.get("winner"):
            print(f"*** {msg['winner']} wins! ***")
            return
        counts = ", ".join(f"{p}:{n}" for p, n in msg["counts"].items())
        print(f"Cards left: {counts} | pile: {msg['pile']}")
        lp = msg.get("last_play")
        if lp:
            print(f"Last play: {lp['player']} put down {lp['count']} x {lp['rank']}")
        who = "YOUR turn" if msg["turn"] == msg["you"] else f"{msg['turn']}'s turn"
        print(f"{who}, claim must be: {msg['claim_rank']}")
        print("Hand: " + "  ".join(f"{i}:{c}" for i, c in enumerate(msg["hand"], 1)))


def send(sock, obj):
    try:
        sock.sendall(json.dumps(obj).encode() + b"\n")
    except OSError:
        pass  # the receive loop will notice the disconnect


def input_loop(sock, state):
    """Runs in a thread so reading the keyboard never blocks incoming messages
    (and so the client works on Windows, where select() can't watch stdin)."""
    try:
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            parts = line.split()
            if not parts:
                continue
            cmd = parts[0].lower()
            if cmd == "quit":
                break
            if cmd in ("start", "call", "pass"):
                send(sock, {"type": cmd})
            elif cmd == "play":
                hand = state["hand"]
                try:
                    picks = [int(i) for i in parts[1:]]
                except ValueError:
                    picks = []
                if not picks or any(not 1 <= i <= len(hand) for i in picks):
                    print("!! use hand positions shown next to your cards, e.g. 'play 1 4'")
                else:
                    send(sock, {"type": "play", "cards": [hand[i - 1] for i in picks]})
            else:
                print("!! commands: start, play N [N...], call, pass, quit")
    finally:
        try:
            sock.shutdown(socket.SHUT_RDWR)  # wakes the receive loop so the program exits
        except OSError:
            pass


def main():
    p = argparse.ArgumentParser(description="Cheat card game client")
    p.add_argument("name", help="your player name (1-16 characters)")
    p.add_argument("--host", default=DEFAULT_HOST,
                   help="server address (default: %(default)s)")
    p.add_argument("--port", type=port_number, default=DEFAULT_PORT,
                   help="server port (default: %(default)s)")
    args = p.parse_args()

    try:
        sock = socket.create_connection((args.host, args.port), timeout=5)
    except OSError as e:
        sys.exit(f"could not connect to {args.host}:{args.port}: {e}")
    sock.settimeout(None)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    state = {"hand": []}
    send(sock, {"type": "join", "name": args.name})
    threading.Thread(target=input_loop, args=(sock, state), daemon=True).start()

    buf = b""
    try:
        while True:
            data = sock.recv(4096)
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    if msg.get("type") == "state":
                        state["hand"] = msg["hand"]
                    render(msg)
    except OSError:
        pass
    print("disconnected from server")


if __name__ == "__main__":
    main()
