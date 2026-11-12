"""Cheat server. Players connect over TCP.

Protocol: newline-delimited JSON, one object per line.
  client -> server: {"type": "join", "name": "..."} | {"type": "start"}
                    {"type": "play", "cards": ["3S", "9H"]} | {"type": "call"} | {"type": "pass"}
  server -> client: {"type": "lobby", ...} | {"type": "state", ...} | {"type": "error", "msg": "..."}

Nothing a client sends is trusted: every message is checked for shape and type
before it is used, and a single bad client can never take the server down.
"""
import argparse
import json
import os
import selectors
import socket
import sys
import traceback

from common import DEFAULT_HOST, DEFAULT_PORT, MAX_LINE, port_number
from game import CheatGame, GameError

MIN_PLAYERS = 2
MAX_PLAYERS = 8
MAX_CONNECTIONS = 32     # includes people who haven't joined yet
SEND_TIMEOUT = 2.0       # a client that can't take a message in this long is dropped


class Client:
    def __init__(self, conn):
        self.conn = conn
        self.buf = b""
        self.name = None


class Server:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT):
        self.host = host
        self.port = port
        self.sel = selectors.DefaultSelector()
        self.clients = []
        self.game = None

    # ---- setup / main loop ---------------------------------------------
    def serve(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name != "nt":  # on Windows SO_REUSEADDR would let a second server steal the port
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((self.host, self.port))
        except OSError as e:
            listener.close()
            sys.exit(f"could not listen on {self.host}:{self.port}: {e}")
        listener.listen()
        self.sel.register(listener, selectors.EVENT_READ, data=None)
        host, port = listener.getsockname()
        print(f"listening on {host}:{port}", flush=True)
        try:
            while True:
                for key, _ in self.sel.select():
                    if key.data is None:
                        self.accept(key.fileobj)
                    else:
                        self.read(key.data)
        except KeyboardInterrupt:
            pass
        finally:
            listener.close()

    def accept(self, listener):
        try:
            conn, _ = listener.accept()
        except OSError:
            return
        if len(self.clients) >= MAX_CONNECTIONS:
            conn.close()
            return
        conn.settimeout(SEND_TIMEOUT)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        client = Client(conn)
        self.clients.append(client)
        self.sel.register(conn, selectors.EVENT_READ, data=client)

    # ---- reading / writing ---------------------------------------------
    def read(self, c):
        try:
            data = c.conn.recv(4096)
        except OSError:
            data = b""
        if not data:
            self.drop(c)
            return
        c.buf += data
        while b"\n" in c.buf:
            line, c.buf = c.buf.split(b"\n", 1)
            if len(line) > MAX_LINE:
                self.reject_and_drop(c, "message too long")
                return
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except (ValueError, RecursionError):  # bad JSON, bad UTF-8, absurd nesting
                self.send(c, {"type": "error", "msg": "malformed JSON"})
                continue
            try:
                self.handle(c, msg)
            except Exception:  # last line of defence; validation should catch everything
                traceback.print_exc()
                self.send(c, {"type": "error", "msg": "internal server error"})
            if c not in self.clients:  # dropped while handling
                return
        if len(c.buf) > MAX_LINE:  # no newline yet and already too long
            self.reject_and_drop(c, "message too long")

    def send(self, c, obj):
        try:
            c.conn.sendall(json.dumps(obj).encode() + b"\n")
        except OSError:  # includes timeouts from a stalled client
            self.drop(c)

    def error(self, c, text):
        self.send(c, {"type": "error", "msg": text})

    def reject_and_drop(self, c, text):
        self.error(c, text)
        self.drop(c)

    def drop(self, c):
        if c not in self.clients:
            return
        self.clients.remove(c)
        self.sel.unregister(c.conn)
        c.conn.close()
        if c.name and self.game and c.name in self.game.hands:
            self.game = None
            self.broadcast_lobby(f"{c.name} left; game aborted")
        elif c.name:
            self.broadcast_lobby(f"{c.name} left")

    # ---- broadcasting ---------------------------------------------------
    def joined(self):
        return [c for c in self.clients if c.name]

    def broadcast_lobby(self, note=""):
        msg = {"type": "lobby", "players": [c.name for c in self.joined()], "note": note}
        for c in self.joined():
            self.send(c, msg)

    def broadcast_state(self, note=""):
        g = self.game
        for c in self.joined():
            if self.game is not g:  # a send failed and the game was aborted
                return
            if c.name not in g.hands:
                continue
            self.send(c, {
                "type": "state",
                "note": note,
                "you": c.name,
                "hand": g.hands[c.name],
                "counts": {p: len(g.hands[p]) for p in g.players},
                "turn": g.current,
                "claim_rank": g.required_rank,
                "pile": len(g.pile),
                "last_play": g.last_play and {
                    "player": g.last_play["player"],
                    "count": len(g.last_play["cards"]),
                    "rank": g.last_play["rank"],
                },
                "pending_win": g.pending_win,
                "winner": g.winner,
            })

    # ---- message handling -----------------------------------------------
    def handle(self, c, msg):
        if not isinstance(msg, dict):
            return self.error(c, "message must be a JSON object")
        kind = msg.get("type")
        if not isinstance(kind, str):
            return self.error(c, "message needs a string 'type'")
        if kind == "join":
            self.handle_join(c, msg)
        elif c.name is None:
            self.error(c, "join first")
        elif kind == "start":
            self.handle_start(c)
        elif kind in ("play", "call", "pass"):
            self.handle_move(c, kind, msg)
        else:
            self.error(c, f"unknown message type {kind[:30]!r}")

    def handle_join(self, c, msg):
        name = msg.get("name")
        if c.name:
            return self.error(c, "you have already joined")
        if not isinstance(name, str):
            return self.error(c, "'name' must be a string")
        name = name.strip()[:16]
        if not name or not name.isprintable():
            return self.error(c, "name must be 1-16 printable characters")
        if self.game:
            return self.error(c, "a game is in progress")
        if name in [x.name for x in self.joined()]:
            return self.error(c, "name already taken")
        if len(self.joined()) >= MAX_PLAYERS:
            return self.error(c, "lobby is full")
        c.name = name
        self.broadcast_lobby(f"{name} joined")

    def handle_start(self, c):
        if self.game:
            return self.error(c, "already started")
        if len(self.joined()) < MIN_PLAYERS:
            return self.error(c, f"need at least {MIN_PLAYERS} players")
        g = CheatGame([x.name for x in self.joined()])
        self.game = g
        note = f"Game started! {len(g.hands[g.players[0]])} cards each"
        if g.set_aside:
            note += f" ({len(g.set_aside)} set aside to keep the deal fair)"
        self.broadcast_state(note)

    def handle_move(self, c, kind, msg):
        g = self.game
        if not g:
            return self.error(c, "no game running")
        try:
            if kind == "play":
                note = g.play(c.name, msg.get("cards"))
            elif kind == "call":
                note = g.call(c.name)
            else:
                note = g.pass_turn(c.name)
        except GameError as e:
            return self.error(c, str(e))
        self.broadcast_state(note)
        if g.winner and self.game is g:
            self.game = None
            self.broadcast_lobby("Game over. Type 'start' to play again.")


def main():
    p = argparse.ArgumentParser(description="Cheat card game server")
    p.add_argument("--host", default=DEFAULT_HOST,
                   help="address to listen on (default: %(default)s, this machine only; "
                        "use 0.0.0.0 to accept players from other machines)")
    p.add_argument("--port", type=port_number, default=DEFAULT_PORT,
                   help="TCP port to listen on (default: %(default)s)")
    args = p.parse_args()
    if args.host not in ("127.0.0.1", "localhost"):
        print("warning: connections are unencrypted and have no authentication. "
              "Only expose this on networks you trust.", file=sys.stderr)
    Server(args.host, args.port).serve()


if __name__ == "__main__":
    main()
