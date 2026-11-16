"""Serve the independent frontend locally, with capacity for parallel assets."""
from argparse import ArgumentParser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

FRONTEND = Path(__file__).resolve().parents[1] / 'frontend'


class PreviewHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        if urlsplit(self.path).path in ('/', '/home.html', '/demo-home.html'):
            self.send_response(307)
            self.send_header('Location', '/wenxia-demo/index.html')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return None
        return super().send_head()


class PreviewServer(ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8303)
    args = parser.parse_args()
    with PreviewServer(('127.0.0.1', args.port), partial(PreviewHandler, directory=str(FRONTEND))) as server:
        print(f'问侠预览：http://127.0.0.1:{args.port}/wenxia-demo/index.html', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
