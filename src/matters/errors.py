"""What can go wrong, in as few kinds as it takes to handle it.

Every message is written for the person who reads it: a page shows it as it is, the
command line prints it. A kind is added only when something handles it differently.
"""


class MattersError(Exception):
    """A failure the person can act on; its message says how."""


class ModelError(MattersError):
    """A model request failed: not answered, declined, or answered in the wrong shape."""


class SettingError(MattersError):
    """A setting matters was started with can't be used."""


class DataError(MattersError):
    """Something stored or recorded isn't what matters expects to find."""
