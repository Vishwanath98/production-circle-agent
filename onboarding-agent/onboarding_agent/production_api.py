import json
import logging
import os
import re
import traceback

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from uuid import uuid4

from langchain_core.messages import AIMessage

from agent_spine.approvals import approval_decide
from agent_spine.auth import Principal, AuthenticationError, AuthorizationError
from agent_spine.auth import require_scope, resolve_principal
from agent_spine.context import RuntimeContext
from agent_spine.mcp_gateway import MCPGateway
from agent_spine.model import config_from_env, make_chat_model
from agent_spine.store import Store

from onboarding_agent.production import AGENT_VERSION, build_agent, profile_authorize, profile_validate, resume, run_message


log = logging.getLogger(__name__)
THREAD_ID = re.compile(r'^[A-Za-z0-9._:-]{1,128}$')


def content_text(result):
    final = result.get('final') or {}
    if final.get('assistant_message'):
        return str(final['assistant_message'])
    for message in reversed(result.get('messages') or []):
        if isinstance(message, AIMessage) and message.content:
            return str(message.content)
    return ''


def interrupt_data(result):
    interrupts = result.get('__interrupt__') or []
    if not interrupts:
        return None
    item = interrupts[0]
    return item.value if hasattr(item, 'value') else item


class OnboardingApplication:

    def __init__(self, db_path, checkpoint_db, model=None):
        self.db_path = os.path.abspath(db_path)
        self.checkpoint_db = os.path.abspath(checkpoint_db)
        self.store = Store(self.db_path)
        self.store.migrate()
        self.model = model or make_chat_model(config_from_env())
        config_path = os.environ.get(
            'ONBOARDING_MCP_CONFIG',
            os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mcp_servers.json')),
        )
        self.mcp_gateway = MCPGateway(config_path)
        self.mcp_tools = None
        self.graphs = {}

    def graph_get(self, profile):
        profile = profile_validate(profile)
        if profile not in self.graphs:
            extra_tools = []
            if profile in ['mcp-sim', 'full-sim']:
                if self.mcp_tools is None:
                    self.mcp_tools = self.mcp_gateway.load()
                extra_tools = self.mcp_tools
            self.graphs[profile] = build_agent(
                profile, model=self.model, checkpoint_db=self.checkpoint_db,
                extra_tools=extra_tools,
            )
        return self.graphs[profile]

    def context_make(self, principal, thread_id, profile):
        return RuntimeContext(
            'req_%s' % uuid4().hex, 'run_%s' % uuid4().hex, thread_id,
            principal, 'onboarding', AGENT_VERSION, profile,
            trace_metadata={'environment': 'local-lab'}, db_path=self.db_path,
        )

    def message_run(self, principal, thread_id, profile, message):
        require_scope(principal, 'agent:chat')
        if not THREAD_ID.match(thread_id):
            raise ValueError('thread_id is invalid')
        if len(message.encode('utf-8')) > 65536:
            raise ValueError('message exceeds 64 KiB')
        profile = profile_validate(profile)
        thread = self.store.thread_get(principal.organization_id, thread_id)
        if thread and thread['principal_id'] != principal.principal_id:
            raise AuthorizationError('thread belongs to another principal')
        if thread:
            profile = thread['profile']
        else:
            profile = profile_authorize(principal, profile)
        self.store.thread_upsert(principal.organization_id, principal.principal_id,
                                 thread_id, profile, title=message[:80])
        ctx = self.context_make(principal, thread_id, profile)
        self.store.message_add(principal.organization_id, thread_id, principal.principal_id,
                               'user', message, ctx.run_id)
        result = run_message(ctx, message, graph=self.graph_get(profile))
        pending = interrupt_data(result)
        text = content_text(result)
        if text:
            self.store.message_add(principal.organization_id, thread_id, principal.principal_id,
                                   'assistant', text, ctx.run_id)
        failed = (result.get('final') or {}).get('status') == 'error'
        status = 'approval_required' if pending else ('failed' if failed else 'completed')
        return {'thread_id': thread_id, 'run_id': ctx.run_id, 'profile': profile,
                'status': status,
                'message': text, 'approval': pending}

    def approval_resume(self, reviewer, approval_id, decision, reason=''):
        require_scope(reviewer, 'onboarding:approval:decide')
        approval = self.store.approval_get(reviewer.organization_id, approval_id)
        if approval is None:
            raise ValueError('approval request not found')
        action = self.store.action_get(reviewer.organization_id, approval['action_id'])
        result = approval_decide(self.store, reviewer, approval_id, decision,
                                 approval['action_digest'], reason)
        if decision == 'reject':
            application = self.store.onboarding_application_by_action(
                reviewer.organization_id, action['action_id'],
            )
            if application:
                self.store.onboarding_application_finalize(
                    reviewer.organization_id, application['application_id'],
                    'pending_review', 'rejected', None,
                )
            return result
        membership = self.store.principal_membership_get(reviewer.organization_id, action['actor_id'])
        if membership is None:
            raise ValueError('original application actor is unavailable')
        requester = Principal(
            action['actor_id'], reviewer.organization_id, membership['display_name'],
            membership['roles'], membership['scopes'], auth_method='thread_resume',
        )
        thread = self.store.thread_get(reviewer.organization_id, action['thread_id'])
        profile_authorize(requester, thread['profile'])
        ctx = self.context_make(requester, action['thread_id'], thread['profile'])
        resumed = resume(ctx, {'approval_id': approval_id, 'decision': decision},
                         graph=self.graph_get(thread['profile']))
        result['message'] = content_text(resumed)
        result['thread_id'] = action['thread_id']
        return result


