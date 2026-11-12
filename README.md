# Cheat: a multiplayer card game over TCP

A terminal version of the card game Cheat (also called BS or I Doubt It). One server process hosts the game and each player connects from their own terminal over TCP, either on the same machine or from other machines on the network.

## Requirements

- Python 3.8 or newer (standard library only, nothing to install)
- Any OS. The server and client are plain TCP, so they work on Linux, macOS and Windows.

## Files

| File | Purpose |
| --- | --- |
| `game.py` | Game rules and state. No networking. |
| `server.py` | Listens for TCP connections and runs the game. |
| `client.py` | Terminal client each player runs. |
| `common.py` | Defaults and argument validation shared by server and client. |
| `test_cheat.py` | Automated tests. |

## Running a game

Put all the files in one folder and `cd` into it in every terminal.

### Everyone on one machine

```bash
python3 server.py                 # terminal 1
python3 client.py alice           # terminal 2
python3 client.py bob             # terminal 3
```

On Windows, use `python` (or `py`) instead of `python3`.

By default the server listens on `127.0.0.1:5555`, which only accepts players on the same machine.

### Players on different machines

On the host machine, listen on all network interfaces:

```bash
python3 server.py --host 0.0.0.0
```

On each player's machine, connect using the host's IP address or hostname:

```bash
python3 client.py alice --host 192.168.1.20
```

To find the host's IP address: `ip addr` or `hostname -I` on Linux, `ifconfig` on macOS, `ipconfig` on Windows. The host's firewall must allow incoming connections on the port.

### Options

| Option | Applies to | Default | Meaning |
| --- | --- | --- | --- |
| `--host` | server | `127.0.0.1` | Address to listen on. Use `0.0.0.0` to accept other machines. |
| `--host` | client | `127.0.0.1` | Address of the server to connect to. |
| `--port` | both | `5555` | TCP port. Must match on server and clients. |

To run a second game at the same time, start another server on a different port (`python3 server.py --port 6000`) and have those players use `--port 6000`.

> **Security note:** connections are unencrypted and there is no authentication. Anyone who can reach the port can join a game. Use `--host 0.0.0.0` only on a network you trust. The server prints a warning when it isn't bound to localhost.

### Starting the game

Once everyone has joined (2 to 8 players), any player types:

```
start
```

You can't join once a game has started. Names are up to 16 characters and must be unique.

## Commands

| Command | What it does |
| --- | --- |
| `start` | Deal and begin the game (needs at least 2 players). |
| `play 1 4 7` | Put down the cards at those positions in your hand, face down. Positions are the numbers shown next to each card. |
| `call` | Call "cheat" on the most recent play. |
| `pass` | Decline to call when the previous player has just played their last card. |
| `quit` | Disconnect. This aborts any game in progress. |

Cards are written as rank plus suit, for example `10H` (ten of hearts) or `AS` (ace of spades). Suits are S, H, D, C.

## How to play

1. Cards are dealt so that **every player starts with exactly the same number of cards**. A deck has 52 cards, so when that doesn't divide evenly, the leftover cards are set aside face down and stay out of the game. The server tells you how many were set aside.

   | Players | Cards each | Set aside |
   | --- | --- | --- |
   | 2 | 26 | 0 |
   | 3 | 17 | 1 |
   | 4 | 13 | 0 |
   | 5 | 10 | 2 |
   | 6 | 8 | 4 |
   | 7 | 7 | 3 |
   | 8 | 6 | 4 |

2. The goal is to get rid of all your cards.
3. On your turn you play 1 to 4 cards face down and claim they are all of the required rank. The required rank starts at Ace and goes up by one each turn (A, 2, 3, ... K, then back to A). The server tells you the current required rank.
4. You may lie. Nobody sees the cards you play, only how many and what you claimed.
5. After a play, any player other than the one who played can type `call` to accuse them of cheating. The cards are revealed:
   - If the player lied, they pick up the whole pile.
   - If they told the truth, the caller picks up the whole pile.
6. After a call the pile is empty and play continues with the same player whose turn it was.
7. If you play your last card, you win unless someone calls you out and you were lying. If nobody calls, the next player types `pass` to confirm the win.

## Example session

```
* Game started! 26 cards each
Cards left: alice:26, bob:26 | pile: 0
YOUR turn, claim must be: A
Hand: 1:2S  2:2H  3:2D  4:2C ...

> play 1                      (alice puts down a card, claiming it's an ace)
* alice plays 1 card(s), claiming A

> call                        (bob challenges her, from his terminal)
* bob calls cheat on alice! Cards were 2S: cheating. alice picks up the pile
```

## Troubleshooting

**`could not connect to ...: Connection refused`**
The server isn't running, or the client has the wrong `--host` or `--port`. Start the server first and make sure both sides use the same port.

**Players on other machines can't connect**
Check that the server was started with `--host 0.0.0.0` (not the default), that clients use the host's real IP address, and that the host's firewall allows the port.

**`could not listen on ...: Address already in use`**
Another program (or another copy of the server) is using that port. Choose a different one with `--port`. On some macOS versions port 5000 is taken by AirPlay, which is why the default is 5555.

**"name already taken" or "a game is in progress"**
Pick a different name, and note that players can only join before the game starts.

**The game ended unexpectedly**
If any player disconnects mid-game, the game is aborted and everyone returns to the lobby.

**Stopping the server**
Press `Ctrl+C` in the server terminal.

## Protocol (for developers)

Messages are newline-delimited JSON, one object per line, over a TCP connection. Messages longer than 4096 bytes get an error and the connection is closed.

Client to server:

```json
{"type": "join", "name": "alice"}
{"type": "start"}
{"type": "play", "cards": ["3S", "9H"]}
{"type": "call"}
{"type": "pass"}
```

Server to client:

```json
{"type": "lobby", "players": ["alice", "bob"], "note": "bob joined"}
{"type": "state", "you": "alice", "hand": ["AD", "2S"], "counts": {"alice": 26, "bob": 26}, "turn": "alice", "claim_rank": "A", "pile": 0, "last_play": null, "pending_win": false, "winner": null, "note": ""}
{"type": "error", "msg": "it's not your turn"}
```

Each player only receives their own hand. The server sends everyone else's card counts, never their cards. Every incoming message is validated before use: it must be a JSON object with a string `type`, `name` must be a string, and `cards` must be a list of strings. Anything else gets an `error` reply instead of crashing the server.
