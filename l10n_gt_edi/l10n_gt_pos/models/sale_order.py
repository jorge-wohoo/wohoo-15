from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    journal_id = fields.Many2one(
        comodel_name="account.journal",
        domain="[('type', '=', 'sale')]",
    )
    journal_group = fields.Boolean(
        compute="_compute_user_in_journal_group",
        default=False,
    )

    @api.onchange("state")
    def _compute_user_in_journal_group(self):
        for record in self:
            record.journal_group = bool(
                self.env.user.has_group("l10n_gt_pos.group_journal_id_sale_order")
            )

    def _prepare_invoice(self):
        invoice_vals = super()._prepare_invoice()
        journal = (
            self.env["account.move"]  # pylint: disable=protected-access
            .with_context(default_move_type="out_invoice")
            ._get_default_journal()  # pylint: disable=protected-access
        )
        invoice_vals["journal_id"] = (self.journal_id.id or journal.id,)
        return invoice_vals
