import json
import socket

import lib.jellyfin.discovery as discovery_mod
from lib.jellyfin import discovery


class FakeSocket:
    """Records every call; recvfrom() returns queued datagrams then times out."""

    def __init__(self, datagrams):
        self.datagrams = list(datagrams)
        self.sent = []
        self.closed = False

    def setsockopt(self, *args):
        pass

    def settimeout(self, value):
        pass

    def sendto(self, data, address):
        self.sent.append((data, address))

    def recvfrom(self, bufsize):
        if not self.datagrams:
            raise socket.timeout()
        return self.datagrams.pop(0), ("192.168.1.1", discovery.DISCOVERY_PORT)

    def close(self):
        self.closed = True


def _install_fake_socket(monkeypatch, datagrams):
    fake = FakeSocket(datagrams)
    monkeypatch.setattr(discovery_mod.socket, "socket", lambda *a, **kw: fake)
    return fake


def test_discover_servers_parses_valid_response(monkeypatch):
    reply = json.dumps({"Address": "http://192.168.1.10:8096", "Id": "srv-1", "Name": "Tower"}).encode()
    fake = _install_fake_socket(monkeypatch, [reply])

    servers = discovery.discover_servers(timeout=0.01)

    assert servers == [{"Address": "http://192.168.1.10:8096", "Id": "srv-1", "Name": "Tower"}]
    assert fake.sent[0] == (discovery.DISCOVERY_MESSAGE, ("255.255.255.255", discovery.DISCOVERY_PORT))
    assert fake.closed


def test_discover_servers_dedupes_by_id(monkeypatch):
    reply = json.dumps({"Address": "http://192.168.1.10:8096", "Id": "srv-1", "Name": "Tower"}).encode()
    _install_fake_socket(monkeypatch, [reply, reply])

    servers = discovery.discover_servers(timeout=0.01)

    assert len(servers) == 1


def test_discover_servers_ignores_garbage_datagram(monkeypatch):
    valid = json.dumps({"Address": "http://192.168.1.10:8096", "Id": "srv-1", "Name": "Tower"}).encode()
    _install_fake_socket(monkeypatch, [b"not json", valid])

    servers = discovery.discover_servers(timeout=0.01)

    assert servers == [{"Address": "http://192.168.1.10:8096", "Id": "srv-1", "Name": "Tower"}]


def test_discover_servers_no_replies(monkeypatch):
    _install_fake_socket(monkeypatch, [])

    assert discovery.discover_servers(timeout=0.01) == []
