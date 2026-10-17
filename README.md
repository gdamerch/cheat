# Cheat: a multiplayer card game over Unix domain sockets

A terminal version of the card game Cheat (also called BS or I Doubt It). One server process hosts the game, and each player connects from their own terminal through a Unix domain socket.

## Requirements

- Python 3.8 or newer (standard library only, nothing to install)
- Linux, macOS, or WSL on Windows. Unix domain sockets and `select` on stdin don't work in a native Windows terminal.
- All players must be on the same machine, since Unix domain sockets are local only.

## Files

| File | Purpose |
| --- | --- |
| `game.py` | Game rules and state. No networking. |
| `server.py` | Accepts connections and runs the game. |
| `client.py` | Terminal client each player runs. |

## Running a game

Open one terminal per player, plus one for the server. Put all three files in the same folder and `cd` into it in each terminal.

**1. Start the server (terminal 1)**

```bash
python3 server.py
```

You should see `listening on /tmp/cheat.sock`. Leave it running.

**2. Connect each player (terminals 2, 3, ...)**

```bash
python3 client.py alice
python3 client.py bob
python3 client.py carol
```

The argument is the player's name (up to 16 characters, must be unique). 2 to 8 players can join.

**3. Start the game**

Once everyone has joined, any player types:

```
start
```

Cards are dealt evenly and player 1 (the first to join) goes first. You can't join once a game has started.

### Using a different socket path

Both programs take an optional socket path, which is handy for running several games at once:

```bash
python3 server.py /tmp/game2.sock
python3 client.py alice /tmp/game2.sock
```

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

1. Everyone is dealt cards until the deck runs out. The goal is to get rid of all your cards.
2. On your turn you play 1 to 4 cards face down and claim they are all of the required rank. The required rank starts at Ace and goes up by one each turn (A, 2, 3, ... K, then back to A). The server tells you the current required rank each turn.
3. You may lie. Nobody sees the cards you play, only how many and what you claimed.
4. After a play, any player other than the one who played can type `call` to accuse them of cheating. The cards are revealed:
   - If the player lied, they pick up the whole pile.
   - If they told the truth, the caller picks up the whole pile.
5. After a call the pile is empty and play continues with the same player whose turn it was.
6. If you play your last card, you win unless someone calls you out and you were lying. If nobody calls, the next player types `pass` to confirm the win.

## Example session

```
* Game started!
Cards left: alice:26, bob:26 | pile: 0
alice's turn, claim must be: A
Hand: 1:AD  2:2S  3:2H  4:2D ...

> play 1                      (alice plays her ace)
* alice plays 1 card(s), claiming A
Cards left: alice:25, bob:26 | pile: 1
Last play: alice put down 1 x A
YOUR turn, claim must be: 2

> call                        (bob challenges her)
* bob calls cheat on alice! Cards were AS: honest. bob picks up the pile
```

## Troubleshooting

**`FileNotFoundError` or `ConnectionRefusedError` when starting a client**
The server isn't running, or you used a different socket path. Start the server first and make sure both sides use the same path.

**`OSError: [Errno 98] Address already in use` or the socket file is left over**
The server normally cleans up `/tmp/cheat.sock` on exit and removes a stale one on startup. If it crashed, delete it manually with `rm /tmp/cheat.sock`.

**"name missing or already taken"**
Pick a different name, since each player needs a unique one.

**"a game is in progress"**
Players can only join before the game starts. Wait for the game to end or restart the server.

**The game ended unexpectedly**
If any player disconnects mid-game, the game is aborted and everyone returns to the lobby.

**Stopping the server**
Press `Ctrl+C` in the server terminal.

## Protocol (for developers)

Messages are newline-delimited JSON over a `SOCK_STREAM` Unix socket, one object per line.

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

Each player only receives their own hand. The server sends everyone else's card counts, never their cards.
