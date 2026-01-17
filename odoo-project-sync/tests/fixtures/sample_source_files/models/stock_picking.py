# -*- coding: utf-8 -*-
"""Sample stock picking customizations for testing."""

from odoo import models, fields, api


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    x_lot_tracking_enabled = fields.Boolean(
        string="Lot Tracking Enabled",
        default=False,
        help="Enable lot tracking for this transfer",
    )
    
    x_total_weight = fields.Float(
        string="Total Weight",
        compute='_compute_total_weight',
        store=True,
    )

    @api.depends('move_ids.product_uom_qty', 'move_ids.product_id.weight')
    def _compute_total_weight(self):
        """Calculate total weight of the picking."""
        for picking in self:
            weight = 0.0
            for move in picking.move_ids:
                if move.product_id.weight:
                    weight += move.product_uom_qty * move.product_id.weight
            picking.x_total_weight = weight

    def action_toggle_lot_tracking(self):
        """Toggle lot tracking on/off."""
        for picking in self:
            picking.x_lot_tracking_enabled = not picking.x_lot_tracking_enabled
