import json
import logging
import mimetypes
import os
import re
import traceback

from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from langchain_core.messages import AIMessage

from agent_spine import audit
from agent_spine.approvals import approval_decide
from agent_spine.auth import AuthenticationError, AuthorizationError, Principal
from agent_spine.auth import require_scope, resolve_principal, resolve_session
from agent_spine.context import RuntimeContext
from agent_spine.model import config_from_env, make_chat_model
from agent_spine.mcp_gateway import MCPGateway
from agent_spine.store import Store

from circle_agent.agent import AGENT_VERSION, build_agent, resume, run_message
from circle_agent.profiles import profile_authorize, profile_get
from circle_agent.rag_service import document_ingest
from circle_agent.webhooks import CircleWebhookVerifier, webhook_process


log = logging.getLogger(__name__)
THREAD_ID = re.compile(r'^[A-Za-z0-9._:-]{1,128}$')


class ApiError(Exception):

    def __init__(self, status, code, message):
        self.status = int(status)
        self.code = code
        self.message = message


def content_text(result):
    final = result.get('final') or {}
    if final.get('assistant_message'):
        return str(final['assistant_message'])
    messages = result.get('messages') or []
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.content:
            return str(message.content)
    return ''


def interrupt_data(result):
    interrupts = result.get('__interrupt__') or []
    if not interrupts:
        return None
    item = interrupts[0]
    value = item.value if hasattr(item, 'value') else item
    return value


def principal_from_membership(row, organization_id, principal_id):
    principal = Principal(
        principal_id=principal_id,
        organization_id=organization_id,
        display_name=row['display_name'],
        roles=row['roles'],
        scopes=row['scopes'],
        auth_method='thread_resume',
    )
    return principal


