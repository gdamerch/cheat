"""Pure game logic for Cheat (a.k.a. Bullshit / I Doubt It). No networking in here."""
import random

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["S", "H", "D", "C"]


class GameError(Exception):
    """Raised for illegal moves; the server relays the message to the player."""


def rank_of(card):
    return card[:-1]


def sort_key(card):
    return (RANKS.index(rank_of(card)), SUITS.index(card[-1]))


class CheatGame:
    def __init__(self, players, rng=None):
        rng = rng or random.Random()
        self.players = list(players)
        deck = [r + s for r in RANKS for s in SUITS]
        rng.shuffle(deck)
        self.hands = {p: [] for p in self.players}
        for i, card in enumerate(deck):
            self.hands[self.players[i % len(self.players)]].append(card)
        for hand in self.hands.values():
            hand.sort(key=sort_key)

        self.turn = 0            # index into self.players
        self.rank_idx = 0        # claims go A, 2, 3, ... K, A, ...
        self.pile = []
        self.last_play = None    # {"player", "cards", "rank"}
        self.pending_win = False  # last player emptied their hand; can still be called
        self.winner = None

    @property
    def current(self):
        return self.players[self.turn]

    @property
    def required_rank(self):
        return RANKS[self.rank_idx % len(RANKS)]

    def _check_active(self):
        if self.winner:
            raise GameError("the game is over")

    def play(self, player, cards):
        """Play 1-4 cards face down, claiming they are all the required rank."""
        self._check_active()
        if player != self.current:
            raise GameError("it's not your turn")
        if self.pending_win:
            raise GameError("the last player is out of cards: call cheat or pass")
        if not 1 <= len(cards) <= 4:
            raise GameError("play between 1 and 4 cards")
        if len(set(cards)) != len(cards) or any(c not in self.hands[player] for c in cards):
            raise GameError("you don't hold those cards")

        for c in cards:
            self.hands[player].remove(c)
        self.pile.extend(cards)
        claimed = self.required_rank
        self.last_play = {"player": player, "cards": list(cards), "rank": claimed}
        self.rank_idx += 1
        self.turn = (self.turn + 1) % len(self.players)
        if not self.hands[player]:
            self.pending_win = True
        return f"{player} plays {len(cards)} card(s), claiming {claimed}"

    def call(self, caller):
        """Call 'cheat' on the most recent play. Any player except the one accused may."""
        self._check_active()
        if caller not in self.hands:
            raise GameError("you're not in this game")
        if not self.last_play:
            raise GameError("there's nothing to call")
        accused = self.last_play["player"]
        if caller == accused:
            raise GameError("you can't call your own play")

        cards = self.last_play["cards"]
        truthful = all(rank_of(c) == self.last_play["rank"] for c in cards)
        loser = caller if truthful else accused
        self.hands[loser].extend(self.pile)
        self.hands[loser].sort(key=sort_key)
        self.pile = []
        if self.pending_win and truthful:
            self.winner = accused
        self.pending_win = False
        self.last_play = None
        verdict = "honest" if truthful else "cheating"
        return (f"{caller} calls cheat on {accused}! Cards were {' '.join(cards)}: "
                f"{verdict}. {loser} picks up the pile")

    def pass_turn(self, player):
        """Only legal when the previous player went out and nobody called them."""
        self._check_active()
        if not self.pending_win:
            raise GameError("you can only pass after a player empties their hand")
        if player != self.current:
            raise GameError("it's not your turn")
        self.winner = self.last_play["player"]
        return f"nobody called it: {self.winner} wins"
