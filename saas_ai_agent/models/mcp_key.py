import secrets

from odoo import models


class MCPKey(models.Model):
    _inherit = 'muk_mcp.key'

    def _generate_agent_key(self, user, name):
        """Mint a key scoped to `user` — modeled directly on the core
        generate_playground_key (external_addons/muk_mcp/models/key.py):
        same secrets.token_urlsafe(32), same SHA-256-only storage. Only the
        plaintext is ever handed to the agent pod, over the in-namespace
        HTTP hop; Odoo itself never persists it.
        """
        rate_limit = int(self.env['ir.config_parameter'].sudo().get_param(
            'muk_mcp.rate_limit_requests', 60,
        ))
        raw_key = secrets.token_urlsafe(32)
        record = self.sudo().create({
            'name': name,
            'user_id': user.id,
            'key_hash': self._hash_key(raw_key),
            'key_prefix': raw_key[:8],
            'scope': 'write',
            'rate_limit': rate_limit,
        })
        return record, raw_key
