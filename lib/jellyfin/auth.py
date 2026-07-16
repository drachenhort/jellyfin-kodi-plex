"""Authentication flows: classic username/password and Quick Connect.

Both end the same way: `client.access_token`/`client.user_id` get set from
an AuthenticationResult so the caller can persist them (e.g. into Kodi addon
settings) and reuse the client for subsequent calls.
"""


def _apply_auth_result(client, result):
    client.access_token = result["AccessToken"]
    client.user_id = result["User"]["Id"]
    return result["User"]


def authenticate_by_name(client, username, password):
    """POST /Users/AuthenticateByName. Returns the User dict on success."""
    result = client.post(
        "/Users/AuthenticateByName",
        json={"Username": username, "Pw": password},
    )
    return _apply_auth_result(client, result)


def initiate_quick_connect(client):
    """POST /QuickConnect/Initiate. Returns dict with 'Code' and 'Secret'.

    Show Code to the user; they enter it on another already-authenticated
    device/web client. Poll with the Secret via poll_quick_connect().
    """
    return client.post("/QuickConnect/Initiate")


def poll_quick_connect(client, secret):
    """GET /QuickConnect/Connect?secret=... Returns True once authorized."""
    result = client.get("/QuickConnect/Connect", params={"secret": secret})
    return bool(result and result.get("Authenticated"))


def authenticate_with_quick_connect(client, secret):
    """POST /Users/AuthenticateWithQuickConnect once poll_quick_connect() is True."""
    result = client.post(
        "/Users/AuthenticateWithQuickConnect",
        json={"Secret": secret},
    )
    return _apply_auth_result(client, result)
