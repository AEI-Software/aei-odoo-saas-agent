"""Layer-1 (authoritative) guardrails for requirements #4 and #5.

Gated on self.env.context.get('mcp_name'), which muk_mcp's auth hook
(external_addons/muk_mcp/models/ir_http.py::_auth_method_mcp) stamps on
the env of every MCP request and nothing else does — verified against the
real addon during the Phase 0 spike. Normal admin UI, XML-RPC, and cron
paths carry no mcp_name and are completely unaffected: these overrides
only ever fire for calls made through the MCP tool interface, i.e. by the
AI agent (or anyone else's MCP key), never through the ordinary UI a human
admin uses to manage users or apps.
"""
from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.http import request


def _is_mcp_request(env):
    """Whether the current call came in through the MCP interface.

    Primary signal: the ``mcp_name`` context stamp. Since muk_mcp 3.0.1
    that stamp is conditional on the ``muk_mcp.annotate_messages`` config
    parameter (default True), so ALSO check ``request._mcp_key``, which
    _auth_method_mcp sets unconditionally — a tenant disabling message
    annotation must not silently disable the guardrails.
    """
    if env.context.get('mcp_name'):
        return True
    return bool(request and getattr(request, '_mcp_key', None))


class ResUsersGuardrail(models.Model):
    _inherit = 'res.users'

    def _check_not_mcp_agent(self):
        if _is_mcp_request(self.env):
            raise UserError(_(
                "I cannot create or modify users: every user has a cost for "
                "the customer. Ask an administrator to do it from the normal "
                "Odoo interface."
            ))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_not_mcp_agent()
        return super().create(vals_list)

    def write(self, vals):
        if set(vals) & {'login', 'group_ids', 'groups_id', 'active'}:
            self._check_not_mcp_agent()
        return super().write(vals)


class IrModuleModuleGuardrail(models.Model):
    _inherit = 'ir.module.module'

    def _check_not_mcp_agent(self):
        if _is_mcp_request(self.env):
            raise UserError(_(
                "I cannot install, upgrade or uninstall apps: this instance "
                "only includes the apps of your current plan. Request a plan "
                "upgrade or contact support."
            ))

    def button_install(self):
        self._check_not_mcp_agent()
        return super().button_install()

    def button_immediate_install(self):
        self._check_not_mcp_agent()
        return super().button_immediate_install()

    def button_upgrade(self):
        self._check_not_mcp_agent()
        return super().button_upgrade()

    def button_immediate_upgrade(self):
        self._check_not_mcp_agent()
        return super().button_immediate_upgrade()

    def button_uninstall(self):
        self._check_not_mcp_agent()
        return super().button_uninstall()

    def button_immediate_uninstall(self):
        self._check_not_mcp_agent()
        return super().button_immediate_uninstall()
