from odoo import fields, models, tools, api, _
from odoo.exceptions import UserError
import logging


import psycopg2
_logger = logging.getLogger(__name__)

class PosOrder(models.Model):
    _inherit = "pos.order"

    journal_id = fields.Many2one(
        comodel_name="account.journal",
    )

    def get_account_move_infile_xml_uuid(self):
        return self.account_move.infile_xml_uuid

    def _prepare_invoice_vals(self):
        invoice_vals = super()._prepare_invoice_vals()
        invoice_vals["dte_type_id"] = (self.session_id.config_id.dte_type_id.id,)
        invoice_vals["journal_id"] = (
            self.journal_id.id or self.session_id.config_id.invoice_journal_id.id,
        )
        return invoice_vals

    def action_pos_order_invoice(self):
        moves = self.env['account.move']

        for order in self:
            # Force company for all SUPERUSER_ID action
            if order.account_move:
                moves += order.account_move
                continue

            if not order.partner_id:
                raise UserError(_('Please provide a partner for the sale.'))

            move_vals = order._prepare_invoice_vals()
            new_move = moves.sudo()\
                            .with_context(force_company=order.company_id.id)\
                            .create(move_vals)
            message = _("This invoice has been created from the point of sale session: <a href=# data-oe-model=pos.order data-oe-id=%d>%s</a>") % (order.id, order.name)
            new_move.message_post(body=message)
            order.write({'account_move': new_move.id, 'state': 'invoiced'})
            new_move.sudo().with_context(force_company=order.company_id.id).action_post()
            moves += new_move

        if not moves:
            return {}

        return {
            'name': _('Customer Invoice'),
            'view_mode': 'form',
            'view_id': self.env.ref('account.view_move_form').id,
            'res_model': 'account.move',
            'context': "{'type':'out_invoice'}",
            'type': 'ir.actions.act_window',
            'nodestroy': True,
            'target': 'current',
            'res_id': moves and moves.ids[0] or False,
        }