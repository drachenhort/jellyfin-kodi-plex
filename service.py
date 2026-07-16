"""Background service: currently a no-op placeholder.

Reserved for M2 work (server auto-discovery, session keep-alive). Playback
progress reporting in M1 runs inline in lib/player.py while the script addon
is in the foreground, so this service does not need to do anything yet.
"""

import xbmc


class JellyfinMonitor(xbmc.Monitor):
    pass


if __name__ == "__main__":
    monitor = JellyfinMonitor()
    while not monitor.abortRequested():
        if monitor.waitForAbort(10):
            break
