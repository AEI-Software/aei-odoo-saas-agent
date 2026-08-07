{
    'name': 'AEI SaaS AI Agent',
    'version': '18.0.1.0.0',
    'summary': 'Tenant AI agent reachable as a Discuss DM, scoped to the RBAC of the chatting user',
    'category': 'Technical',
    'author': 'AEI Software',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'muk_mcp', 'base_setup'],
    'data': [
        'security/ir.model.access.csv',
        'data/agent_partner.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
