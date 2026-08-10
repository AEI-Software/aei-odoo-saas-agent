from odoo import api, fields, models

# Anthropic-compatible endpoints confirmed during the business-model research
# (Fable 5, 2026-08-07) — DeepSeek and Moonshot/Kimi both expose a
# /v1/messages-compatible endpoint, so the Claude Agent SDK's normal
# ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN env vars work unmodified.
PROVIDER_BASE_URLS = {
    'deepseek': 'https://api.deepseek.com/anthropic',
    'moonshot': 'https://api.moonshot.ai/anthropic',
}
PROVIDER_DEFAULT_MODELS = {
    'anthropic': 'claude-sonnet-5',
    'deepseek': 'deepseek-chat',
    'moonshot': 'kimi-k2-turbo-preview',
}

# Trial budget: how much of the platform's own default API key (never a
# BYOK key — that's the tenant's own, always unlimited) this tenant may
# spend before the assistant asks them to configure their own key. The key
# itself lives only in the agent pod's env (DEFAULT_LLM_* — see
# agent/main.py / manifests.py agent_secret_manifest) — Odoo only tracks
# spend and a boolean "still within budget?" signal, so the shared platform
# secret never has to be written into any tenant's database.
TRIAL_CAP_DEFAULT_USD = 1.0


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    aei_assistant_provider = fields.Selection(
        selection=[
            ('anthropic', "Anthropic (Claude)"),
            ('deepseek', "DeepSeek"),
            ('moonshot', "Moonshot / Kimi"),
            ('custom', "Personalizado / self-hosted (Ollama, ...)"),
        ],
        string="Proveedor de IA",
        config_parameter='saas_ai_agent.provider',
        default='anthropic',
        help="BYOK: AEI Assistant funciona solo con tu propia API key — AEI "
             "nunca ve ni paga tu uso del modelo de IA.",
    )
    aei_assistant_api_key = fields.Char(
        string="Clave API",
        config_parameter='saas_ai_agent.api_key',
        help="Tu propia API key del proveedor seleccionado. El asistente "
             "permanece desactivado hasta que la configures.",
    )
    aei_assistant_base_url = fields.Char(
        string="URL del endpoint personalizado",
        config_parameter='saas_ai_agent.base_url',
        help="Solo necesario para 'Personalizado / self-hosted' — p. ej. "
             "http://tu-host-ollama:11434 (debe exponer un endpoint "
             "/v1/messages compatible con Anthropic).",
    )
    aei_assistant_model = fields.Char(
        string="Modelo",
        config_parameter='saas_ai_agent.model',
        help="Déjalo vacío para usar el modelo por defecto del proveedor.",
    )
    aei_assistant_trial_used_usd = fields.Float(
        string="Gasto de prueba usado (USD)",
        compute='_compute_aei_assistant_trial_status',
        help="Costo aproximado consumido hasta ahora contra la clave de "
             "prueba de AEI (calculado desde el reporte de costo por turno "
             "del Claude Agent SDK). El reinicio es manual.",
    )
    aei_assistant_trial_cap_usd = fields.Float(
        string="Presupuesto de prueba (USD)",
        config_parameter='saas_ai_agent.trial_cap_usd',
        default=TRIAL_CAP_DEFAULT_USD,
        help="Cuánto de la clave por defecto de AEI puede usar este tenant "
             "antes de que el asistente le pida una API key propia. "
             "Dimensionado para que un cliente nuevo pruebe el asistente y "
             "reciba ayuda para configurar su clave sin que la exposición de "
             "la prueba de AEI sea ilimitada.",
    )

    @api.depends('aei_assistant_api_key')
    def _compute_aei_assistant_trial_status(self):
        used = float(self.env['ir.config_parameter'].sudo().get_param('saas_ai_agent.trial_cost_used', '0.0'))
        for rec in self:
            rec.aei_assistant_trial_used_usd = used

    @api.onchange('aei_assistant_provider')
    def _onchange_aei_assistant_provider(self):
        if self.aei_assistant_provider != 'custom':
            self.aei_assistant_base_url = False

    def _aei_assistant_resolve_llm_config(self):
        """Server-side resolution used by the /ai_agent/llm_config
        controller — never called from the client, so a BYOK api_key value
        only ever leaves Odoo over the internal, NetworkPolicy-fenced hop
        to this tenant's own agent pod. When the tenant hasn't set their
        own key, this does NOT hand back a key at all — it only signals
        whether the tenant is still within its trial budget; the agent pod
        supplies its own DEFAULT_LLM_* credentials from its env in that
        case (see agent/main.py), so the shared platform key never touches
        this (or any) tenant's database.
        """
        get_param = self.env['ir.config_parameter'].sudo().get_param
        provider = get_param('saas_ai_agent.provider', 'anthropic')
        api_key = get_param('saas_ai_agent.api_key')
        model = get_param('saas_ai_agent.model') or PROVIDER_DEFAULT_MODELS.get(provider, PROVIDER_DEFAULT_MODELS['anthropic'])

        if api_key:
            base_url = get_param('saas_ai_agent.base_url') or None if provider == 'custom' else PROVIDER_BASE_URLS.get(provider)
            return {
                'configured': True, 'trial': False,
                'provider': provider, 'api_key': api_key, 'base_url': base_url, 'model': model,
            }

        trial_used = float(get_param('saas_ai_agent.trial_cost_used', '0.0'))
        trial_cap = float(get_param('saas_ai_agent.trial_cap_usd', str(TRIAL_CAP_DEFAULT_USD)))
        return {
            'configured': False, 'trial': True,
            'trial_available': trial_used < trial_cap,
            'trial_used_usd': trial_used, 'trial_cap_usd': trial_cap,
            'provider': None, 'api_key': None, 'base_url': None, 'model': None,
        }

    def _aei_assistant_record_trial_spend(self, cost_usd):
        """Called by the /ai_agent/reply controller after a turn that ran
        on the trial key, to keep the budget check in
        _aei_assistant_resolve_llm_config accurate for the next message."""
        ICP = self.env['ir.config_parameter'].sudo()
        used = float(ICP.get_param('saas_ai_agent.trial_cost_used', '0.0'))
        ICP.set_param('saas_ai_agent.trial_cost_used', str(used + max(0.0, cost_usd)))
