from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AccountMove(models.Model):
    _inherit = "account.move"

    motivo_anulacion = fields.Text()

    def retry_annulation(self):
        return super(AccountMove, self).call_generate_and_send_xml_annulated()

    @api.onchange(
        "partner_id",
        "invoice_date",
        "invoice_payment_term_id",
        "journal_id",
        "dte_type_id",
        "invoice_line_ids",
        "ref",
        "invoice_user_id",
        "team_id",
    )
    def block_change_information_infile_done(self):
        for record in self:
            if record.infile_status == ["done", "annulled", "annulled_error"]:
                raise ValidationError(
                    "No se pueden modificar estos datos porque la factura ya fue timbrada"
                )

    def action_open_annulation_wizard(self):
        return {
            "name": _("Annulate Invoice"),
            "res_model": "annulate.wizard",
            "view_mode": "form",
            "context": {
                "active_model": "account.move",
                "active_ids": self.ids,
            },
            "target": "new",
            "type": "ir.actions.act_window",
        }
