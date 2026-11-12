"""Constants and helpers shared by the server and the client."""
import argparse

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5555
MAX_LINE = 4096  # longest message (in bytes) either side will accept


def port_number(text):
    """argparse type: a TCP port between 1 and 65535."""
    try:
        port = int(text)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be a number between 1 and 65535")
    return port
