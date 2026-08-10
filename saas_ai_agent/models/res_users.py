import logging

from odoo import fields, models

logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    aei_assistant_welcomed = fields.Boolean(
        string="AEI Assistant Welcomed",
        default=False,
        copy=False,
        help="Latch: True once the AEI Assistant has proactively introduced "
             "itself to this user in Discuss. Mirrors mail_bot's odoobot_state "
             "so the welcome fires exactly once per user.",
    )

    def _on_webclient_bootstrap(self):
        """Announce the AEI Assistant proactively on first webclient load —
        the SAME hook OdooBot uses (mail_bot.res_users._on_webclient_bootstrap,
        called from web/controllers/home.py on every webclient load). This is
        what makes the assistant's DM channel appear and greet the user without
        them having to open any menu — matching OdooBot's own unprompted
        welcome. Latched per-user via aei_assistant_welcomed so it fires once.

        Wrapped in try/except so a hiccup here can NEVER break the webclient
        from loading — a broken welcome must not lock a tenant out of Odoo.
        """
        super()._on_webclient_bootstrap()
        user = self.env.user
        if not user._is_internal() or user.aei_assistant_welcomed:
            return
        try:
            channel = self.env['discuss.channel']._agent_get_or_create_channel(user)
            channel._agent_trigger_welcome(user)
            user.sudo().aei_assistant_welcomed = True
        except Exception:
            logger.exception(
                "saas_ai_agent: proactive AEI Assistant welcome failed for %s",
                user.login,
            )

    def action_open_ai_assistant_chat(self):
        """Entry point for the top-level "AEI Assistant" menu.

        Odoo's own DM picker (res.partner.im_search) only searches
        res.users, never plain res.partner records — the bot partner has
        no login, so it can never surface there the way a human contact
        would (verified against the real search domain in mail/models/
        res_partner.py). This menu is the discoverable substitute: it
        get-or-creates the caller's own DM with the bot and jumps straight
        into Discuss on that channel, using the same URL shape Odoo's own
        Discuss app generates for a channel deep link (verified against
        mail's own test suite: /odoo/discuss?active_id=discuss.channel_<id>).

        Shares the aei_assistant_welcomed latch with _on_webclient_bootstrap
        so the user never gets a double greeting whichever path fires first.
        """
        channel = self.env['discuss.channel']._agent_get_or_create_channel(self.env.user)
        if not self.env.user.aei_assistant_welcomed:
            channel._agent_trigger_welcome(self.env.user)
            self.env.user.sudo().aei_assistant_welcomed = True
        return {
            'type': 'ir.actions.act_url',
            'url': f'/odoo/discuss?active_id=discuss.channel_{channel.id}',
            'target': 'self',
        }