class CircleApplication:

    def __init__(self, db_path, checkpoint_db, ui_dir=None, model=None):
        self.db_path = os.path.abspath(db_path)
        self.checkpoint_db = os.path.abspath(checkpoint_db)
        self.ui_dir = Path(ui_dir or os.path.join(os.path.dirname(__file__), '..', 'ui')).resolve()
        self.store = Store(self.db_path)
        self.store.migrate()
        self.model = model or make_chat_model(config_from_env())
        self.graphs = {}
        mcp_config = os.environ.get(
            'CIRCLE_MCP_CONFIG', str(Path(__file__).resolve().parents[1] / 'mcp_servers.json'),
        )
        self.mcp_gateway = MCPGateway(mcp_config)
        self.mcp_tools = None
        self.webhook_verifier = CircleWebhookVerifier(
            base_url=os.environ.get('CIRCLE_API_HOST', 'https://api.circle.com'),
        )

    def graph_get(self, profile):
        profile = profile_get(profile)['name']
        if profile not in self.graphs:
            profile_data = profile_get(profile)
            extra_tools = []
            if profile_data['mcp']:
                if self.mcp_tools is None:
                    self.mcp_tools = self.mcp_gateway.load()
                extra_tools = self.mcp_tools
            self.graphs[profile] = build_agent(
                profile=profile, model=self.model, checkpoint_db=self.checkpoint_db,
                extra_tools=extra_tools,
            )
        return self.graphs[profile]

    def context_make(self, principal, thread_id, profile, request_id='', run_id=''):
        ctx = RuntimeContext(
            request_id=request_id or 'req_%s' % uuid4().hex,
            run_id=run_id or 'run_%s' % uuid4().hex,
            thread_id=thread_id,
            principal=principal,
            agent_name='circle',
            agent_version=AGENT_VERSION,
            profile=profile_get(profile)['name'],
            trace_metadata={'environment': 'local-lab'},
            db_path=self.db_path,
        )
        return ctx

    def message_run(self, principal, thread_id, profile, message, request_id=''):
        require_scope(principal, 'agent:chat')
        if not THREAD_ID.match(thread_id):
            raise ValueError('thread_id is invalid')
        if len(message.encode('utf-8')) > 65536:
            raise ValueError('message exceeds 64 KiB')
        existing = self.store.thread_get(principal.organization_id, thread_id)
        if existing and existing['principal_id'] != principal.principal_id:
            raise AuthorizationError('thread belongs to another principal')
        if existing:
            profile = existing['profile']
        else:
            profile = profile_authorize(principal, profile)
        self.store.thread_upsert(
            principal.organization_id, principal.principal_id, thread_id, profile,
            title=message[:80],
        )
        ctx = self.context_make(principal, thread_id, profile, request_id=request_id)
        self.store.message_add(
            principal.organization_id, thread_id, principal.principal_id,
            'user', message, ctx.run_id,
        )
        audit.emit(self.store, ctx, 'run_started', 'thread', thread_id, 'started', 'user_message')
        result = run_message(ctx, message, graph=self.graph_get(profile))
        pending = interrupt_data(result)
        text = content_text(result)
        if text:
            self.store.message_add(
                principal.organization_id, thread_id, principal.principal_id,
                'assistant', text, ctx.run_id,
            )
        failed = (result.get('final') or {}).get('status') == 'error'
        status = 'approval_required' if pending else ('failed' if failed else 'completed')
        audit.emit(self.store, ctx, 'run_finished', 'thread', thread_id, status, status)
        response = {
            'request_id': ctx.request_id,
            'run_id': ctx.run_id,
            'thread_id': thread_id,
            'profile': profile,
            'status': status,
            'message': text,
            'approval': pending,
        }
        return response

    def approval_decide_and_resume(self, reviewer, approval_id, decision, reason=''):
        require_scope(reviewer, 'circle:approval:decide')
        approval = self.store.approval_get(reviewer.organization_id, approval_id)
        if approval is None:
            raise ApiError(404, 'not_found', 'approval request not found')
        action = self.store.action_get(reviewer.organization_id, approval['action_id'])
        result = approval_decide(
            self.store, reviewer, approval_id, decision, approval['action_digest'], reason,
        )
        if decision == 'reject':
            result['resume_status'] = 'rejected'
            return result

        membership = self.store.principal_membership_get(
            reviewer.organization_id, action['actor_id'],
        )
        if membership is None:
            raise ApiError(409, 'thread_actor_missing', 'original thread actor is unavailable')
        requester = principal_from_membership(membership, reviewer.organization_id, action['actor_id'])
        thread = self.store.thread_get(reviewer.organization_id, action['thread_id'])
        if thread is None:
            raise ApiError(409, 'thread_missing', 'approval thread is unavailable')
        profile_authorize(requester, thread['profile'])
        ctx = self.context_make(requester, action['thread_id'], thread['profile'])
        graph = self.graph_get(thread['profile'])
        resumed = resume(ctx, {'approval_id': approval_id, 'decision': decision}, graph=graph)
        text = content_text(resumed)
        if text:
            self.store.message_add(
                reviewer.organization_id, action['thread_id'], requester.principal_id,
                'assistant', text, ctx.run_id,
            )
        result['resume_status'] = 'completed'
        result['thread_id'] = action['thread_id']
        result['message'] = text
        return result


