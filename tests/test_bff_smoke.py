from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from scripts import smoke_test_bff


def test_image_probe_retries_connection_closed_during_container_startup(monkeypatch, capsys):
    requests = []

    class Readiness(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if len(requests) == 1:
                self.connection.close()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ready"}')

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Readiness)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    removed = []

    def docker(*args, **kwargs):
        if args[0] == "run":
            return "test-container"
        if args[0] == "port":
            return f"127.0.0.1:{server.server_port}"
        return ""

    monkeypatch.setattr(smoke_test_bff, "docker", docker)
    monkeypatch.setattr(smoke_test_bff.sys, "argv", ["smoke_test_bff.py", "test-image"])
    monkeypatch.setattr(smoke_test_bff.subprocess, "run", lambda args, **kwargs: removed.append(args))
    try:
        smoke_test_bff.main()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert requests == ["/readiness", "/readiness"]
    assert removed == [["docker", "rm", "--force", "test-container"]]
    assert "HTTP 200" in capsys.readouterr().out
