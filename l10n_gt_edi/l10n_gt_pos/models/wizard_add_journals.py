from odoo import fields, models


class WizardAddJournal(models.TransientModel):
    _name = "wizard.add.journals"

    journal_id = fields.Many2one(
        comodel_name="account.journal",
        domain="[('type', '=', 'sale')]",
    )

    def action_pos_order_invoice(self):
        sales = self.env["pos.order"].browse(self.env.context["active_ids"])
        for record in sales:
            record.journal_id = self.journal_id.id
            if not record.partner_id:
                partner = self.env["res.partner"].search(
                    [
                        ("id", "=", "res_partner_cf_gt"),
                    ]
                )
                record.partner_id = partner
            res = record.action_pos_order_invoice()
            res["target"] = ""
