"""Test source extractors."""

import tempfile
from pathlib import Path

import pytest
from source_extractors import (
    SourceFieldExtractor,
    SourceServerActionExtractor,
    SourceViewExtractor,
    load_source_components,
)


class TestSourceExtractors:
    """Test source code extraction functionality."""

    def test_source_field_extractor(self):
        """Test field extraction from Python source."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir)

            # Create a mock Odoo model file
            model_file = source_dir / "models" / "partner.py"
            model_file.parent.mkdir(parents=True)
            model_file.write_text(
                """
from odoo import models, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'

    custom_field = fields.Char(string='Custom Field')
    computed_field = fields.Float(compute='_compute_total', store=True)
    related_field = fields.Char(related='parent_id.name')
"""
            )

            extractor = SourceFieldExtractor(source_dir)
            components = extractor.extract()

            assert len(components) == 3
            field_names = {comp.name for comp in components}
            assert "custom_field" in field_names
            assert "computed_field" in field_names
            assert "related_field" in field_names
            
            # Verify string parameter is extracted correctly
            custom_field = next(c for c in components if c.name == "custom_field")
            assert custom_field.display_name == "Custom Field"
            assert custom_field.raw_data.get("string") == "Custom Field"
            
            # Fields without string parameter should fall back to field name
            computed_field = next(c for c in components if c.name == "computed_field")
            assert computed_field.display_name == "computed_field"
            assert computed_field.raw_data.get("string") == "computed_field"

    def test_source_view_extractor(self):
        """Test view extraction from XML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir)

            # Create a mock view file
            view_file = source_dir / "views" / "partner_views.xml"
            view_file.parent.mkdir(parents=True)
            view_file.write_text(
                """<?xml version="1.0"?>
<odoo>
    <record id="view_partner_form_custom" model="ir.ui.view">
        <field name="name">res.partner.form.custom</field>
        <field name="model">res.partner</field>
        <field name="arch" type="xml">
            <form>
                <field name="name"/>
                <field name="email"/>
                <group>
                    <field name="phone"/>
                    <field name="mobile"/>
                </group>
                <button name="action_custom" string="Custom Action"/>
            </form>
        </field>
    </record>
</odoo>"""
            )

            extractor = SourceViewExtractor(source_dir)
            components = extractor.extract()

            assert len(components) == 1
            comp = components[0]
            assert comp.component_type == "view"
            # Name should be the view's name field (for matching TOML refs), not record ID
            assert comp.name == "res.partner.form.custom"
            assert comp.display_name == "res.partner.form.custom"
            assert comp.model == "res.partner"
            # Record ID should be in raw_data
            assert comp.raw_data.get("record_id") == "view_partner_form_custom"

    def test_load_source_components(self):
        """Test loading all components from source directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_dir = Path(tmpdir)

            # Create model file
            model_file = source_dir / "models.py"
            model_file.write_text(
                """
from odoo import models, fields

class TestModel(models.Model):
    _name = 'test.model'

    name = fields.Char(string='Name')
"""
            )

            # Create view file
            view_file = source_dir / "views.xml"
            view_file.write_text(
                """<?xml version="1.0"?>
<odoo>
    <record id="test_view" model="ir.ui.view">
        <field name="model">test.model</field>
        <field name="arch" type="xml">
            <form><field name="name"/></form>
        </field>
    </record>
</odoo>"""
            )

            components = load_source_components(source_dir)

            # Should find 1 field and 1 view
            assert len(components) >= 2
            component_types = {comp.component_type for comp in components}
            assert "field" in component_types
            assert "view" in component_types
