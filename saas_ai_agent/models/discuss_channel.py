import json
import logging
import os

import requests

from markupsafe import Markup

from odoo import models
from odoo.tools import html2plaintext

logger = logging.getLogger(__name__)

AGENT_WEBHOOK_SECRET = os.environ.get('AGENT_WEBHOOK_SECRET', '')
AGENT_URL = os.environ.get('AGENT_URL', 'http://agent:8000')


def _sign(secret: str, body: bytes) -> str:
    import hashlib
    import hmac
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def _agent_get_or_create_channel(self, user):
        """Get-or-create the 1:1 DM between `user` and the AI agent bot
        partner — wraps core channel_get(), the same method Discuss itself
        uses for any "OdooBot"-style chat (verified against the actual
        Odoo 18 image; some docs describe a differently-named
        _get_or_create_chat, which is the Odoo 19 name).
        """
        bot = self.env.ref('saas_ai_agent.partner_agent_bot')
        return self.with_user(user).channel_get(partners_to=[bot.id], pin=True)

    def _is_agent_channel(self):
        self.ensure_one()
        bot = self.env.ref('saas_ai_agent.partner_agent_bot', raise_if_not_found=False)
        if not bot:
            return False
        return self.channel_type == 'chat' and bot.id in self.channel_member_ids.partner_id.ids

    def _agent_has_session(self):
        """Whether this channel has ever been dispatched to the agent
        before — used to fire the one-time welcome message on first open
        (see res_users.action_open_ai_assistant_chat), and nothing else:
        a session existing doesn't imply the tenant is configured/within
        budget, just that this isn't the very first interaction."""
        self.ensure_one()
        return bool(self.env['saas_ai_agent.session'].sudo().search_count([('channel_id', '=', self.id)]))

    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        self._maybe_notify_agent(message, kwargs)
        return message

    def _maybe_notify_agent(self, message, kwargs):
        self.ensure_one()
        bot = self.env.ref('saas_ai_agent.partner_agent_bot', raise_if_not_found=False)
        if not bot or not self._is_agent_channel():
            return
        # Never re-trigger on the bot's own reply (posted by the
        # /ai_agent/reply controller) — avoids an infinite loop.
        if kwargs.get('author_id') == bot.id:
            return
        user = self.env.user
        if not user or user._is_public() or not user.id:
            return
        body = html2plaintext(message.body or '').strip()
        if not body:
            return
        self._dispatch_to_agent(user, message=body)

    def _agent_trigger_welcome(self, user):
        """Post the AEI Assistant's self-introduction into the DM, once.

        Posts a LOCAL, inline message from the bot partner — exactly how
        OdooBot does it (mail_bot._init_odoobot: channel.sudo().message_post
        with author_id=bot, silent=True). This is deliberately NOT routed
        through the agent pod: the earlier design dispatched the welcome over
        HTTP to the agent, which silently produced an empty channel whenever
        the pod/secret/LLM wasn't ready — the opposite of "announce itself".
        A static local greeting always appears; the dynamic agent
        conversation begins as soon as the user actually replies (that reply
        goes through _maybe_notify_agent → _dispatch_to_agent as normal).
        """
        self.ensure_one()
        bot = self.env.ref('saas_ai_agent.partner_agent_bot')
        body = Markup(
            "¡Hola! Soy <b>AEI Assistant</b>, tu asistente de IA integrado en Odoo."
            "<br/><br/>"
            "Puedo ayudarte a configurar y operar tu instancia — siempre dentro "
            "de tus permisos. Escríbeme por aquí y pregúntame lo que necesites."
            "<br/><br/>"
            "Para desbloquear todas mis capacidades, configura tu propia API key "
            "en <b>Ajustes → AEI Assistant</b>."
        )
        self.sudo().with_context(mail_post_autofollow=False).message_post(
            body=body,
            author_id=bot.id,
            message_type='comment',
            silent=True,
            subtype_xmlid='mail.mt_comment',
        )

    def _dispatch_to_agent(self, user, message, welcome=False):
        self.ensure_one()
        bot = self.env.ref('saas_ai_agent.partner_agent_bot')

        if not AGENT_WEBHOOK_SECRET:
            logger.warning(
                "saas_ai_agent: AGENT_WEBHOOK_SECRET not set — skipping agent "
                "notification for channel %s.", self.id,
            )
            return

        llm_config = self.env['res.config.settings'].sudo()._aei_assistant_resolve_llm_config()
        if not llm_config['configured'] and not llm_config.get('trial_available'):
            # Either never configured, or the trial budget on AEI's own
            # key ran out — either way there's no key to run this turn
            # with. Skip the agent pod entirely and say so directly;
            # distinguish the two cases so "never tried" doesn't sound
            # like "you burned through your trial".
            if llm_config.get('trial'):
                text = (
                    "Se acabó el crédito de prueba — para seguir usándome, "
                    "configura tu propia API key en Ajustes > AEI Assistant."
                )
            else:
                text = (
                    "Todavía no configuraste tu API key de IA — anda a "
                    "Ajustes > AEI Assistant para activarme."
                )
            self.with_context(mail_post_autofollow=False).message_post(
                body=text, author_id=bot.id,
                message_type='comment', subtype_xmlid='mail.mt_comment',
            )
            return

        raw_key = self.env['saas_ai_agent.session']._issue_key(self, user)

        # Fires after the transaction commits, so the agent's own MCP reads
        # can already see any user message; never blocks or aborts the
        # user's own request if the agent pod is unreachable.
        channel_id = self.id
        payload = {
            "channel_id": channel_id,
            "message": message,
            "user_id": user.id,
            "user_login": user.login,
            "mcp_key": raw_key,
            "welcome": welcome,
        }
        self.env.cr.postcommit.add(lambda: _post_hook(channel_id, payload))


def _post_hook(channel_id, payload):
    raw = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Agent-Signature": _sign(AGENT_WEBHOOK_SECRET, raw),
    }
    try:
        resp = requests.post(f"{AGENT_URL}/hook", data=raw, headers=headers, timeout=5)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error(
            "saas_ai_agent: failed to notify agent for channel %s: %s",
            channel_id, exc,
        )
