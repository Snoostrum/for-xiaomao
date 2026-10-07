"""Probe: does the friend's model route actually support tool calling? (throwaway, M3 onward decides)

用法(在仓库根目录跑):python tools/probe_tool_call.py [config.json 路径]——默认读 data/config.json

Reads config from data/config.json (or a path passed as argv[1]), makes ONE chat
request carrying a `tools` array, and prints a line-by-line trace. Writes nothing
except a few DEBUG lines to the logger (no usage ledger entry).

Exit codes:
  0 = model emitted a tool_call, tool result fed back, loop finished with an answer
  1 = model answered without calling the tool (tool calling likely unsupported / weak)
  2 = platform error (connection, HTTP non-200, etc.)
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import requests

logging.basicConfig(level=logging.DEBUG, format="[%(levelname)s %(name)s] %(message)s")
logging.getLogger("urllib3").setLevel(logging.WARNING)
log = logging.getLogger("probe")

TIMEOUT = 60.0


def main() -> None:
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/config.json")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    base_url = str(cfg.get("base_url") or "").rstrip("/")
    api_key = str(cfg.get("api_key") or "")
    model = str(cfg.get("model") or "")
    if not (base_url and api_key and model):
        log.error("config incomplete: base_url/api_key/model 任一为空,不跑")
        sys.exit(2)

    print(f"provider={cfg.get('provider')} base_url={base_url} model={model} "
          f"key=...{api_key[-4:]} (len {len(api_key)})")

    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_courseware_page",
                "description": "读取某份课件 PDF 的某一页,返回该页内容",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "course_id": {"type": "string", "description": "课件编号"},
                        "page_no": {"type": "integer", "description": "页码,从 1 开始"},
                    },
                    "required": ["course_id", "page_no"],
                },
            },
        }
    ]

    messages = [
        {"role": "system", "content": "你是小灶,一个帮用户研究课件的小助手。需要课件内容时调用工具,不要编造。"},
        {
            "role": "user",
            "content": "课件 f08a9627e330fb0f(海洋科学导论)里,叶绿素 a 的吸收峰在多少纳米?",
        },
    ]

    url = f"{base_url}/chat/completions"
    log.debug("POST %s  model=%s  tools=%d", url, model, len(tools))
    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "tools": tools, "max_tokens": 512},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        log.error("请求没发出去:%s", e)
        sys.exit(2)

    log.debug("HTTP %s  body=%s", r.status_code, r.text[:500])
    if r.status_code != 200:
        log.error("非 200,平台原话:%s", r.text[:300])
        sys.exit(2)

    data = r.json()

    # ---- Turn 1: did the model call the tool? ----
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    finish = choice.get("finish_reason")
    tool_calls = msg.get("tool_calls") or []
    print("---- turn 1 ----")
    print(f"finish_reason={finish}  content={msg.get('content')!r}")
    print(f"tool_calls={len(tool_calls)}")
    for tc in tool_calls:
        fn = (tc.get("function") or {})
        print(f"  id={tc.get('id')} name={fn.get('name')} arguments={fn.get('arguments')!r}")
    print(f"usage={data.get('usage')}")

    if not tool_calls:
        print("VERDICT: 模型没调用工具,直接答了(或平台没回 tool_calls)——这条路不通")
        sys.exit(1)

    # ---- Turn 2: feed a fake tool result back, does the loop close? ----
    fake_page = "光合作用\n浮游植物的关键色素是叶绿素 a\n叶绿素 a 的吸收峰在 430nm 附近(蓝紫光区)\n红光区还有第二个吸收峰,约 660nm"
    messages.append(msg)  # assistant message carrying tool_calls, verbatim
    for tc in tool_calls:
        messages.append({"role": "tool", "tool_call_id": tc.get("id"), "content": fake_page})

    try:
        r2 = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "tools": tools, "max_tokens": 512},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        log.error("第二轮请求没发出去:%s", e)
        sys.exit(2)

    log.debug("HTTP %s  body=%s", r2.status_code, r2.text[:500])
    if r2.status_code != 200:
        log.error("第二轮非 200,平台原话:%s", r2.text[:300])
        sys.exit(2)

    data2 = r2.json()
    choice2 = (data2.get("choices") or [{}])[0]
    msg2 = choice2.get("message") or {}
    print("---- turn 2 ----")
    print(f"finish_reason={choice2.get('finish_reason')}  content={msg2.get('content')!r}")
    print(f"tool_calls={len(msg2.get('tool_calls') or [])}")
    print(f"usage={data2.get('usage')}")
    print("VERDICT: 完整走通一轮 tool 调用 + 回填 —— 这条路通")
    sys.exit(0)


if __name__ == "__main__":
    main()
