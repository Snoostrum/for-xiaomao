from app.chat import MAX_HISTORY_MESSAGES, chat_loop, chat_turn, trim_history
from app.config import Config, save_config
from tests.test_provider import FakeLLM, cfg_for


def make_input(lines: list[str]):
    it = iter(lines)

    def fake_input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError  # 真 input() 读到头就是这个

    return fake_input


def test_chat_turn_returns_reply_and_remembers_context():
    with FakeLLM() as fake:
        history: list[dict] = []
        assert chat_turn(cfg_for(fake), history, "你好") == "收到"
        chat_turn(cfg_for(fake), history, "接着说")
        sent = fake.requests[1]["json"]["messages"]
        assert sent[:2] == [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "收到"},
        ]
        assert sent[-1] == {"role": "user", "content": "接着说"}


def test_chat_turn_error_is_human_and_not_remembered():
    with FakeLLM(status=401) as fake:
        history: list[dict] = []
        msg = chat_turn(cfg_for(fake), history, "你好")
        assert "Key" in msg
        assert history == []  # 失败的一问不记账,重问一次就行


def test_trim_history_keeps_tail_and_starts_with_user():
    history: list[dict] = []
    for i in range(15):
        history.append({"role": "user", "content": f"u{i}"})
        history.append({"role": "assistant", "content": f"a{i}"})
    trim_history(history)
    assert len(history) <= MAX_HISTORY_MESSAGES
    assert history[0]["role"] == "user"


def test_trim_history_drops_dangling_assistant_head():
    history = [
        {"role": "user", "content": "u0"},
        {"role": "assistant", "content": "a0"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
    ]
    trim_history(history, limit=3)
    assert history == [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
    ]


def test_chat_loop_replies_then_exits_on_quit_word(tmp_path):
    with FakeLLM() as fake:
        save_config(tmp_path, cfg_for(fake))
        out: list[str] = []
        chat_loop(tmp_path, "http://127.0.0.1:1/", input_fn=make_input(["你好", "退出"]), print_fn=out.append)
        assert any("收到" in line for line in out)
        assert any("再见" in line for line in out)
        assert len(fake.requests) == 1


def test_chat_loop_without_key_points_to_settings(tmp_path):
    with FakeLLM() as fake:
        save_config(tmp_path, Config())  # 什么都没填
        out: list[str] = []
        chat_loop(tmp_path, "http://127.0.0.1:1/", input_fn=make_input(["你好", "quit"]), print_fn=out.append)
        assert any("API Key" in line and "设置" in line for line in out)
        assert fake.requests == []  # 没填就没发请求


def test_chat_loop_says_goodbye_on_eof(tmp_path):
    out: list[str] = []
    chat_loop(tmp_path, "http://127.0.0.1:1/", input_fn=make_input([]), print_fn=out.append)
    assert any("再见" in line for line in out)
