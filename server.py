"""Cheat server over a Unix domain socket.

Protocol: newline-delimited JSON, one object per line.
  client -> server: {"type": "join", "name": "..."} | {"type": "start"}
                    {"type": "play", "cards": ["3S", "9H"]} | {"type": "call"} | {"type": "pass"}
  server -> client: {"type": "lobby", "players": [...]} | {"type": "state", ...}
                    {"type": "error", "msg": "..."}
"""
import json
import os
import selectors
import socket
import sys

from game import CheatGame, GameError

SOCK_PATH = "/tmp/cheat.sock"
MIN_PLAYERS = 2
MAX_PLAYERS = 8


class Client:
    def __init__(self, conn):
        self.conn = conn
        self.buf = b""
        self.name = None


class Server:
    def __init__(self, path=SOCK_PATH):
        self.path = path
        self.sel = selectors.DefaultSelector()
        self.clients = []
        self.game = None

    # ---- plumbing -------------------------------------------------------
    def serve(self):
        if os.path.exists(self.path):
            os.unlink(self.path)  # stale socket from a previous run
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.path)
        srv.listen()
        self.sel.register(srv, selectors.EVENT_READ, data=None)
        print(f"listening on {self.path}")
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
            srv.close()
            if os.path.exists(self.path):
                os.unlink(self.path)

    def accept(self, srv):
        conn, _ = srv.accept()
        conn.setblocking(True)
        client = Client(conn)
        self.clients.append(client)
        self.sel.register(conn, selectors.EVENT_READ, data=client)

    def read(self, c):
        try:
            data = c.conn.recv(4096)
        except ConnectionError:
            data = b""
        if not data:
            self.drop(c)
            return
        c.buf += data
        while b"\n" in c.buf:
            line, c.buf = c.buf.split(b"\n", 1)
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self.send(c, {"type": "error", "msg": "malformed JSON"})
                continue
            self.handle(c, msg)

    def send(self, c, obj):
        try:
            c.conn.sendall(json.dumps(obj).encode() + b"\n")
        except OSError:
            pass  # the read loop will notice the dead connection

    def drop(self, c):
        if c not in self.clients:
            return
        self.sel.unregister(c.conn)
        c.conn.close()
        self.clients.remove(c)
        if c.name and self.game and c.name in self.game.hands:
            self.game = None
            self.broadcast_lobby(f"{c.name} left; game aborted")
        elif c.name:
            self.broadcast_lobby(f"{c.name} left")

    # ---- game flow ------------------------------------------------------
    def joined(self):
        return [c for c in self.clients if c.name]

    def broadcast_lobby(self, note=""):
        msg = {"type": "lobby", "players": [c.name for c in self.joined()], "note": note}
        for c in self.joined():
            self.send(c, msg)

    def broadcast_state(self, note=""):
        g = self.game
        for c in self.joined():
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

    def handle(self, c, msg):
        kind = msg.get("type")
        if kind == "join":
            self.handle_join(c, msg)
        elif c.name is None:
            self.send(c, {"type": "error", "msg": "join first"})
        elif kind == "start":
            self.handle_start(c)
        elif kind in ("play", "call", "pass"):
            self.handle_move(c, kind, msg)
        else:
            self.send(c, {"type": "error", "msg": f"unknown message type {kind!r}"})

    def handle_join(self, c, msg):
        name = str(msg.get("name", "")).strip()[:16]
        if self.game:
            self.send(c, {"type": "error", "msg": "a game is in progress"})
        elif not name or name in [x.name for x in self.joined()]:
            self.send(c, {"type": "error", "msg": "name missing or already taken"})
        elif len(self.joined()) >= MAX_PLAYERS:
            self.send(c, {"type": "error", "msg": "lobby is full"})
        else:
            c.name = name
            self.broadcast_lobby(f"{name} joined")

    def handle_start(self, c):
        if self.game:
            self.send(c, {"type": "error", "msg": "already started"})
        elif len(self.joined()) < MIN_PLAYERS:
            self.send(c, {"type": "error", "msg": f"need at least {MIN_PLAYERS} players"})
        else:
            self.game = CheatGame([x.name for x in self.joined()])
            self.broadcast_state("Game started!")

    def handle_move(self, c, kind, msg):
        if not self.game:
            self.send(c, {"type": "error", "msg": "no game running"})
            return
        try:
            if kind == "play":
                note = self.game.play(c.name, msg.get("cards", []))
            elif kind == "call":
                note = self.game.call(c.name)
            else:
                note = self.game.pass_turn(c.name)
        except GameError as e:
            self.send(c, {"type": "error", "msg": str(e)})
            return
        self.broadcast_state(note)
        if self.game.winner:
            self.game = None
            self.broadcast_lobby("Game over. Type 'start' to play again.")


if __name__ == "__main__":
    Server(sys.argv[1] if len(sys.argv) > 1 else SOCK_PATH).serve()
