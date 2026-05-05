# -*- coding: utf-8 -*-
"""Sample stock automation for testing complexity analysis."""

from odoo import models, fields, api
import logging
import requests

_logger = logging.getLogger(__name__)


class StockPickingAutomation(models.Model):
    _inherit = 'stock.picking'

    def automation_update_inventory(self):
        """Complex automation that updates inventory levels.
        
        This automation:
        1. Checks picking state
        2. Updates quant levels
        3. Sends notifications
        4. Calls external webhook
        """
        for picking in self:
            if picking.state != 'done':
                continue
            
            # Update quants
            for move in picking.move_ids:
                quants = self.env['stock.quant'].search([
                    ('product_id', '=', move.product_id.id),
                    ('location_id', '=', move.location_dest_id.id),
                ])
                
                for quant in quants:
                    if quant.quantity < 0:
                        _logger.warning(
                            f"Negative quant for {move.product_id.name}"
                        )
                
                # Check reorder rules
                orderpoints = self.env['stock.warehouse.orderpoint'].search([
                    ('product_id', '=', move.product_id.id),
                ])
                
                for op in orderpoints:
                    if op.product_min_qty > sum(quants.mapped('quantity')):
                        self._create_reorder_notification(op)
            
            # Send webhook notification
            if picking.company_id.x_webhook_url:
                try:
                    self._send_inventory_webhook(picking)
                except Exception as e:
                    _logger.error(f"Webhook failed: {e}")

    def _create_reorder_notification(self, orderpoint):
        """Create notification for low stock."""
        self.env['mail.activity'].create({
            'res_model_id': self.env.ref('stock.model_stock_warehouse_orderpoint').id,
            'res_id': orderpoint.id,
            'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
            'summary': f'Low stock: {orderpoint.product_id.name}',
            'user_id': orderpoint.user_id.id or self.env.uid,
        })

    def _send_inventory_webhook(self, picking):
        """Send inventory update to external system."""
        webhook_url = picking.company_id.x_webhook_url
        
        payload = {
            'picking_id': picking.id,
            'name': picking.name,
            'state': picking.state,
            'products': [{
                'id': m.product_id.id,
                'name': m.product_id.name,
                'qty': m.product_uom_qty,
            } for m in picking.move_ids],
        }
        
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        
        return response.json()

    def action_run_inventory_check(self):
        """Run comprehensive inventory check.
        
        This uses eval for dynamic filter - flagged as complex.
        """
        filter_domain = self.env['ir.config_parameter'].sudo().get_param(
            'stock.inventory_check_domain', '[]'
        )
        
        # Dynamic domain evaluation (flagged for complexity)
        domain = eval(filter_domain)
        pickings = self.search(domain)
        
        for picking in pickings:
            picking.automation_update_inventory()
