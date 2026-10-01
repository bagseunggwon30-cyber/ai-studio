from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from functools import partial

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Host") not in ("127.0.0.1:8796", "localhost:8796"):
            self.send_error(403)
            return
        super().do_GET()
    def end_headers(self):
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

if __name__ == "__main__":
    server=ThreadingHTTPServer(("127.0.0.1",8796),partial(Handler,directory=str(Path(__file__).resolve().parent)))
    print("Preview: http://127.0.0.1:8796/",flush=True)
    server.serve_forever()

