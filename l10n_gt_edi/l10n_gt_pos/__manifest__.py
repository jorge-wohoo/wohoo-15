{
    "name": "L10N GT POS INVOCING",
    "version": "14.0.0.1.0",
    "author": "HomebrewSoft",
    "website": "https://homebrewsoft.dev",
    "license": "OPL-1",
    "depends": [
        "l10n_gt_edi",
        "l10n_gt_infile",
        "point_of_sale",
    ],
    "data": [
        "data/res_partner.xml",
        # secutity
        "security/ir.model.access.csv",
        # views
        "views/pos_order.xml",
        "views/pos_config.xml",
        "views/wizard_add_journals.xml",
        
    ],
    # "qweb": [
    #     "static/src/xml/pos_report.xml",
    # ],
    # "assets": {
    #     "point_of_sale.assets": [
    #         "l10n_gt_pos/static/src/js/models.js",
    #     ]
    # },
}
