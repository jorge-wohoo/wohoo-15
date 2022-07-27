from odoo import fields, models


class AnnulateWizard(models.TransientModel):
    _name = "annulate.wizard"

    motivo_anulacion = fields.Text()

    def button_annulate(self):
        # OVERRIDE
        sale = self.env["pos.order"].browse(self.env.context["active_id"])
        res = sale.button_annulate()
        sale.annulment_reason = self.motivo_anulacion
        return res