class CircleRequestHandler(BaseHTTPRequestHandler):

    server_version = 'CircleAgentLab/1.0'

    @property
    def app(self):
        return self.server.app

    def log_message(self, fmt, *args):
        log.info('http %s', fmt % args)

    def request_id(self):
        value = self.headers.get('X-Request-ID', '')
        return value[:128] or 'req_%s' % uuid4().hex

    def body_read(self):
        length = int(self.headers.get('Content-Length', '0') or 0)
        if length > 1024 * 1024:
            raise ApiError(413, 'body_too_large', 'request body exceeds 1 MiB')
        return self.rfile.read(length)

    def json_read(self):
        raw = self.body_read()
        try:
            value = json.loads(raw.decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, 'invalid_json', 'request body must be valid JSON')
        if not isinstance(value, dict):
            raise ApiError(400, 'invalid_json', 'request body must be a JSON object')
        return value

    def response_json(self, status, payload, headers=None):
        raw = json.dumps(payload, sort_keys=True).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(raw)

    def response_file(self, path):
        if not path.exists() or not path.is_file() or self.app.ui_dir not in path.parents:
            raise ApiError(404, 'not_found', 'asset not found')
        raw = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'")
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.end_headers()
        self.wfile.write(raw)

    def cookie_get(self, name):
        cookie = SimpleCookie(self.headers.get('Cookie', ''))
        item = cookie.get(name)
        return item.value if item else ''

    def principal_get(self, require_csrf=False):
        authorization = self.headers.get('Authorization', '')
        if authorization.startswith('Bearer '):
            return resolve_principal(self.app.store, authorization[7:].strip())
        session_token = self.cookie_get('circle_session')
        if not session_token:
            raise AuthenticationError('authentication is required')
        principal, csrf_token = resolve_session(self.app.store, session_token)
        if require_csrf and self.headers.get('X-CSRF-Token', '') != csrf_token:
            raise AuthorizationError('valid CSRF token is required')
        return principal

    def dispatch(self, method):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/') or '/'
        parts = [item for item in path.split('/') if item]

        if method == 'GET' and path == '/':
            return self.response_file(self.app.ui_dir / 'index.html')
        if method == 'GET' and path.startswith('/assets/'):
            name = path[len('/assets/'):]
            if '/' in name or '..' in name:
                raise ApiError(404, 'not_found', 'asset not found')
            return self.response_file(self.app.ui_dir / name)
        if method == 'GET' and path == '/healthz':
            return self.response_json(200, {'status': 'ok', 'agent_version': AGENT_VERSION})
        if method == 'GET' and path == '/readyz':
            self.app.store.connect().close()
            return self.response_json(200, {'status': 'ready'})
        if method == 'GET' and path == '/openapi.yaml':
            docs_path = Path(__file__).resolve().parents[2] / 'docs' / 'api' / 'openapi.yaml'
            return self.response_file_external(docs_path, 'application/yaml')
        if method == 'POST' and path == '/api/v1/sessions':
            data = self.json_read()
            principal = resolve_principal(self.app.store, data.get('token', ''))
            expires_at = datetime.now(timezone.utc) + timedelta(hours=8)
            session, csrf_token = self.app.store.session_create(
                principal.organization_id, principal.principal_id, expires_at.isoformat(),
            )
            cookie = 'circle_session=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=28800' % session
            if os.environ.get('COOKIE_SECURE', '').lower() == 'true':
                cookie += '; Secure'
            return self.response_json(201, {'csrf_token': csrf_token, 'principal': principal.to_dict()},
                                      {'Set-Cookie': cookie})
        if method == 'POST' and parts == ['api', 'v1', 'webhooks', 'circle']:
            body = self.body_read()
            result = webhook_process(
                self.app.store, body,
                self.headers.get('X-Circle-Signature', ''),
                self.headers.get('X-Circle-Key-Id', ''),
                self.app.webhook_verifier,
            )
            return self.response_json(200, result)

        mutating = method in ['POST', 'PUT', 'PATCH', 'DELETE']
        bearer_request = self.headers.get('Authorization', '').startswith('Bearer ')
        principal = self.principal_get(require_csrf=mutating and not bearer_request)

        if method == 'GET' and path == '/api/v1/me':
            return self.response_json(200, {'principal': principal.to_dict()})
        if method == 'DELETE' and path == '/api/v1/sessions/current':
            session_token = self.cookie_get('circle_session')
            if session_token:
                session_id = session_token.split('.', 1)[0][4:]
                self.app.store.session_revoke(session_id)
            return self.response_json(200, {'status': 'signed_out'},
                                      {'Set-Cookie': 'circle_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'})
        if method == 'GET' and path == '/api/v1/threads':
            rows = self.app.store.thread_list(principal.organization_id, principal.principal_id)
            return self.response_json(200, {'items': rows})
        if method == 'POST' and path == '/api/v1/threads':
            data = self.json_read()
            profile = profile_authorize(principal, data.get('profile', 'full-sim'))
            thread_id = str(data.get('thread_id') or 'thread_%s' % uuid4().hex)
            if not THREAD_ID.match(thread_id):
                raise ApiError(400, 'invalid_thread_id', 'thread_id is invalid')
            self.app.store.thread_upsert(
                principal.organization_id, principal.principal_id, thread_id, profile,
                title=str(data.get('title', ''))[:160],
            )
            return self.response_json(201, {'thread_id': thread_id, 'profile': profile})
        if len(parts) == 5 and parts[:3] == ['api', 'v1', 'threads'] and parts[4] == 'messages':
            thread_id = parts[3]
            if method == 'GET':
                thread = self.app.store.thread_get(principal.organization_id, thread_id)
                if thread is None or thread['principal_id'] != principal.principal_id:
                    raise ApiError(404, 'not_found', 'thread not found')
                rows = self.app.store.message_list(principal.organization_id, thread_id)
                return self.response_json(200, {'items': rows})
            if method == 'POST':
                data = self.json_read()
                message = str(data.get('message', '')).strip()
                if not message:
                    raise ApiError(400, 'message_required', 'message is required')
                profile = data.get('profile', 'full-sim')
                response = self.app.message_run(
                    principal, thread_id, profile, message, request_id=self.request_id(),
                )
                return self.response_json(200, response)
        if method == 'GET' and path == '/api/v1/approvals':
            require_scope(principal, 'circle:approval:decide')
            status = parse_qs(parsed.query).get('status', ['pending'])[0]
            rows = self.app.store.approval_detail_list(principal.organization_id, status)
            return self.response_json(200, {'items': rows})
        if method == 'POST' and len(parts) == 5 and parts[:3] == ['api', 'v1', 'approvals'] and parts[4] == 'decisions':
            data = self.json_read()
            result = self.app.approval_decide_and_resume(
                principal, parts[3], data.get('decision', ''), str(data.get('reason', '')),
            )
            return self.response_json(200, result)
        if method == 'GET' and len(parts) == 4 and parts[:3] == ['api', 'v1', 'transactions']:
            transaction = self.app.store.transaction_get(principal.organization_id, parts[3])
            if transaction is None:
                raise ApiError(404, 'not_found', 'transaction not found')
            return self.response_json(200, transaction)
        if method == 'GET' and path == '/api/v1/events':
            thread_id = parse_qs(parsed.query).get('thread_id', [''])[0]
            thread = self.app.store.thread_get(principal.organization_id, thread_id)
            if thread is None or (thread['principal_id'] != principal.principal_id and not principal.has_role('reviewer')):
                raise ApiError(404, 'not_found', 'thread not found')
            events = self.app.store.audit_list(principal.organization_id, thread_id)
            return self.response_sse(events)
        if method == 'GET' and path == '/api/v1/documents':
            require_scope(principal, 'policy:read')
            return self.response_json(200, {'items': self.app.store.document_list(principal.organization_id)})
        if method == 'POST' and path == '/api/v1/documents':
            require_scope(principal, 'policy:write')
            data = self.json_read()
            result = document_ingest(
                self.app.store, principal.organization_id, str(data.get('source_name', '')),
                str(data.get('version', '')), str(data.get('content', '')),
                principal.principal_id, visibility='tenant', sensitivity='internal',
            )
            return self.response_json(201, result)
        if method == 'GET' and path == '/api/v1/memories':
            require_scope(principal, 'memory:read')
            thread_id = parse_qs(parsed.query).get('thread_id', [''])[0] or None
            if thread_id:
                thread = self.app.store.thread_get(principal.organization_id, thread_id)
                if thread is None or thread['principal_id'] != principal.principal_id:
                    raise ApiError(404, 'not_found', 'thread not found')
            rows = self.app.store.memory_list(principal.organization_id,
                                              principal.principal_id, thread_id=thread_id)
            return self.response_json(200, {'items': rows})
        if method == 'POST' and path == '/api/v1/memories':
            require_scope(principal, 'memory:write')
            data = self.json_read()
            thread_id = str(data.get('thread_id', ''))
            thread = self.app.store.thread_get(principal.organization_id, thread_id)
            if thread is None or thread['principal_id'] != principal.principal_id:
                raise ApiError(404, 'not_found', 'thread not found')
            sensitivity = str(data.get('sensitivity', 'private'))
            if sensitivity not in ['private', 'internal']:
                raise ApiError(400, 'invalid_sensitivity', 'memory sensitivity is invalid')
            content = str(data.get('content', '')).strip()
            if not content:
                raise ApiError(400, 'content_required', 'memory content is required')
            expires_at = data.get('expires_at')
            if expires_at:
                expiry = datetime.fromisoformat(str(expires_at))
                if expiry.tzinfo is None:
                    raise ApiError(400, 'invalid_expiry', 'memory expiry requires a timezone')
            memory_id = self.app.store.memory_add(
                principal.organization_id, principal.principal_id, thread_id,
                str(data.get('memory_type', 'user_note')), content,
                sensitivity, 'user_explicit', expires_at,
            )
            return self.response_json(201, {'memory_id': memory_id})
        if method == 'DELETE' and len(parts) == 4 and parts[:3] == ['api', 'v1', 'memories']:
            require_scope(principal, 'memory:write')
            deleted = self.app.store.memory_delete(
                principal.organization_id, principal.principal_id, parts[3],
            )
            if not deleted:
                raise ApiError(404, 'not_found', 'memory not found')
            return self.response_json(200, {'status': 'deleted'})
        if method == 'POST' and path in ['/chat', '/v1/chat/completions']:
            data = self.json_read()
            if path == '/chat':
                message = str(data.get('message') or data.get('input') or '')
                if not message.strip():
                    raise ApiError(400, 'message_required', 'message is required')
                profile = data.get('profile', 'full-sim')
                thread_id = str(data.get('thread_id') or 'thread_%s' % uuid4().hex)
                result = self.app.message_run(principal, thread_id, profile, message, self.request_id())
                return self.response_json(200, result)
            messages = data.get('messages') or []
            user_messages = [item for item in messages if item.get('role') == 'user']
            if not user_messages:
                raise ApiError(400, 'message_required', 'a user message is required')
            message = str(user_messages[-1].get('content', ''))
            profile = data.get('model', 'full-sim')
            thread_id = str(data.get('thread_id') or 'thread_%s' % uuid4().hex)
            result = self.app.message_run(principal, thread_id, profile, message, self.request_id())
            choice = {'index': 0, 'message': {'role': 'assistant', 'content': result['message']}, 'finish_reason': 'stop'}
            payload = {
                'id': result['run_id'], 'object': 'chat.completion', 'model': profile,
                'choices': [choice], 'circle': {'status': result['status'], 'approval': result['approval'],
                                                'thread_id': thread_id},
            }
            if data.get('stream') is True:
                return self.response_openai_stream(payload)
            return self.response_json(200, payload)
        raise ApiError(404, 'not_found', 'route not found')

    def response_file_external(self, path, content_type):
        if not path.exists():
            raise ApiError(404, 'not_found', 'document not found')
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def response_sse(self, events):
        lines = []
        for event in events:
            lines.append('event: audit')
            lines.append('data: %s' % json.dumps(event, sort_keys=True))
            lines.append('')
        raw = ('\n'.join(lines) + '\n').encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def response_openai_stream(self, payload):
        choice = payload['choices'][0]
        chunk = {
            'id': payload['id'], 'object': 'chat.completion.chunk', 'model': payload['model'],
            'choices': [{'index': 0, 'delta': choice['message'],
                         'finish_reason': choice['finish_reason']}],
            'circle': payload['circle'],
        }
        raw = ('data: %s\n\ndata: [DONE]\n\n' % json.dumps(chunk, sort_keys=True)).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def handle_method(self, method):
        try:
            self.dispatch(method)
        except AuthenticationError as exc:
            self.response_json(401, {'error': {'code': 'unauthenticated', 'message': str(exc)}})
        except AuthorizationError as exc:
            self.response_json(403, {'error': {'code': 'forbidden', 'message': str(exc)}})
        except ApiError as exc:
            self.response_json(exc.status, {'error': {'code': exc.code, 'message': exc.message}})
        except (ValueError, KeyError) as exc:
            self.response_json(400, {'error': {'code': 'invalid_request', 'message': str(exc)}})
        except Exception:
            request_id = self.request_id()
            log.error('unhandled request error request_id=%s\n%s', request_id, traceback.format_exc())
            self.response_json(500, {'error': {'code': 'internal_error', 'message': 'request failed',
                                               'request_id': request_id}})

    def do_GET(self):
        self.handle_method('GET')

    def do_POST(self):
        self.handle_method('POST')

    def do_DELETE(self):
        self.handle_method('DELETE')


class CircleHttpServer(ThreadingHTTPServer):

    daemon_threads = True

    def __init__(self, address, app):
        self.app = app
        ThreadingHTTPServer.__init__(self, address, CircleRequestHandler)


def serve(host, port, app):
    if host not in ['127.0.0.1', '::1', 'localhost'] and os.environ.get('ALLOW_NON_LOOPBACK', '') != 'true':
        raise ValueError('non-loopback binding requires ALLOW_NON_LOOPBACK=true')
    server = CircleHttpServer((host, int(port)), app)
    log.info('circle agent serving host=%s port=%s', host, port)
    server.serve_forever()
