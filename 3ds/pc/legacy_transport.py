"""Wire constants for the bundled first generation device transport."""

MAGIC = "MW3DS1"
HELLO = (MAGIC + " HELLO\n").encode("ascii")
CHALLENGE_PREFIX = (MAGIC.encode("ascii"), b"CHALLENGE")
TOKEN_HEADER = "X-MW3DS-Token"
ID_HEADER = "X-MW3DS-ID"
TYPE_HEADER = "X-MW3DS-Type"
SD_CONFIG = "sdmc:/3ds/mw3ds/bug-it/receiver.cfg"
