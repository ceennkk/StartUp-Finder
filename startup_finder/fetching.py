"""Bounded public-page retrieval. HTML/RSS adapters, not an unrestricted crawler."""
import ipaddress
import socket
from html.parser import HTMLParser
import urllib.request
from urllib.parse import urlparse, urljoin
import xml.etree.ElementTree as ET


def validate_public_url(url, allowed_hosts):
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Public HTTP(S) URL required')
    if parsed.port not in (None, 80, 443):
        raise ValueError('Only standard HTTP(S) ports allowed')
    if parsed.hostname.lower() not in {host.lower() for host in allowed_hosts}:
        raise ValueError('URL host is not allowlisted for this source')
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('Private/reserved network destination refused')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirect refused; configure the canonical source URL')


def fetch(url, allowed_hosts):
    validate_public_url(url, allowed_hosts)
    request = urllib.request.Request(url, headers={'User-Agent': 'StartupFinder/0.1 (research prototype)', 'Accept': 'text/html,application/rss+xml,application/xml,text/plain'})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
        mime = response.headers.get_content_type()
        if mime not in ('text/html', 'text/plain', 'application/rss+xml', 'application/atom+xml', 'application/xml', 'text/xml'):
            raise ValueError('Unsupported source content type')
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError('Source response exceeds 2 MB')
        return body.decode(response.headers.get_content_charset() or 'utf-8', errors='replace')


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.ignored = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'nav', 'noscript'):
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'nav', 'noscript') and self.ignored:
            self.ignored -= 1

    def handle_data(self, data):
        if not self.ignored and data.strip():
            self.parts.append(data.strip())


def text_from_html(body):
    parser = TextParser()
    parser.feed(body)
    return '\n'.join(parser.parts)


def collect(source, limit=10):
    body = fetch(source['url'], source['allowed_hosts'])
    if source['kind'] == 'rss':
        root = ET.fromstring(body)
        items = list(root.findall('.//item')) + list(root.findall('{http://www.w3.org/2005/Atom}entry'))
        result = []
        for item in items[:limit]:
            title = item.findtext('title') or item.findtext('{http://www.w3.org/2005/Atom}title') or source['name']
            link = item.findtext('link')
            if not link:
                node = item.find('{http://www.w3.org/2005/Atom}link')
                link = node.get('href') if node is not None else None
            if not link:
                continue
            link = urljoin(source['url'], link)
            description = item.findtext('description') or item.findtext('{http://www.w3.org/2005/Atom}summary') or title
            result.append(dict(url=link, title=title, text=text_from_html(description)))
        return result
    return [dict(url=source['url'], title=source['name'], text=text_from_html(body))]
