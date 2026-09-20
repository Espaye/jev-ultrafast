"""Diagnostics that cannot end a run."""

import sys


def say(message):
    """Print a line that may carry page text.

    A page label or a model's answer can hold a character the console cannot encode -- an emoji in a YouTube
    title on a Windows cp1252 console. `print` then raises UnicodeEncodeError out of whatever was running,
    which killed one request per measured suite run. The console's own encoding still decides what is shown;
    a character it has no glyph for becomes "?" instead of ending the request.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(message.encode(encoding, "replace").decode(encoding, "replace"), flush=True)
