from odoo import fields, models


class AgentSession(models.Model):
    _name = 'saas_ai_agent.session'
    _description = 'AI agent conversation session (per Discuss channel)'

    channel_id = fields.Many2one('discuss.channel', required=True, index=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', required=True, index=True, ondelete='cascade')
    mcp_key_id = fields.Many2one('muk_mcp.key', ondelete='set null')
    last_activity = fields.Datetime(default=fields.Datetime.now)

    _sql_constraints = [
        ('channel_unique', 'unique(channel_id)', 'One agent session per Discuss channel.'),
    ]

    def _issue_key(self, channel, user):
        """Mint a fresh key for this turn and revoke the previous one.

        muk_mcp only ever stores a key's hash (see models/mcp_key.py), so
        there is no plaintext to reuse across separate /hook requests —
        each user message gets a brand-new, single-turn key instead. This
        also keeps the exposure window per leaked key as small as possible.

        Bookkeeping only — sudo() throughout: the acting user (whoever is
        chatting) has no reason to hold direct ACLs on this model, same as
        they have none on muk_mcp.key itself.
        """
        self = self.sudo()
        session = self.search([('channel_id', '=', channel.id)], limit=1)
        old_key = session.mcp_key_id if session else self.env['muk_mcp.key']

        record, raw_key = self.env['muk_mcp.key']._generate_agent_key(
            user, name=f"agent:{channel.id}",
        )

        if session:
            session.write({
                'mcp_key_id': record.id,
                'user_id': user.id,
                'last_activity': fields.Datetime.now(),
            })
        else:
            session = self.create({
                'channel_id': channel.id,
                'user_id': user.id,
                'mcp_key_id': record.id,
            })

        if old_key:
            old_key.sudo().write({'active': False})

        return raw_key