class OnboardingHandler(BaseHTTPRequestHandler):

    @property
    def app(self):
        return self.server.app

    def log_message(self, fmt, *args):
        log.info('http %s', fmt % args)

    def json_read(self):
        length = int(self.headers.get('Content-Length', '0') or 0)
        if length > 1024 * 1024:
            raise ValueError('request body exceeds 1 MiB')
        value = json.loads(self.rfile.read(length).decode('utf-8') or '{}')
        if not isinstance(value, dict):
            raise ValueError('request body must be an object')
        return value

    def response(self, status, payload):
        raw = json.dumps(payload, sort_keys=True).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.end_headers()
        self.wfile.write(raw)

    def principal_get(self):
        authorization = self.headers.get('Authorization', '')
        if not authorization.startswith('Bearer '):
            raise AuthenticationError('bearer authentication is required')
        return resolve_principal(self.app.store, authorization[7:].strip())

    def dispatch(self, method):
        path = urlparse(self.path).path.rstrip('/') or '/'
        parts = [item for item in path.split('/') if item]
        if method == 'GET' and path == '/healthz':
            return self.response(200, {'status': 'ok', 'agent_version': AGENT_VERSION})
        if method == 'GET' and path == '/readyz':
            self.app.store.connect().close()
            return self.response(200, {'status': 'ready'})
        principal = self.principal_get()
        if method == 'POST' and path == '/chat':
            data = self.json_read()
            thread_id = str(data.get('thread_id') or 'thread_%s' % uuid4().hex)
            message = str(data.get('message') or data.get('input') or '')
            if not message.strip():
                raise ValueError('message is required')
            result = self.app.message_run(principal, thread_id,
                                          data.get('profile', 'full-sim'), message)
            return self.response(200, result)
        if method == 'GET' and path == '/api/v1/approvals':
            require_scope(principal, 'onboarding:approval:decide')
            return self.response(200, {'items': self.app.store.approval_detail_list(
                principal.organization_id, 'pending')})
        if method == 'POST' and len(parts) == 5 and parts[:3] == ['api', 'v1', 'approvals'] and parts[4] == 'decisions':
            data = self.json_read()
            result = self.app.approval_resume(principal, parts[3], data.get('decision', ''),
                                              str(data.get('reason', '')))
            return self.response(200, result)
        if method == 'GET' and len(parts) == 4 and parts[:3] == ['api', 'v1', 'applications']:
            require_scope(principal, 'onboarding:read')
            application = self.app.store.onboarding_application_get(principal.organization_id, parts[3])
            if application is None:
                return self.response(404, {'error': {'code': 'not_found', 'message': 'application not found'}})
            return self.response(200, application)
        return self.response(404, {'error': {'code': 'not_found', 'message': 'route not found'}})

    def handle_method(self, method):
        try:
            self.dispatch(method)
        except AuthenticationError as exc:
            self.response(401, {'error': {'code': 'unauthenticated', 'message': str(exc)}})
        except AuthorizationError as exc:
            self.response(403, {'error': {'code': 'forbidden', 'message': str(exc)}})
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self.response(400, {'error': {'code': 'invalid_request', 'message': str(exc)}})
        except Exception:
            request_id = 'req_%s' % uuid4().hex
            log.error('onboarding request failed request_id=%s\n%s', request_id, traceback.format_exc())
            self.response(500, {'error': {'code': 'internal_error', 'message': 'request failed',
                                          'request_id': request_id}})

    def do_GET(self):
        self.handle_method('GET')

    def do_POST(self):
        self.handle_method('POST')


class OnboardingHttpServer(ThreadingHTTPServer):

    daemon_threads = True

    def __init__(self, address, app):
        self.app = app
        ThreadingHTTPServer.__init__(self, address, OnboardingHandler)
