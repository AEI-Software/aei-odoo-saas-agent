import json
import logging
import os

import requests

from markupsafe import Markup

from odoo import _, models
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
        partner — wraps core _get_or_create_chat(), the same method
        mail_bot._init_odoobot uses in Odoo 19 (channel_get was removed in
        19.0; it crashed the proactive welcome on every tenant until
        2026-08-12, SUB00264). Passing both partner ids mirrors mail_bot;
        with_user(user) makes the pin/last_interest apply to that user.
        """
        bot = self.env.ref('saas_ai_agent.partner_agent_bot')
        return self.with_user(user)._get_or_create_chat(
            [bot.id, user.partner_id.id], pin=True,
        )

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
        # Source strings are English; i18n/es.po carries the Spanish shown
        # to es_* tenants. Markup placeholders keep the tags out of the
        # translatable text (mail_bot's own pattern).
        body = Markup("%s<br/><br/>%s<br/><br/>%s") % (
            _("Hello! I am %s, your AI assistant built into Odoo.",
              Markup("<b>AEI Assistant</b>")),
            _("I can help you set up and operate your system — always within "
              "your own permissions. Write to me here and ask me anything."),
            _("To unlock all my capabilities, configure your own API key "
              "under %s.", Markup("<b>%s</b>") % _("Settings → AEI Assistant")),
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
                text = _(
                    "The trial credit has run out — to keep using me, "
                    "configure your own API key under Settings > AEI Assistant."
                )
            else:
                text = _(
                    "You have not configured your AI API key yet — go to "
                    "Settings > AEI Assistant to activate me."
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
