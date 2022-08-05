import base64
import logging
from typing import List, Set

from gt_sat_api import DTE, AnulacionDTE, Complemento, Direccion, Emisor, Frase, Item, Receptor
from gt_sat_api.parsers import dte_to_xml, dte_to_xml_annulled
from pytz import timezone
from decimal import *

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)
DIGITS = 2


class AccountMove(models.Model):
    _inherit = "account.move"

    frases_ids = fields.Many2many(
        comodel_name="gt.frase",
    )
    dte_type_id = fields.Many2one(
        comodel_name="gt.dte.type",
        readonly=True,
        states={"draft": [("readonly", False)]},
        default=lambda self: self.env.company.default_dte_type_id,
    )
    allowed_type_ids = fields.Many2many(
        comodel_name="gt.dte.type",
        compute="_compute_allowed_type_ids",
    )
    emision_datetime = fields.Datetime(
        copy=False,
    )
    annulated_datetime = fields.Datetime(
        copy=False,
        readonly=True,
    )
    annulment_reason = fields.Text(
        string="Razón de anulación",
        copy=False,
    )
    regime = fields.Boolean(
        string="Is Old Regime",
    )
    origin_uuid = fields.Char()
    origin_date = fields.Date()
    use_in_sat = fields.Boolean(
        related="journal_id.use_in_sat",
    )
    subscription_number = fields.Integer(
        string="Numero de Abono",
    )
    payment_amount = fields.Integer(
        compute="_compute_payment_amount",
        string="Monto Abono",
    )
    fcam_invoice = fields.Boolean(
        compute="_compute_fcam_invoice",
    )
    accreditation_date = fields.Datetime(
        copy=False,
        readonly=True,
    )
    import_invoice = fields.Boolean(
        string="Factura de exportacion"
    )
    sale_order_id = fields.Many2one(
        comodel_name='sale.order',
    )
    transport = fields.Char(
        string='Transporte',
    )
    modelo = fields.Char()


    @api.onchange("dte_type_id")
    def _compute_fcam_invoice(self):
        for record in self:
            if record.dte_type_id.code == "FCAM":
                record.fcam_invoice = True
            else:
                record.fcam_invoice = False

    @api.depends("subscription_number")
    def _compute_payment_amount(self):
        for record in self:
            record.payment_amount = 0
            if record.subscription_number:
                record.payment_amount = record.amount_total / record.subscription_number

    def partner_dte_requiered_fields(self):
        return {
            "city",
            "country_id",
            "email",
            "name",
            "state_id",
            "street",
            "vat",
            "zip",
        }

    @api.depends("move_type")
    def _compute_allowed_type_ids(self):
        """Method to generate a list of valid dte_type ids and use it to compare in view domain"""
        for move in self:
            if move.move_type in ("out_invoice", "in_invoice"):
                move.allowed_type_ids = self.env["gt.dte.type"].search(
                    [("general_move_type", "=", "invoice")]
                )
            elif move.move_type in ("out_receipt", "in_receipt"):
                move.allowed_type_ids = self.env["gt.dte.type"].search(
                    [("general_move_type", "=", "receipt")]
                )
            else:
                move.allowed_type_ids = self.env["gt.dte.type"].search(
                    [("general_move_type", "=", "refund")]
                )

    def generate_dte_emisor(self) -> Emisor:
        """Generate a emisor object to be added in a dte object generation
        Returns:
            Emisor -- The emisor object
        """
        self.ensure_one()
        return Emisor(
            afiliacion_iva=self.company_id.iva_affiliation_id.code,
            codigo_establecimiento=self.company_id.codigo_establecimiento,
            correo_emisor=self.company_id.email,
            nit_emisor=self.company_id.vat,
            nombre_comercial=self.company_id.name,
            nombre_emisor=self.company_id.company_registry,
            direccion=Direccion(
                direccion=self.company_id.street,
                codigo_postal=self.company_id.zip,
                municipio=self.company_id.city,
                departamento=self.company_id.state_id.name,
                pais=self.company_id.country_id.code,
            ),
        )

    def generate_dte_receptor(self) -> Receptor:
        """Generate a receptor object to be added in a dte object generation
        Returns:
            Receptor -- The receptor object
        """
        self.ensure_one()
        return Receptor(
            correo_receptor=self.partner_id.email,
            id_receptor=self.partner_id.vat,
            nombre_receptor=self.partner_id.name,
            direccion=Direccion(
                direccion=self.partner_id.street,
                codigo_postal=self.partner_id.zip,
                municipio=self.partner_id.city,
                departamento=self.partner_id.state_id.name,
                pais=self.partner_id.country_id.code,
            ),
        )

    def generate_dte_items(self) -> List[Item]:
        """Generate list of item objects added in a dte object generation
        Returns:
            list[Item] -- List of items (invoice lines)
        """
        self.ensure_one()
        return [
            Item(
                bien_o_servicio="S" if line.product_id.type == "service" else "B",
                numero_linea=index + 1,
                cantidad=line.quantity,
                unidad_medida=line.product_uom_id.name[:3].upper(),
                descripcion=line.modelo,
                ImpuestoGravable=line.impuesto_gravable,
                precio_unitario=float(Decimal(line.price_unit).quantize(Decimal("0.01"), rounding = "ROUND_HALF_UP")),
                MontoGravable=line.monto_gravable,
                MontoImpuesto=line.impuesto,
                descuento_porcentual=line.discount,
                impuestos_rate={
                    tax.code_name: (
                        tax.codigo_unidad_gravable,
                        100 / len(line.tax_ids),
                    )
                    for tax in line.tax_ids
                },
            )
            for index, line in enumerate(self.invoice_line_ids)
        ]

    def generate_dte_complements(self) -> List[Complemento]:
        """Generate a list of Complement objects to be added in a dte object generation
        Returns:
            list[Complement] -- List of complements
        """
        self.ensure_one()
        complement_list = []
        if self.move_type in ("out_refund", "in_refund"):
            if not self.origin_uuid:
                raise ValidationError(_("There is no origin UUID"))
            if not self.origin_date:
                raise ValidationError(_("There is no origin date"))
            complemento = Complemento(
                nombre="Notas",
                uri="http://www.sat.gob.gt/fel/notas.xsd",
                regimen=self.regime,
                no_origen=self.origin_uuid,
                fecha_origen=self.origin_date,
                descripcion=self.ref,
                type="nota",
            )
            complement_list.append(complemento)
        return complement_list

    def _pre_generate_dte(self):
        """Ensure all data is correct before try to generate a dte object"""
        self.ensure_one()
        if not self.env.user.tz:
            raise ValidationError(_("You must set your timezone firts"))

    def generate_dte(self) -> DTE:
        """Create a DTE object
        Returns:
            DTE -- A DTE object
        """
        self._pre_generate_dte()
        self._check_required_fields()

        emisor = self.generate_dte_emisor()
        receptor = self.generate_dte_receptor()
        items = self.generate_dte_items()
        self.emision_datetime = fields.Datetime.now()
        self.accreditation_date = fields.Datetime.now()
        return DTE(
            clase_documento="dte",
            ImportInvoice=self.import_invoice,
            codigo_moneda=self.currency_id.name,
            fecha_hora_emision=self.emision_datetime.astimezone(timezone(self.env.user.tz)),
            tipo=self.dte_type_id.code,
            NumeroAbono= self.subscription_number,
            FechaVencimiento= self.invoice_date_due,
            MontoAbono= self.payment_amount,
            CondicionesPago=self.invoice_payment_term_id.name,
            Vencimiento=self.invoice_date_due,
            NoOCCliente=self.sale_order_id.name,
            NombreConsignatarioODestinatario=self.partner_id.name,
            DireccionConsignatarioODestinatario=self.partner_id.street,
            CodigoConsignatarioODestinatario=0,
            NombreComprador=self.partner_id.name,
            DireccionComprador=self.partner_id.street,
            CodigoComprador=0,
            OtraReferencia="N/A",
            INCOTERM=self.invoice_incoterm_id.code,
            NombreExportador=self.company_id.name,
            CodigoExportador=self.company_id.export_code,
            CodigoCliente=self.partner_id.ref,
            Transporte=self.transport,
            NoPedido=self.sale_order_id.name,
            FechaPedido=self.sale_order_id.date_order,
            modelo=self.modelo,
            Agente=self.invoice_user_id.name,
            emisor=emisor,
            receptor=receptor,
            frases=[
                Frase(codigo_escenario=frase.code, tipo_frase=frase.type)
                for frase in self.dte_type_id.frases_ids
            ],
            items=items,
            complementos=self.generate_dte_complements(),
        )

    def generate_dte_annulled(self):
        """Create a AnulacionDTE object
        Returns:
            AnulacionDTE -- A AnulacionDTE object
        """
        self._pre_generate_dte()
        self._check_required_fields(annulled=True)

        emisor = self.generate_dte_emisor()
        receptor = self.generate_dte_receptor()
        annulated_datetime = fields.Datetime.now()
        self.annulated_datetime = annulated_datetime
        return AnulacionDTE(
            uuid=self.infile_xml_uuid,
            fecha_hora_emision=self.emision_datetime.astimezone(timezone(self.env.user.tz)),
            fecha_hora_anulacion=annulated_datetime.astimezone(timezone(self.env.user.tz)),
            motivo_anulacion=self.annulment_reason,
            emisor=emisor,
            receptor=receptor,
        )

    def get_last_xml_attachment(self, name):
        """Search for the invoice xml file in attachments
        Returns:
            record -- ir.attachment record or False
        """
        self.ensure_one()
        return self.env["ir.attachment"].search(
            [
                ("res_model", "=", self._name),
                ("res_id", "=", self.id),
                ("name", "=", name),
            ],
            order="id desc",
            limit=1,
        )

    def _generate_generate_attachment_from_xml_string(self, xml_string, file_name):
        """Generate an attachment from xml string
        Returns:
            record -- ir.attachment record
        """
        data_attach = {
            "name": file_name,
            "datas": base64.b64encode(xml_string.encode()),
            "store_fname": file_name,
            "description": _(f"XML File to send to SAT - Invoice: '{self.name}'"),
            "res_model": "account.move",
            "res_id": self.id,
            "type": "binary",
        }
        return self.env["ir.attachment"].create(data_attach)

    def get_fname_xml(self, annulled=False):
        """Get the file name for the xml file
        Returns:
            str -- File name
        """
        self.ensure_one()
        posfix = "(Annulled)" if annulled else ""
        return f"{self.dte_type_id.code}_{self.name}{posfix}.xml"

    def get_xml_string(self, annulled=False):
        """Method that returns the invoice xml string
        Raises:
            ValidationError: If there is a problem with the attachment
        Returns:
            str -- String of xml attachment
        """
        self.ensure_one()
        fname = self.get_fname_xml(annulled)
        attachment = self.get_last_xml_attachment(fname)
        if not attachment:
            raise ValidationError(_("There is no XML attached to the invoice %s") % self.name)
        return base64.b64decode(attachment.datas)

    def generate_attachment_from_xml_string(self, xml_string, file_name):
        """Update or create a new xml file as attachment
        Arguments:
            xml {str} -- String of xml invoice
            info {dict} -- Dictionary containing information to generate attachment
        """
        attachment = self.get_last_xml_attachment(file_name)
        if not attachment:
            return self._generate_generate_attachment_from_xml_string(xml_string, file_name)
        attachment.datas = base64.b64encode(xml_string.encode())
        attachment.mimetype = "application/xml"
        return attachment

    def generate_dte_xml(self, dte):
        """Generate an xml file per invoice and save them on attachments"""
        annulled = isinstance(dte, AnulacionDTE)
        xml_str = dte_to_xml_annulled(dte) if annulled else dte_to_xml(dte)
        if not annulled:
            tag_adendda = ("<dte:Adenda>" '\n'
                        "<Agente>%(Agente)s</Agente>" '\n'
                        "<Vencimiento>%(Vencimiento)s</Vencimiento>" '\n'
                        "<NumeroInterno>%(NumeroInterno)s</NumeroInterno>" '\n'
                        "</dte:Adenda>"
            ) % {"Agente": self.invoice_user_id.name, "Vencimiento": self.invoice_date_due, "NumeroInterno": self.name}
            index_final = xml_str.find("</dte:DTE>")
            dte_end = xml_str.find("</dte:SAT>")
            if self.invoice_payment_term_id:
                index_adendda_tag = tag_adendda.find("</dte:Adenda>")
                tag_adendda_payment_term = ("<CondicionesPago>%(CondicionesPago)s</CondicionesPago>" '\n') % {"CondicionesPago": self.invoice_payment_term_id.name}
                tag_adendda = tag_adendda[:index_adendda_tag] + tag_adendda_payment_term + tag_adendda[index_adendda_tag:]
            if self.partner_id.ref:
                index_adendda_tag = tag_adendda.find("</dte:Adenda>")
                tag_adendda_codigo_cliente = ("<CodigoCliente>%(CodigoCliente)s</CodigoCliente>" '\n') % {"CodigoCliente": self.partner_id.ref}
                tag_adendda = tag_adendda[:index_adendda_tag] + tag_adendda_codigo_cliente + tag_adendda[index_adendda_tag:]
            if self.sale_order_id:
                index_adendda_tag = tag_adendda.find("</dte:Adenda>")
                tag_adendda_sale_order = ("<NoOCCliente>%(NoOcCliente)s</NoOCCliente>" '\n'
                                        "<FechaPedido>%(FechaPedido)s</FechaPedido>" '\n'
                                        "<NoPedido>%(NoPedido)s</NoPedido>" '\n'
                ) % {"NoOcCliente": self.sale_order_id.name, "FechaPedido": self.sale_order_id.date_order, "NoPedido": self.sale_order_id.name}
                tag_adendda = tag_adendda[:index_adendda_tag] + tag_adendda_sale_order + tag_adendda[index_adendda_tag:]
            if self.transport:
                index_adendda_tag = tag_adendda.find("</dte:Adenda>")
                tag_adendda_transporte = ("<Transporte>%(Transporte)s</Transporte>" '\n') % {"Transporte": self.transport}
                tag_adendda = tag_adendda[:index_adendda_tag] + tag_adendda_transporte + tag_adendda[index_adendda_tag:]
            
            if self.tax_totals_json:
                if "TotalMontoImpuesto" in xml_str:
                    index_total_monto_impuesto = xml_str.index("TotalMontoImpuesto")
                    index2 = xml_str.index("</dte:TotalImpuestos>")
                    total_monto_impuesto = ("%(ImpuestoTotal)s")  % {"ImpuestoTotal": Decimal(self.amount_tax_signed).quantize(Decimal("0.01"), rounding = "ROUND_HALF_UP")}
                    if self.move_type in ["in_refund", "out_refund"]:
                        total_monto_impuesto = ("%(ImpuestoTotal)s")  % {"ImpuestoTotal": -(Decimal(self.amount_tax_signed).quantize(Decimal("0.01"), rounding = "ROUND_HALF_UP"))}
                    if self.currency_id.name == "USD":
                        total_monto_impuesto = ("%(ImpuestoTotal)s")  % {"ImpuestoTotal": (Decimal(self.amount_tax).quantize(Decimal("0.01"), rounding = "ROUND_HALF_UP"))}
                    
                    xml_str = xml_str[:index_total_monto_impuesto+20] + str(total_monto_impuesto) + xml_str[index2-14:]
            xml_str = xml_str[:index_final + 9] + tag_adendda + xml_str[dte_end - 4:]
            fname = self.get_fname_xml(annulled)
            self.generate_attachment_from_xml_string(xml_str, fname)
        else:
            fname = self.get_fname_xml(annulled)
            self.generate_attachment_from_xml_string(xml_str, fname)

    def send_xml_to_sat(self, annulled=False):
        """Function to send the XML string to SAT"""
        raise NotImplementedError(_("This function must be implemented by a third party module"))

    def post_send_xml_to_sat(self, response, annulled=False):
        """Function to send the XML string to SAT"""
        raise NotImplementedError(_("This function must be implemented by a third party module"))

    def _check_partner_required_fields(self, partner, field_names: Set[str] = None) -> None:
        """Check if the partner has all the required fields"""
        field_names = set(field_names or {})
        for field in self.partner_dte_requiered_fields() | field_names:
            if not getattr(partner, field):
                raise ValidationError(
                    _(
                        "The partner '%(partner_name)s' is missing the field '%(field_name)s'. "
                        "Please fill it before sending the invoice to SAT"
                    )
                    % {"partner_name": partner.name, "field_name": field}
                )

    def _check_required_fields(self, annulled=False):
        """Function to validate the required fields to generate and send the XML"""
        self.ensure_one()
        if annulled and not self.annulment_reason:
            raise ValidationError(
                _("You must provide a reason for the annulment of the invoice %(invoice_name)s")
                % {"invoice_name": self.name}
            )
        self._check_partner_required_fields(
            self.company_id,
            {
                "iva_affiliation_id",
                "codigo_establecimiento",
                "company_registry",
            },
        )
        self._check_partner_required_fields(self.partner_id)

    def action_post(self):
        """Post/Validate the documents"""
        res = super().action_post()
        self.action_generate_and_send_xml()

        return res

    def action_generate_and_send_xml(self, annulled=False):
        """Call the methods to generate a new XML file and try to send it to SAT"""
        for move in self:
            if not move.use_in_sat:
                continue
            if annulled and not move.posted_before:
                raise ValidationError(
                    _(
                        "You can not generate an XML file for an annulled "
                        "invoice that has not been posted before"
                    )
                )
            if move.infile_status == "error" and move.state == "cancel" and move.annulment_reason:
                annulled=True
            if not annulled and move.state != "posted":
                raise ValidationError(_("You can only generate XML for posted invoices"))
            dte = move.generate_dte_annulled() if annulled else move.generate_dte()
            move.generate_dte_xml(dte)
            response = move.send_xml_to_sat(annulled)
            move.post_send_xml_to_sat(response, annulled)

    def button_cancel(self):
        """Function to cancel the invoice"""
        self.button_draft()
        res = super().button_cancel()
        self.action_generate_and_send_xml(annulled=True)
        return res
