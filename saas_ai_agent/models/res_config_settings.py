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


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    aei_assistant_provider = fields.Selection(
        selection=[
            ('anthropic', "Anthropic (Claude)"),
            ('deepseek', "DeepSeek"),
            ('moonshot', "Moonshot / Kimi"),
            ('custom', "Custom / self-hosted (Ollama, ...)"),
        ],
        string="AI Provider",
        config_parameter='saas_ai_agent.provider',
        default='anthropic',
        help="BYOK: aei_assistant only runs against your own API key — AEI "
             "never sees or pays for your LLM usage.",
    )
    aei_assistant_api_key = fields.Char(
        string="API Key",
        config_parameter='saas_ai_agent.api_key',
        help="Your own API key for the selected provider. The assistant "
             "stays disabled until this is set.",
    )
    aei_assistant_base_url = fields.Char(
        string="Custom Endpoint URL",
        config_parameter='saas_ai_agent.base_url',
        help="Required only for 'Custom / self-hosted' — e.g. "
             "http://your-ollama-host:11434 (must expose an "
             "Anthropic-compatible /v1/messages endpoint).",
    )
    aei_assistant_model = fields.Char(
        string="Model",
        config_parameter='saas_ai_agent.model',
        help="Leave empty to use the provider's default model.",
    )

    @api.onchange('aei_assistant_provider')
    def _onchange_aei_assistant_provider(self):
        if self.aei_assistant_provider != 'custom':
            self.aei_assistant_base_url = False

    def _aei_assistant_resolve_llm_config(self):
        """Server-side resolution used by the /ai_agent/llm_config
        controller — never called from the client, so the api_key value
        only ever leaves Odoo over the internal, NetworkPolicy-fenced hop
        to this tenant's own agent pod."""
        get_param = self.env['ir.config_parameter'].sudo().get_param
        provider = get_param('saas_ai_agent.provider', 'anthropic')
        api_key = get_param('saas_ai_agent.api_key')
        model = get_param('saas_ai_agent.model') or PROVIDER_DEFAULT_MODELS.get(provider, PROVIDER_DEFAULT_MODELS['anthropic'])
        if provider == 'custom':
            base_url = get_param('saas_ai_agent.base_url') or None
        else:
            base_url = PROVIDER_BASE_URLS.get(provider)
        return {
            'configured': bool(api_key),
            'provider': provider,
            'api_key': api_key or None,
            'base_url': base_url,
            'model': model,
        }
