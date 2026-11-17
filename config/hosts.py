import re

_HOSTNAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$")


def render_hosts(hostname):
    """Allowed host and trusted origin for the hostname a host such as Render provides.
    Anything that is not a plain hostname (a scheme, a path, a port) is ignored."""
    host = (hostname or "").strip()
    if not host or not _HOSTNAME.match(host):
        return [], []
    return [host], ["https://" + host]