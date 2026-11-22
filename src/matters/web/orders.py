"""The order a session's turns are read in: oldest first or newest first.

You set it for every session in the sliders menu, and for one session with the switch
above its turns; a session you set yourself keeps its order whatever the default
becomes. Both are kept in your browser as cookies, which the server reads to draw the
page in that order (localStorage would reach the page only after it is drawn)."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace

# (value, name); the first is the default until you pick one.
ORDERS = (("oldest", "Oldest first"), ("newest", "Newest first"))
OLDEST, NEWEST = (value for value, _ in ORDERS)
DEFAULT_COOKIE = "matters-order"  # every session: oldest or newest
PICKS_COOKIE = "matters-turns"  # the sessions set on their own page: id:o or id:n, by "."
SHORT = {"o": OLDEST, "n": NEWEST}
ROOM = 3800  # characters of picks a cookie can hold (about 4 KB); the latest picks stay
YEAR = 365 * 24 * 3600
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")  # what a cookie can carry as it is


@dataclass(frozen=True, slots=True)
class TurnOrders:
    """The default order, and the sessions set otherwise, oldest pick first."""

    default: str = OLDEST
    picks: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_cookies(cls, cookies: Mapping[str, str]) -> "TurnOrders":
        default = cookies.get(DEFAULT_COOKIE, "")
        picks = []
        for entry in cookies.get(PICKS_COOKIE, "").split("."):
            session_id, _, short = entry.rpartition(":")
            if _ID.fullmatch(session_id) and short in SHORT:
                picks.append((session_id, SHORT[short]))
        return cls(default if default in SHORT.values() else OLDEST, tuple(picks))

    def of(self, session_id: str) -> str:
        return dict(self.picks).get(session_id, self.default)

    def newest_first(self, session_id: str) -> bool:
        return self.of(session_id) == NEWEST

    def picking(self, session_id: str, order: str) -> "TurnOrders":
        """This session in this order, the others as they were. Picking the default lets
        the session follow the default again."""
        picks = tuple(pick for pick in self.picks if pick[0] != session_id)
        if order != self.default and order in SHORT.values() and _ID.fullmatch(session_id):
            picks = (*picks, (session_id, order))
        while picks and len(_joined(picks)) > ROOM:
            picks = picks[1:]
        return replace(self, picks=picks)

    def to_cookie(self) -> str:
        """The Set-Cookie value that keeps the picks; none clears the cookie."""
        age = YEAR if self.picks else 0
        return f"{PICKS_COOKIE}={_joined(self.picks)}; Path=/; Max-Age={age}; SameSite=Strict"


def _joined(picks: tuple[tuple[str, str], ...]) -> str:
    return ".".join(f"{session_id}:{order[0]}" for session_id, order in picks)
