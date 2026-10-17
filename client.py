"""Terminal client for Cheat. Usage: python client.py NAME [SOCKET_PATH]

Commands:  start | play 1 4 5 (hand positions) | call | pass | quit
"""
import json
import selectors
import socket
import sys

SOCK_PATH = "/tmp/cheat.sock"


def render(msg):
    if msg["type"] == "error":
        print(f"!! {msg['msg']}")
    elif msg["type"] == "lobby":
        if msg["note"]:
            print(f"* {msg['note']}")
        print(f"Lobby: {', '.join(msg['players'])}  (type 'start' when ready)")
    elif msg["type"] == "state":
        if msg["note"]:
            print(f"* {msg['note']}")
        if msg["winner"]:
            print(f"*** {msg['winner']} wins! ***")
            return
        counts = ", ".join(f"{p}:{n}" for p, n in msg["counts"].items())
        print(f"Cards left: {counts} | pile: {msg['pile']}")
        lp = msg["last_play"]
        if lp:
            print(f"Last play: {lp['player']} put down {lp['count']} x {lp['rank']}")
        who = "YOUR turn" if msg["turn"] == msg["you"] else f"{msg['turn']}'s turn"
        print(f"{who}, claim must be: {msg['claim_rank']}")
        print("Hand: " + "  ".join(f"{i}:{c}" for i, c in enumerate(msg["hand"], 1)))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    name = sys.argv[1]
    path = sys.argv[2] if len(sys.argv) > 2 else SOCK_PATH

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(path)

    def send(obj):
        sock.sendall(json.dumps(obj).encode() + b"\n")

    send({"type": "join", "name": name})
    hand = []
    buf = b""

    sel = selectors.DefaultSelector()
    sel.register(sock, selectors.EVENT_READ, "net")
    sel.register(sys.stdin, selectors.EVENT_READ, "kbd")

    while True:
        for key, _ in sel.select():
            if key.data == "net":
                data = sock.recv(4096)
                if not data:
                    print("server closed the connection")
                    return
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    msg = json.loads(line)
                    if msg["type"] == "state":
                        hand = msg["hand"]
                    render(msg)
            else:
                line = sys.stdin.readline()
                if not line:
                    return
                parts = line.split()
                if not parts:
                    continue
                cmd = parts[0].lower()
                if cmd == "quit":
                    return
                if cmd in ("start", "call", "pass"):
                    send({"type": cmd})
                elif cmd == "play":
                    try:
                        cards = [hand[int(i) - 1] for i in parts[1:]]
                    except (ValueError, IndexError):
                        print("!! use hand positions, e.g. 'play 1 4'")
                        continue
                    send({"type": "play", "cards": cards})
                else:
                    print("!! commands: start, play N [N...], call, pass, quit")


if __name__ == "__main__":
    main()
