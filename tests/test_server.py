import io
import logging
import socket
import threading
import time

import pymupdf
import pytest

from app.config import Config, load_config, save_config
from app.logging_setup import setup_logging
from app.server import create_app, find_free_port
from tests.test_provider import FakeLLM, cfg_for


def make_client(tmp_path):
    app = create_app(tmp_path)
    app.config["TESTING"] = True
    return app.test_client()


def test_status_reports_version_and_no_key(tmp_path):
    data = make_client(tmp_path).get("/api/status").get_json()
    assert data["has_key"] is False
    assert data["version"]


def test_get_config_masks_key(tmp_path):
    save_config(tmp_path, Config(provider="kimi", api_key="sk-1234567890"))
    data = make_client(tmp_path).get("/api/config").get_json()
    assert data["api_key_masked"] == "sk-1…7890"
    assert "sk-1234567890" not in str(data)


def test_post_config_fills_preset_defaults_and_keeps_key_when_blank(tmp_path):
    save_config(tmp_path, Config(provider="kimi", api_key="sk-old"))
    r = make_client(tmp_path).post("/api/config", json={"provider": "openrouter", "api_key": "  ", "base_url": "", "model": ""})
    assert r.status_code == 200
    cfg = load_config(tmp_path)
    assert cfg.provider == "openrouter"
    assert cfg.base_url == "https://openrouter.ai/api/v1"
    assert cfg.model  # 预设默认模型已填入
    assert cfg.api_key == "sk-old"  # 留空 = 不改


def test_post_config_stores_new_key(tmp_path):
    make_client(tmp_path).post("/api/config", json={"provider": "openrouter", "api_key": " sk-new\n", "base_url": "", "model": ""})
    assert load_config(tmp_path).api_key == "sk-new"


def test_test_connection_endpoint_wires_provider(tmp_path, monkeypatch):
    import app.server as server_mod
    save_config(tmp_path, Config(provider="custom", base_url="https://x/v1", api_key="k", model="m"))
    monkeypatch.setattr(server_mod, "test_connection", lambda cfg: (True, "连接成功,模型有回应 ✔"))
    r = make_client(tmp_path).post("/api/test-connection")
    assert r.get_json() == {"ok": True, "message": "连接成功,模型有回应 ✔"}


def test_find_free_port_avoids_busy_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    busy = s.getsockname()[1]
    try:
        assert find_free_port(busy) != busy
    finally:
        s.close()


def test_find_free_port_zero_returns_real_assigned_port():
    assert 1024 < find_free_port(0) < 65536


def test_setup_logging_writes_utf8_file_and_is_idempotent(tmp_path):
    setup_logging(tmp_path)
    setup_logging(tmp_path)  # 再来一次不应该重复挂 handler
    logging.getLogger("xiaozhao.test").info("你好,日志")
    text = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    assert "你好,日志" in text


def test_post_config_rejects_non_object_body(tmp_path):
    # 数组/字符串这类"合法 JSON 但不是对象"的 body:400,不能 500,也不许改坏配置
    save_config(tmp_path, Config(provider="kimi", api_key="sk-old"))
    r = make_client(tmp_path).post("/api/config", json=[1, 2, 3])
    assert r.status_code == 400
    assert r.get_json()["ok"] is False
    assert load_config(tmp_path).provider == "kimi"


def test_post_config_rejects_non_json_body(tmp_path):
    # 恶意页面只能发 text/plain 这种"简单请求";换掉 force=True 后它连解析都过不了
    r = make_client(tmp_path).post("/api/config", data="provider=x", content_type="text/plain")
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_cross_origin_post_is_rejected(tmp_path):
    # 别的网页拿着用户浏览器朝本机发 POST:拦下(这一条是口子①的守门员)
    r = make_client(tmp_path).post(
        "/api/config", json={"provider": "kimi"}, headers={"Origin": "https://evil.example"}
    )
    assert r.status_code == 403
    assert r.get_json()["ok"] is False


def test_same_origin_post_is_allowed(tmp_path):
    # 我们自己的页面(fetch 的 POST 会带 Origin):必须放行
    r = make_client(tmp_path).post(
        "/api/config", json={"provider": "kimi", "base_url": "", "model": ""},
        headers={"Origin": "http://127.0.0.1:8756"},
    )
    assert r.status_code == 200


def test_post_config_blank_provider_keeps_stored(tmp_path):
    # 口子⑤:前端没加载全时会把 provider 发成空——不能把人已存的平台抹掉
    save_config(tmp_path, Config(provider="kimi", api_key="sk-old", base_url="https://x/v1", model="m"))
    r = make_client(tmp_path).post("/api/config", json={"provider": "", "api_key": "", "base_url": "https://x/v1", "model": "m"})
    assert r.status_code == 200
    assert load_config(tmp_path).provider == "kimi"


