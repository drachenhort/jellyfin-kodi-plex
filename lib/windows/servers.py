"""Server list/switcher window: shows every saved server, lets the user pick
one to make active, add a new one (delegated back to lib/main.py's login
flow, same split of responsibility LoginWindow already has), or remove a
saved one.

self.result on close is one of:
  {"action": "select", "server_id": ...}
  {"action": "add"}
  {"action": "remove", "server_id": ...}
  None (back — no change)
"""

import xbmcgui

from lib.windows.kodigui import ControlledWindow

CTRL_SERVER_LIST = 300
CTRL_ADD_SERVER = 301
CTRL_REMOVE_SERVER = 302
CTRL_STATUS_LABEL = 303


class ServerListWindow(ControlledWindow):
    xmlFile = "script-jellyfin-servers.xml"

    def setup(self, servers=None, active_id=None, **kwargs):
        super().setup(**kwargs)
        self.servers = servers or []
        self.active_id = active_id

    def onInit(self):
        control = self.getControl(CTRL_SERVER_LIST)
        control.reset()
        for server in self.servers:
            label = server.get("name") or server.get("server_url", "")
            if server.get("id") == self.active_id:
                label += " (current)"
            li = xbmcgui.ListItem(label=label)
            li.setProperty("server_id", server.get("id", ""))
            control.addItem(li)
        self.setFocusId(CTRL_SERVER_LIST)

    def handle_click(self, control_id):
        if control_id == CTRL_SERVER_LIST:
            self._select()
        elif control_id == CTRL_ADD_SERVER:
            self.result = {"action": "add"}
            self.close()
        elif control_id == CTRL_REMOVE_SERVER:
            self._remove()

    def _selected_server_id(self):
        selected = self.getControl(CTRL_SERVER_LIST).getSelectedItem()
        if not selected:
            return None
        return selected.getProperty("server_id")

    def _select(self):
        server_id = self._selected_server_id()
        if not server_id:
            return
        self.result = {"action": "select", "server_id": server_id}
        self.close()

    def _remove(self):
        server_id = self._selected_server_id()
        if not server_id:
            return
        if server_id == self.active_id:
            self.getControl(CTRL_STATUS_LABEL).setLabel(
                "Can't remove the active server — switch to another server first"
            )
            return
        self.result = {"action": "remove", "server_id": server_id}
        self.close()
