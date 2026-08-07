import hashlib
import hmac
import json
import logging
import os

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

AGENT_WEBHOOK_SECRET = os.environ.get('AGENT_WEBHOOK_SECRET', '')


def _verify(body: bytes, signature: str | None) -> bool:
    if not signature or not AGENT_WEBHOOK_SECRET:
        return False
    expected = hmac.new(AGENT_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _verify_bearer(header: str | None) -> bool:
    if not header or not AGENT_WEBHOOK_SECRET:
        return False
    prefix = 'Bearer '
    if not header.startswith(prefix):
        return False
    return hmac.compare_digest(header[len(prefix):], AGENT_WEBHOOK_SECRET)


class AgentReplyController(http.Controller):

    def _json_response(self, payload, status=200):
        return request.make_response(
            json.dumps(payload),
            status=status,
            headers=[('Content-Type', 'application/json')],
        )

    @http.route(
        '/ai_agent/reply',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
        save_session=False,
    )
    def reply(self, **kwargs):
        """Receive the agent's reply and post it into the Discuss channel as
        the bot partner. Authenticated by AGENT_WEBHOOK_SECRET (shared with
        the agent pod via K8s Secret) — same HMAC scheme as the outbound
        hook, verified in models/discuss_channel.py's _post_hook. type='http'
        (not 'json') so an unauthenticated caller gets a real HTTP 401,
        matching the convention in payment_qr_mercantil/controllers/main.py.
        """
        raw = request.httprequest.get_data()
        signature = request.httprequest.headers.get('X-Agent-Signature')
        if not _verify(raw, signature):
            return self._json_response({'status': 'error', 'message': 'unauthorized'}, status=401)

        try:
            payload = json.loads(raw)
        except ValueError:
            return self._json_response({'status': 'error', 'message': 'bad request'}, status=400)

        channel_id = payload.get('channel_id')
        text = (payload.get('text') or '').strip()
        if not channel_id or not text:
            return self._json_response({'status': 'error', 'message': 'bad request'}, status=400)

        channel = request.env['discuss.channel'].sudo().browse(channel_id).exists()
        if not channel:
            return self._json_response({'status': 'error', 'message': 'unknown channel'}, status=404)

        bot = request.env.ref('saas_ai_agent.partner_agent_bot', raise_if_not_found=False)
        if not bot:
            _logger.error("saas_ai_agent: bot partner missing, cannot post agent reply")
            return self._json_response({'status': 'error', 'message': 'bot partner missing'}, status=200)

        try:
            channel.sudo().message_post(
                body=text,
                author_id=bot.id,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
        except Exception:
            _logger.exception("saas_ai_agent: failed to post agent reply into channel %s", channel_id)
            return self._json_response({'status': 'error', 'message': 'post failed'}, status=200)

        return self._json_response({'status': 'ok'})

    @http.route(
        '/ai_agent/llm_config',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
        save_session=False,
    )
    def llm_config(self, **kwargs):
        """BYOK: the agent pod fetches the tenant's own AI-provider
        credentials here on each turn instead of a static env var, so a
        key change in Settings takes effect on the next message with no
        redeploy. Authenticated the same way as the rest of the
        odoo<->agent channel (AGENT_WEBHOOK_SECRET) plus the tenant
        NetworkPolicy — this is not internet-facing in practice, but the
        key itself never leaves this hop either way.
        """
        if not _verify_bearer(request.httprequest.headers.get('Authorization')):
            return self._json_response({'status': 'error', 'message': 'unauthorized'}, status=401)

        config = request.env['res.config.settings'].sudo()._aei_assistant_resolve_llm_config()
        return self._json_response(config)
