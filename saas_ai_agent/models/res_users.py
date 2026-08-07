from odoo import models


class ResUsers(models.Model):
    _inherit = 'res.users'

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
        """
        channel = self.env['discuss.channel']._agent_get_or_create_channel(self.env.user)
        return {
            'type': 'ir.actions.act_url',
            'url': f'/odoo/discuss?active_id=discuss.channel_{channel.id}',
            'target': 'self',
        }
