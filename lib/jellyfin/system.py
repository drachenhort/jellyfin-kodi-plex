"""Server-level (not user-level) Jellyfin endpoints."""


def get_public_info(client):
    """GET /System/Info/Public — unauthenticated; used to resolve a saved
    server's friendly display name (ServerName) after login."""
    return client.get("/System/Info/Public")
