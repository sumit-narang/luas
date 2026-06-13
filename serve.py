#!/usr/bin/env python3
"""Dev server — injects .env tokens into HTML and proxies /luas-api to production."""

import io, os, urllib.request, urllib.error
from http.server import HTTPServer, SimpleHTTPRequestHandler

# Load .env
env = {}
env_path = os.path.join(os.path.dirname(__file__), '.env')
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip()

MAPBOX_TOKEN = env.get('MAPBOX_TOKEN', '')
PROD_API = 'http://46.62.130.159:8000'

class Handler(SimpleHTTPRequestHandler):

    def do_GET(self):
        if self.path.startswith('/luas-api'):
            self._proxy(self.path)
        else:
            super().do_GET()

    def _proxy(self, path):
        target = PROD_API + path[len('/luas-api'):]
        try:
            req = urllib.request.Request(target, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                self.send_response(200)
                self.send_header('Content-Type', resp.headers.get('Content-Type', 'application/json'))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            self.send_error(e.code, str(e))
        except Exception as e:
            self.send_error(502, f'Proxy error: {e}')

    def send_head(self):
        if self.path.endswith('.html') or self.path == '/':
            path = self.translate_path(self.path)
            try:
                with open(path, 'rb') as f:
                    content = f.read().decode('utf-8')
            except (OSError, IsADirectoryError):
                return super().send_head()

            content = content.replace('YOUR_MAPBOX_TOKEN', MAPBOX_TOKEN)
            encoded = content.encode('utf-8')

            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            return io.BytesIO(encoded)

        return super().send_head()

    def log_message(self, fmt, *args):
        print(f'  {args[0]} {args[1]}')

if __name__ == '__main__':
    port = 8888
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f'Serving http://localhost:{port}/')
    print(f'  → HTML: token injected from .env')
    print(f'  → /luas-api: proxied to {PROD_API}')
    HTTPServer(('127.0.0.1', port), Handler).serve_forever()
