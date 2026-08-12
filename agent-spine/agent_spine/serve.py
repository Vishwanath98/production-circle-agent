# agent_spine/serve.py
#
# Self-serving HTTP endpoint for a decision-pipeline agent (circle / onboarding
# / wellcheck). Lets an agent expose its OWN ``POST /chat`` instead of routing
# through a separate adapter process: Scrimmage points ``Agent.api_url`` straight
# at the agent's serve.py and gets the same uniform response shape back, trace
# events included.
#
# This is the reusable core that used to live in scrimmage-adapter/adapter.py;
# it belongs in the spine because every decision-pipeline agent needs the exact
# same server. Per-agent specifics (plain-text input defaults, which final-state
# key is the human message) are passed in by the agent's own serve.py.
#
# Wire contract (unchanged from the adapter):
#   Request:  POST /chat  {customer_id?, thread_id?, message}
#   Response: 200 OK      {assistant_message, status, tool_call, usage}

import json
import logging
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("agent_spine.serve")


def response_body(result):
    final = result.get('final', {}) or {}
    body = {
        'assistant_message': final.get('assistant_message', ''),
        'status': final.get('status'),
        'tool_call': final.get('tool_call'),
        'usage': final.get('usage', {}),
    }
    if final.get('decision') is not None:
        body['decision'] = final['decision']
    return body


def _usage_tracker():
    """A LangChain callback that sums token usage across the run."""
    from langchain_core.callbacks import BaseCallbackHandler

    class _Tracker(BaseCallbackHandler):
        def __init__(self):
            self.input_tokens = 0
            self.output_tokens = 0

        def on_llm_end(self, response, **kw):
            for gen_list in response.generations:
                for gen in gen_list:
                    message = getattr(gen, "message", None)
                    if message is None:
                        continue
                    usage = getattr(message, "usage_metadata", None) or {}
                    self.input_tokens += int(usage.get("input_tokens", 0) or 0)
                    self.output_tokens += int(usage.get("output_tokens", 0) or 0)

    return _Tracker()


def build_run(agent_module, *, plaintext_defaults=None, plaintext_key="message",
              outcome_keys=("receipt_message", "confirmation_message", "outcome_message"),
              decision_keys=("decision", "eligibility_status", "resolution"),
              trace_name="agent-chat"):
    """Return a ``run(message, thread_id)`` callable for one agent module.

    ``agent_module`` exposes ``run(input_dict, llm_override=, verbose=, trace=)``.
    ``plaintext_defaults`` lifts a plain-English message into the agent's input
    dict (Scrimmage's coverage generator emits prose, not JSON); ``plaintext_key``
    is where the prose lands in that dict.
    """
    plaintext_defaults = plaintext_defaults or {}
    model = os.environ.get("AGENT_MODEL", "claude-sonnet-4-5")
    trace_enabled = os.environ.get("LANGSMITH_TRACING", "").lower() in ("1", "true", "yes")
    traceable = None
    if trace_enabled:
        try:
            from langsmith import traceable as langsmith_traceable
        except ImportError:
            log.warning("langsmith tracing requested but langsmith is not installed")
        else:
            traceable = langsmith_traceable

    def _parse_input(raw_message):
        if isinstance(raw_message, dict):
            return raw_message
        if not isinstance(raw_message, str):
            raise ValueError("decision-pipeline agents require a string or dict message")
        s = raw_message.strip()
        if s.startswith("{"):
            return json.loads(s)
        wrapped = dict(plaintext_defaults)
        wrapped[plaintext_key] = s
        return wrapped

    def run(message, thread_id):
        try:
            input_dict = _parse_input(message)
        except (ValueError, TypeError) as exc:
            return {"final": {"assistant_message": "Bad input: %s" % exc,
                              "status": "error", "tool_call": None, "usage": {}}}

        # Build the LLM lazily, inside the request, so importing/serving this
        # module (and the /healthz probe) never needs an API key.
        from langchain_anthropic import ChatAnthropic
        tracker = _usage_tracker()
        llm = ChatAnthropic(model=model, api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
                            temperature=0.1, callbacks=[tracker])

        agent_error = None
        final = {}
        try:
            if traceable is not None:
                @traceable(name=trace_name, run_type="chain")
                def run_traced(input_dict, thread_id):
                    rv = agent_module.run(input_dict, llm_override=llm, verbose=False, trace=True)
                    return rv

                final = run_traced(input_dict=input_dict, thread_id=thread_id)
            else:
                final = agent_module.run(input_dict, llm_override=llm, verbose=False, trace=True)
        except Exception as exc:  # noqa: BLE001 -- log + surface as status=error
            log.exception("agent run failed")
            agent_error = str(exc)

        usage = {"input_tokens": tracker.input_tokens,
                 "output_tokens": tracker.output_tokens,
                 "total_tokens": tracker.input_tokens + tracker.output_tokens}

        if agent_error is not None:
            return {"final": {"assistant_message": "Agent error: %s" % agent_error,
                              "status": "error", "tool_call": None, "usage": usage}}

        assistant_message = next(
            (final[k] for k in outcome_keys if final.get(k)),
            "Decision: %s" % next((final.get(k) for k in decision_keys if final.get(k)), "n/a"),
        )
        return {"final": {"assistant_message": assistant_message, "status": "ok",
                          "tool_call": None, "usage": usage,
                          "decision": next((final.get(k) for k in decision_keys if final.get(k)), None)}}

    return run


