import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.config import Config
from app.llm.provider import chat_completion, test_connection

# pytest 会把导入的 test_connection 当成用例去收集(名字以 test 开头),显式声明它不是测试。
test_connection.__test__ = False


class FakeLLM:
    """可编排返回码的本地假服务,并记录收到的每个请求。"""

    def __init__(self, status: int = 200, body: dict | None = None):
        self.status = status
        self.body = body or {"choices": [{"message": {"content": "收到"}}]}
        self.requests: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                outer.requests.append({
                    "path": self.path,
                    "auth": self.headers.get("Authorization"),
                    "json": json.loads(self.rfile.read(length) or b"{}"),
                })
                payload = json.dumps(outer.body).encode("utf-8")
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()


def cfg_for(fake: FakeLLM) -> Config:
    return Config(provider="custom", base_url=fake.base_url, api_key="sk-test", model="m")


def test_success_hits_chat_completions_with_bearer():
    with FakeLLM() as fake:
        ok, msg = test_connection(cfg_for(fake))
        assert ok is True
        req = fake.requests[0]
        assert req["path"] == "/v1/chat/completions"
        assert req["auth"] == "Bearer sk-test"
        assert req["json"]["model"] == "m"


def test_401_tells_user_key_problem():
    with FakeLLM(status=401) as fake:
        ok, msg = test_connection(cfg_for(fake))
        assert ok is False and "Key" in msg


def test_429_tells_user_rate_limited():
    with FakeLLM(status=429) as fake:
        ok, msg = test_connection(cfg_for(fake))
        assert ok is False and "频繁" in msg


def test_connection_refused_says_cannot_reach_with_url():
    cfg = Config(provider="custom", base_url="http://127.0.0.1:1/v1", api_key="k", model="m")
    ok, msg = test_connection(cfg)
    assert ok is False and "连不上" in msg and "127.0.0.1:1" in msg


def test_chat_completion_returns_text():
    with FakeLLM() as fake:
        assert chat_completion(cfg_for(fake), [{"role": "user", "content": "hi"}]) == "收到"


def test_null_content_comes_back_as_empty_string():
    with FakeLLM(body={"choices": [{"message": {"content": None}}]}) as fake:
        assert chat_completion(cfg_for(fake), [{"role": "user", "content": "hi"}]) == ""


def test_missing_key_says_so():
    ok, msg = test_connection(Config())
    assert ok is False and "Key" in msg


def test_base_url_without_scheme_gets_human_message():
    cfg = Config(provider="custom", base_url="example.com/v1", api_key="k", model="m")
    ok, msg = test_connection(cfg)
    assert ok is False and "连不上" in msg and "http" in msg
