# -*- coding: utf-8 -*-
"""Sample sale order customizations for testing complexity analysis."""

from odoo import models, fields, api
from odoo.exceptions import UserError


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    x_secondary_uom = fields.Float(
        string="Secondary UoM Quantity",
        digits='Product Unit of Measure',
        help="Quantity in secondary unit of measure (e.g., weight)",
    )
    
    x_weight_calculated = fields.Float(
        string="Calculated Weight",
        compute='_compute_weight',
        store=True,
        digits='Stock Weight',
    )
    
    x_unit_weight = fields.Float(
        string="Unit Weight",
        related='product_id.weight',
    )

    @api.depends('product_uom_qty', 'x_unit_weight')
    def _compute_weight(self):
        """Calculate total weight based on quantity and unit weight."""
        for line in self:
            if line.x_unit_weight:
                line.x_weight_calculated = line.product_uom_qty * line.x_unit_weight
            else:
                line.x_weight_calculated = 0.0

    def action_update_secondary_uom(self):
        """Update secondary UoM from product default."""
        for line in self:
            if line.product_id.x_secondary_uom_id:
                factor = line.product_id.x_uom_conversion_factor or 1.0
                line.x_secondary_uom = line.product_uom_qty * factor


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    x_total_weight = fields.Float(
        string="Total Weight",
        compute='_compute_total_weight',
        store=True,
    )
    
    x_weight_uom_id = fields.Many2one(
        'uom.uom',
        string="Weight UoM",
        default=lambda self: self.env.ref('uom.product_uom_kgm', raise_if_not_found=False),
    )

    @api.depends('order_line.x_weight_calculated')
    def _compute_total_weight(self):
        """Sum weights from all order lines."""
        for order in self:
            order.x_total_weight = sum(order.order_line.mapped('x_weight_calculated'))

    def action_calculate_weights(self):
        """Recalculate all weights for the order.
        
        This is a more complex action that:
        1. Validates product weights exist
        2. Applies conversion factors
        3. Updates secondary UoM values
        4. Logs the calculation
        """
        for order in self:
            missing_weights = order.order_line.filtered(
                lambda l: not l.product_id.weight and l.product_id.type == 'product'
            )
            
            if missing_weights:
                product_names = missing_weights.mapped('product_id.name')
                raise UserError(
                    f"Missing weights for products: {', '.join(product_names)}"
                )
            
            # Update all line weights
            for line in order.order_line:
                line._compute_weight()
                line.action_update_secondary_uom()
            
            # Search for related pickings
            pickings = self.env['stock.picking'].search([
                ('sale_id', '=', order.id),
                ('state', 'not in', ['done', 'cancel']),
            ])
            
            # Update picking weights
            for picking in pickings:
                picking.x_total_weight = order.x_total_weight
            
            # Log the action
            order.message_post(
                body=f"Weights recalculated. Total: {order.x_total_weight} kg",
                message_type='notification',
            )
        
        return True

    def _prepare_invoice(self):
        """Override to include weight information on invoice."""
        values = super()._prepare_invoice()
        values['x_total_weight'] = self.x_total_weight
        return values

    @api.model
    def _get_weight_report_data(self, orders):
        """Prepare weight data for reporting.
        
        Returns aggregated weight data by product category.
        """
        result = {}
        
        for order in orders:
            for line in order.order_line:
                category = line.product_id.categ_id.name or 'Uncategorized'
                if category not in result:
                    result[category] = {
                        'total_weight': 0.0,
                        'line_count': 0,
                        'products': set(),
                    }
                result[category]['total_weight'] += line.x_weight_calculated
                result[category]['line_count'] += 1
                result[category]['products'].add(line.product_id.id)
        
        return result