def make_handler(run_fn, backend_label):
    class ChatHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log.info("%s - %s", self.address_string(), fmt % args)

        def _write_json(self, status_code, body):
            payload = json.dumps(body, default=str).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path in ("/", "/healthz"):
                self._write_json(200, {"status": "ok", "backend": backend_label})
                return
            self._write_json(404, {"error": "Not Found"})

        def do_POST(self):
            if self.path not in ("/chat", "/"):
                self._write_json(404, {"error": "Not Found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                request_body = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                self._write_json(400, {"error": "Invalid JSON body"})
                return

            message = request_body.get("message") or ""
            thread_id = request_body.get("thread_id") or ("scrimmage-" + uuid.uuid4().hex[:8])
            if not message:
                self._write_json(400, {"error": "message is required"})
                return

            try:
                result = run_fn(message=message, thread_id=thread_id)
                try:
                    from langchain_core.tracers.langchain import wait_for_all_tracers
                    wait_for_all_tracers()
                except Exception:
                    pass
            except Exception as exc:  # noqa: BLE001
                log.exception("agent run failed")
                self._write_json(500, {"error": str(exc)[:512]})
                return

            final = result.get("final", {}) or {}
            body = response_body(result)
            http_status = 200 if final.get("status") != "error" else 502
            self._write_json(http_status, body)

    return ChatHandler


def run_server(agent_module, *, backend_label, host=None, port=None, **build_kwargs):
    """Start a self-serving /chat endpoint for ``agent_module``.

    Called from an agent's own serve.py. ``build_kwargs`` are forwarded to
    ``build_run`` (plaintext_defaults, plaintext_key, outcome_keys, ...).
    """
    host = host or os.environ.get("ADAPTER_HOST", "0.0.0.0")
    port = int(port or os.environ.get("ADAPTER_PORT", os.environ.get("PORT", "8082")))
    run_fn = build_run(agent_module, trace_name=backend_label, **build_kwargs)
    handler = make_handler(run_fn, backend_label)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log.info("agent_spine.serve starting backend=%s host=%s port=%s langsmith_tracing=%s project=%s",
             backend_label, host, port,
             os.environ.get("LANGSMITH_TRACING", ""),
             os.environ.get("LANGSMITH_PROJECT", ""))
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("agent_spine.serve stopping (KeyboardInterrupt)")
    finally:
        server.server_close()