def test_vision_model_roundtrip(tmp_path):
    c = make_client(tmp_path)
    c.post("/api/config", json={"provider": "custom", "base_url": "https://x/v1", "model": "m", "vision_model": " vm "})
    assert load_config(tmp_path).vision_model == "vm"
    assert c.get("/api/config").get_json()["vision_model"] == "vm"


def test_usage_endpoint_reports_totals(tmp_path):
    from app.usage import record_usage

    record_usage(tmp_path, "提问", "m", {"prompt_tokens": 5, "completion_tokens": 5})
    data = make_client(tmp_path).get("/api/usage").get_json()
    assert data["calls"] == 1 and data["prompt_tokens"] == 5


# —— Task 10:课件接口(上传 / 列表 / 后台解析 / 删除)与人话错误 ——

# brief 夹具的默认文字「第一页内容」只有 5 字,会被 SCANNED_TEXT_THRESHOLD=20 判成扫描页
# (那样解析要走视觉模型、job 会 failed,与用例意图正好相反)。阈值是计划钉死的常量,不能动;
# 只把示例文字补到 ≥20 字,页面角色与断言一字未改(T7/T8 同一个坑,同款修法)。
def make_pdf_bytes(text="第一页内容:这一页的文字内容在这里,足够长,不会被当扫描页。") -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text, fontname="china-s", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def upload(client, name="讲义.pdf", content=None):
    payload = content if content is not None else make_pdf_bytes()
    return client.post(
        "/api/courses", data={"file": (io.BytesIO(payload), name)}, content_type="multipart/form-data"
    )


def test_upload_list_delete_roundtrip(tmp_path):
    c = make_client(tmp_path)
    r = upload(c)
    assert r.status_code == 200 and r.get_json()["is_new"] is True
    course_id = r.get_json()["id"]
    items = c.get("/api/courses").get_json()
    assert len(items) == 1 and items[0]["name"] == "讲义.pdf"
    assert items[0]["status"]["state"] == "none"
    assert c.delete(f"/api/courses/{course_id}").status_code == 200
    assert c.get("/api/courses").get_json() == []


def test_same_pdf_with_new_name_is_not_duplicated(tmp_path):
    # Review Focus #1:同一份课件(改了文件名)再来一次 → 不建第二条、不重复解析
    # 夹具坑:pymupdf 每次 tobytes() 都会埋一个随机的 /ID,两次各生成一遍就是两份不同的字节
    # (哈希入库会当成两份)。「同一份课件」= 同一串字节,所以先造一次、两次传同一份。
    c = make_client(tmp_path)
    payload = make_pdf_bytes()
    first = upload(c, "讲义.pdf", payload).get_json()
    second = upload(c, "讲义-最终版.pdf", payload).get_json()
    assert second["is_new"] is False and second["id"] == first["id"]
    assert len(c.get("/api/courses").get_json()) == 1


def test_upload_non_pdf_is_human_error(tmp_path):
    c = make_client(tmp_path)
    # 非 ASCII 字节字面量在 bytes 里写不出来,拼出来才是合法 Python
    r = upload(c, "照片.jpg", b"JFIF " + "我是图片".encode("utf-8"))
    assert r.status_code == 400
    assert "PDF" in r.get_json()["message"]
    assert c.get("/api/courses").get_json() == []


def test_upload_too_big_is_human_413(tmp_path):
    c = make_client(tmp_path)
    c.application.config["MAX_CONTENT_LENGTH"] = 100  # 测试里把上限调小,不用真造 200MB
    r = upload(c, "大.pdf", b"%PDF-" + b"x" * 500)
    assert r.status_code == 413
    assert "太大" in r.get_json()["message"]


def test_parse_endpoint_runs_in_background_and_reports_done(tmp_path):
    c = make_client(tmp_path)
    course_id = upload(c).get_json()["id"]
    assert c.post(f"/api/courses/{course_id}/parse").status_code == 200
    item = None
    for _ in range(100):  # 后台线程:轮询等它跑完(纯文字 PDF,不需要模型)
        item = c.get("/api/courses").get_json()[0]
        if item.get("job", {}).get("state") in ("done", "failed"):
            break
        time.sleep(0.05)
    assert item["job"]["state"] == "done"
    assert item["status"]["state"] == "done"


def test_parse_and_delete_bad_id_are_human(tmp_path):
    c = make_client(tmp_path)
    assert c.post("/api/courses/zzz/parse").status_code == 400
    assert c.delete("/api/courses/zzz").status_code == 400


