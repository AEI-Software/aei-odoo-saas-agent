from odoo import models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _compute_im_status(self):
        # Same pattern mail/models/res_partner.py uses for base.partner_root
        # (OdooBot) — verified against the actual Odoo 18 image.
        super()._compute_im_status()
        bot_id = self.env['ir.model.data']._xmlid_to_res_id(
            'saas_ai_agent.partner_agent_bot', raise_if_not_found=False,
        )
        if not bot_id:
            return
        bot = self.browse(bot_id)
        if bot in self:
            bot.im_status = 'bot'
