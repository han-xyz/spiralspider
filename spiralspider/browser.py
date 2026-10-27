"""The browser: scrapy-playwright's plain headless Chromium, or a browser of the user's own over the DevTools
protocol, and the challenge pages that stop a source."""
import ipaddress
import os
import socket
import urllib.parse

# Cloudflare's interstitials: the "Just a moment" page, its managed challenge script, and the Turnstile widget.
CHALLENGE_MARKERS = (
    "<title>Just a moment...</title>",
    "Performing security verification",
    "Verify you are human",
    "challenges.cloudflare.com",
    "cf-turnstile",
    "_cf_chl_opt",
    "cf-chl-",
)


def challenge_marker(text):
    """Return the first recognizable challenge marker, if present."""
    normalized = text.casefold()

    markers = (
        ("<title>just a moment...</title>", "cloudflare_interstitial"),
        ("performing security verification", "security_verification"),
        ("verify you are human", "human_verification"),
        ("challenges.cloudflare.com", "challenge_script"),
        ("cf-turnstile", "turnstile"),
        ("_cf_chl_opt", "challenge_configuration"),
        ("cf-chl-", "challenge_resource"),
    )

    for needle, label in markers:
        if needle in normalized:
            return label

    return None


CDP_URL_VARIABLE = "SPIDER_CDP_URL"


def cdp_url(environ=None, resolve=socket.gethostbyname):
    """The DevTools endpoint of a browser the user runs themselves (SPIDER_CDP_URL), or None for the bundled Chromium.

    Chrome's DevTools server answers only requests whose Host header is an address or localhost, so a host name (a
    compose service, host.docker.internal) is resolved to its address here.
    """
    value = (os.environ if environ is None else environ).get(CDP_URL_VARIABLE, "").strip()
    if not value:
        return None
    parts = urllib.parse.urlsplit(value)
    host = parts.hostname
    if host and host != "localhost" and not _is_address(host):
        address = resolve(host)
        parts = parts._replace(netloc=f"{address}:{parts.port}" if parts.port else address)
    return urllib.parse.urlunsplit(parts)


def playwright_settings(environ=None, resolve=socket.gethostbyname):
    """scrapy-playwright's settings: the browser at SPIDER_CDP_URL when it is set, else a headless Chromium of its
    own, which starts each crawl with a fresh context: no profile, no cookies."""
    endpoint = cdp_url(environ, resolve)
    if endpoint:
        return {"PLAYWRIGHT_CDP_URL": endpoint}
    return {"PLAYWRIGHT_BROWSER_TYPE": "chromium", "PLAYWRIGHT_LAUNCH_OPTIONS": {"headless": True}}


def _is_address(host):
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True