def test_double_click_parse_starts_only_one_run(tmp_path, monkeypatch):
    # T8 评审 M3:双击/双标签同时点「解析」——服务端抢占必须是原子的,
    # 否则同一份课件会跑两遍解析(同一页问两遍视觉模型 = 重复花钱,meta.json.tmp 也会互踩)。
    import app.server as server_mod
    from app.courseware import course_file as real_course_file

    app = create_app(tmp_path)
    app.config["TESTING"] = True
    clients = [app.test_client(), app.test_client()]
    course_id = upload(clients[0]).get_json()["id"]

    started: list[str] = []
    holding = threading.Event()

    def fake_parse(data_dir, cid, cfg, progress=None):
        started.append(cid)
        holding.wait(10)  # 卡住这一遍,让「正在跑」一直挂着
        return {"pages": 1}

    monkeypatch.setattr(server_mod, "parse_course", fake_parse)

    both_at_the_door = threading.Barrier(2, timeout=10)

    def slow_course_file(data_dir, cid):
        # 两个请求都先在这里碰头,再一起往下走——把竞争的窗口撑开到必现
        both_at_the_door.wait()
        return real_course_file(data_dir, cid)

    monkeypatch.setattr(server_mod, "course_file", slow_course_file)

    responses = []

    def post_parse(client):
        responses.append(client.post(f"/api/courses/{course_id}/parse"))

    threads = [threading.Thread(target=post_parse, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)

    assert [r.status_code for r in responses] == [200, 200]
    deadline = time.time() + 5
    while not started and time.time() < deadline:
        time.sleep(0.01)
    time.sleep(0.3)  # 没锁的话,第二个解析会在这一小段里冒头
    holding.set()
    assert started == [course_id]  # 两个请求同时到,只准跑一遍


# —— fix round 1:T10 评审 M1(抢占成功后的意外不许把 running 粘住)与 M2(解析/删除交错)——


def test_parse_start_failure_does_not_leave_a_stuck_running_job(tmp_path, monkeypatch):
    # M1:占位成功但线程起不来(比如系统开不出新线程)→「解析中…」必须撤掉,
    # 不然这份课件永远删不掉、也永远解析不了,只能重启小灶。
    import app.server as server_mod

    c = make_client(tmp_path)
    course_id = upload(c).get_json()["id"]

    class NoThread:
        @staticmethod
        def Thread(*_a, **_k):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(server_mod, "threading", NoThread)
    with pytest.raises(RuntimeError):
        c.post(f"/api/courses/{course_id}/parse")

    monkeypatch.undo()
    item = c.get("/api/courses").get_json()[0]
    assert "job" not in item  # 没粘着「解析中…」
    assert c.delete(f"/api/courses/{course_id}").status_code == 200  # 也没被它卡住


def test_parse_config_failure_happens_before_the_job_is_claimed(tmp_path, monkeypatch):
    # M1 的另一半:读配置会抛的先抛——先占下 job 再炸,坏配置就把课件粘在「解析中…」了
    import app.server as server_mod

    c = make_client(tmp_path)
    course_id = upload(c).get_json()["id"]

    def broken_load_config(_data_dir):
        raise OSError("config.json 被别的程序占着")

    monkeypatch.setattr(server_mod, "load_config", broken_load_config)
    with pytest.raises(OSError):
        c.post(f"/api/courses/{course_id}/parse")

    monkeypatch.undo()
    assert "job" not in c.get("/api/courses").get_json()[0]


def test_parse_racing_a_delete_leaves_no_stale_job_card(tmp_path, monkeypatch):
    # M2:解析刚校验完「文件还在」、还没抢占时,删除先落地 →
    # 解析必须老实报「不在了」并且一个 job 都不许占;否则会留下一张指向已删 id 的
    # 失败卡片,同内容重传(同 id)时那张卡片会盖住真实状态。
    import app.server as server_mod
    from app.courseware import course_file as real_course_file

    app = create_app(tmp_path)
    app.config["TESTING"] = True
    parse_client, other = app.test_client(), app.test_client()
    payload = make_pdf_bytes()
    course_id = upload(parse_client, "讲义.pdf", payload).get_json()["id"]

    checked = threading.Event()
    released = threading.Event()

    class PathCheckedThenDeleted:
        """把「校验的那一刻」定住:第 1 次 exists() 里等删除落地,再说"还在"
        (真实交错里,校验就是在文件还在的时候通过的);第 2 次起照实说。"""

        def __init__(self, real):
            self._real = real
            self._calls = 0

        def exists(self):
            self._calls += 1
            if self._calls == 1:
                checked.set()
                released.wait(10)  # 删除在这段时间里跑完
                return True
            return self._real.exists()

    def pausing_course_file(data_dir, cid):
        return PathCheckedThenDeleted(real_course_file(data_dir, cid))

    monkeypatch.setattr(server_mod, "course_file", pausing_course_file)

    response = {}

    def post_parse():
        response["r"] = parse_client.post(f"/api/courses/{course_id}/parse")

    t = threading.Thread(target=post_parse)
    t.start()
    assert checked.wait(10)
    assert other.delete(f"/api/courses/{course_id}").status_code == 200
    released.set()
    t.join(15)

    r = response["r"]
    assert r.status_code == 400 and "不在了" in r.get_json()["message"]

    again = upload(other, "讲义.pdf", payload).get_json()  # 同内容重传:还是那个 id
    assert again["id"] == course_id and again["is_new"] is True
    item = other.get("/api/courses").get_json()[0]
    assert "job" not in item  # 上次没留下失败卡片
    assert item["status"]["state"] == "none"


# —— Task 11:提问接口 ——


def test_ask_end_to_end(tmp_path):
    # 一份文字版课件:上传 → 解析(本地活,不花钱)→ 提问(走 FakeLLM)
    with FakeLLM() as fake:  # 默认回答「收到」
        save_config(tmp_path, cfg_for(fake))
        c = make_client(tmp_path)
        course_id = upload(c).get_json()["id"]
        c.post(f"/api/courses/{course_id}/parse")
        for _ in range(100):
            if c.get("/api/courses").get_json()[0]["status"]["state"] == "done":
                break
            time.sleep(0.05)
        r = c.post(f"/api/courses/{course_id}/ask", json={"question": "这页讲了啥?"})
        assert r.status_code == 200
        assert r.get_json()["answer"] == "收到"
        assert c.get("/api/usage").get_json()["calls"] == 1


def test_ask_unparsed_course_is_human(tmp_path):
    c = make_client(tmp_path)
    course_id = upload(c).get_json()["id"]
    r = c.post(f"/api/courses/{course_id}/ask", json={"question": "在吗"})
    assert r.status_code == 400 and "解析" in r.get_json()["message"]


def test_ask_non_object_body_is_400(tmp_path):
    r = make_client(tmp_path).post("/api/courses/zzz/ask", json=[1, 2])
    assert r.status_code == 400 and r.get_json()["ok"] is False


# —— fix round:最终评审 M1/M2/M4/M5 ——


def test_courses_endpoint_survives_junk_in_the_library(tmp_path):
    # M1:课件夹里的脏数据(名字不合规的 json、半截 json)不能让 /api/courses 整条垮掉
    c = make_client(tmp_path)
    course_id = upload(c).get_json()["id"]
    courses = tmp_path / "courses"
    (courses / "乱七八糟.json").write_text('{"name": "手放的"}', encoding="utf-8")
    (courses / "乱七八糟.pdf").write_bytes(b"%PDF-1.4 " + "手放的".encode("utf-8"))  # 以前这条会让接口整个失败
    (courses / ("c" * 16 + ".json")).write_text("{ 半截", encoding="utf-8")
    r = c.get("/api/courses")
    assert r.status_code == 200
    assert [it["id"] for it in r.get_json()] == [course_id]


def test_usage_endpoint_survives_dirty_lines(tmp_path):
    # M2:账本里混进脏行(合法 JSON 非对象、token 不是数字)→ /api/usage 照样 200
    with (tmp_path / "usage.jsonl").open("a", encoding="utf-8") as f:
        f.write("123\n")
        f.write('{"prompt_tokens": "很多"}\n')
    r = make_client(tmp_path).get("/api/usage")
    assert r.status_code == 200
    assert r.get_json()["calls"] == 1  # 是一次调用,只是 token 数字脏了


def test_ask_survives_the_course_being_deleted_mid_question(tmp_path, monkeypatch):
    # M4:提问读页途中课件被删 → 400 人话(以前 FileNotFoundError 500,还劝人去重启小灶)
    import app.server as server_mod

    def gone(*_a, **_k):
        raise FileNotFoundError("课件被删了")

    c = make_client(tmp_path)
    course_id = upload(c).get_json()["id"]
    monkeypatch.setattr(server_mod, "ask_course", gone)
    r = c.post(f"/api/courses/{course_id}/ask", json={"question": "在吗"})
    assert r.status_code == 400
    assert "删" in r.get_json()["message"] and r.get_json()["ok"] is False


def test_responses_forbid_being_framed(tmp_path):
    # M5:别的网页不许拿 iframe 把小灶页面套进去骗点击
    r = make_client(tmp_path).get("/api/status")
    assert r.headers["X-Frame-Options"] == "DENY"
