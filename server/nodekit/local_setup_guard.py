"""Request checks for the loopback-only first-installation service."""

import hmac
import ipaddress
import secrets


class LocalSetupGuard:
    """Bind a session to one loopback origin and an unguessable capability."""

    def __init__(self, port, token=None):
        if not 1 <= int(port) <= 65535:
            raise ValueError("invalid port")
        self.host = "127.0.0.1:%d" % int(port)
        self.origin = "http://" + self.host
        self.token = token or secrets.token_urlsafe(32)

    def allowed(self, peer, host, origin=None, token=None, mutation=False, protected=False):
        try:
            if not ipaddress.ip_address(peer).is_loopback:
                return False
        except ValueError:
            return False
        if host != self.host:
            return False
        if mutation:
            return (origin == self.origin and isinstance(token, str)
                    and hmac.compare_digest(token, self.token))
        if protected:
            return ((origin is None or origin == self.origin) and isinstance(token, str)
                    and hmac.compare_digest(token, self.token))
        return origin is None or origin == self.origin
