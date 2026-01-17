"""Tests for ModuleGenerator (V1.1.2) - Module-Based Structure Generation.

Tests module-based folder organization, model mapping, computed fields,
clean XML views, and report template extraction.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "shared" / "python"))

from feature_detector import Component, ComponentType
from module_generator import ModuleGenerator, ModuleGeneratorError
from module_mapper import ModuleMapper


@pytest.fixture
def temp_project():
    """Create temporary project directory."""
    temp_dir = tempfile.mkdtemp()
    project_root = Path(temp_dir)

    # Create .odoo-sync structure
    (project_root / ".odoo-sync" / "data" / "extracted").mkdir(parents=True)
    (project_root / ".odoo-sync" / "data" / "cache").mkdir(parents=True)

    yield project_root

    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_odoo_source(temp_project):
    """Create mock Odoo source directory structure."""
    odoo_source = temp_project / "odoo_source"
    addons_dir = odoo_source / "addons"

    # Create sale module
    sale_models = addons_dir / "sale" / "models"
    sale_models.mkdir(parents=True)
    (sale_models / "sale_order.py").write_text(
        """
class SaleOrder(models.Model):
    _name = 'sale.order'
    _description = 'Sale Order'

class SaleOrderLine(models.Model):
    _name = 'sale.order.line'
    _description = 'Sale Order Line'
"""
    )

    # Create stock module
    stock_models = addons_dir / "stock" / "models"
    stock_models.mkdir(parents=True)
    (stock_models / "stock_picking.py").write_text(
        """
class StockPicking(models.Model):
    _name = 'stock.picking'
    _description = 'Stock Picking'
"""
    )

    # Create mrp module
    mrp_models = addons_dir / "mrp" / "models"
    mrp_models.mkdir(parents=True)
    (mrp_models / "mrp_production.py").write_text(
        """
class MrpProduction(models.Model):
    _name = 'mrp.production'
    _description = 'Manufacturing Order'
"""
    )

    return odoo_source


@pytest.fixture
def module_mapper(mock_odoo_source):
    """Create ModuleMapper instance."""
    # Create module_model_map.toml file from mock Odoo source
    map_file = mock_odoo_source / "module_model_map.toml"
    toml_content = """[modules.sale]
models = ["sale.order", "sale.order.line"]

[modules.account]
models = ["account.move", "account.move.line"]

[modules.mrp]
models = ["mrp.production"]

[modules.stock]
models = ["stock.picking"]
"""
    map_file.write_text(toml_content)
    
    mapper = ModuleMapper(map_file)
    return mapper


def test_module_mapper_build_map(module_mapper):
    """Test building model→module mapping from Odoo source."""
    model_map = module_mapper.build_model_map()

    assert "sale.order" in model_map
    assert model_map["sale.order"] == "sale"
    assert "sale.order.line" in model_map
    assert model_map["sale.order.line"] == "sale"
    assert "stock.picking" in model_map
    assert model_map["stock.picking"] == "stock"


def test_module_mapper_is_custom_model(module_mapper):
    """Test custom model detection."""
    assert module_mapper.is_custom_model("x_studio_custom_field") is True
    assert module_mapper.is_custom_model("x_tracking") is True
    assert module_mapper.is_custom_model("sale.order") is False


def test_module_mapper_standard_model_not_found(module_mapper):
    """Test that nonexistent models return None."""
    result = module_mapper.get_module_for_model("nonexistent.model")
    assert result is None


def test_module_based_structure_creation(temp_project, module_mapper):
    """Test module-based directory structure creation."""
    generator = ModuleGenerator(
        project_root=temp_project, model_module_map=module_mapper.load_map(), dry_run=False
    )

    components = [
        Component(
            id=1,
            name="x_test_field",
            component_type=ComponentType.FIELD,
            model="sale.order",
            complexity="simple",
            raw_data={
                "name": "x_test_field",
                "ttype": "char",
                "field_description": "Test Field",
            },
        ),
        Component(
            id=2,
            name="x_stock_field",
            component_type=ComponentType.FIELD,
            model="stock.picking",
            complexity="simple",
            raw_data={
                "name": "x_stock_field",
                "ttype": "char",
                "field_description": "Stock Field",
            },
        ),
    ]

    result = generator.generate_structure(components)

    # Verify module directories created
    assert (temp_project / "sale" / "models").exists()
    assert (temp_project / "sale" / "views").exists()
    assert (temp_project / "sale" / "actions").exists()
    assert (temp_project / "sale" / "reports").exists()
    assert (temp_project / "stock" / "models").exists()

    # Verify model files created
    assert (temp_project / "sale" / "models" / "sale_order.py").exists()
    assert (temp_project / "stock" / "models" / "stock_picking.py").exists()


def test_computed_field_with_separate_method(temp_project, module_mapper):
    """Test computed field generates separate method with @api.depends."""
    generator = ModuleGenerator(
        project_root=temp_project, model_module_map=module_mapper.load_map(), dry_run=False
    )

    components = [
        Component(
            id=1,
            name="x_total_amount",
            component_type=ComponentType.FIELD,
            model="sale.order",
            complexity="medium",
            raw_data={
                "name": "x_total_amount",
                "ttype": "float",
                "field_description": "Total Amount",
                "compute": "_compute_x_total_amount",
                "depends": "order_line.price_subtotal",
            },
        )
    ]

    result = generator.generate_structure(components)

    model_file = temp_project / "sale" / "models" / "sale_order.py"
    content = model_file.read_text()

    # Verify field definition
    assert "x_total_amount = fields.Float(" in content
    assert 'compute="_compute_x_total_amount"' in content

    # Verify separate method with decorator
    assert "@api.depends('order_line.price_subtotal')" in content
    assert "def _compute_x_total_amount(self):" in content


def test_view_xml_without_cdata(temp_project, module_mapper):
    """Test view XML generation WITHOUT CDATA wrapper."""
    # Create empty views_metadata.json
    views_metadata = (
        temp_project
        / ".odoo-sync"
        / "data"
        / "extracted"
        / "views_metadata.json"
    )
    views_metadata.write_text("[]")

    generator = ModuleGenerator(
        project_root=temp_project, model_module_map=module_mapper.load_map(), dry_run=False
    )

    components = [
        Component(
            id=1,
            name="sale.order.form.custom",
            component_type=ComponentType.VIEW,
            model="sale.order",
            complexity="simple",
            raw_data={
                "name": "sale.order.form.custom",
                "model": "sale.order",
                "type": "form",
                "priority": 16,
                "inherit_id": [1234, "sale.view_order_form"],
                "inherit_view_xml_id": "sale.view_order_form",
                "arch_db": '<xpath expr="//field[@name=\'partner_id\']" position="after">\n  <field name="x_custom_field"/>\n</xpath>',
            },
        )
    ]

    result = generator.generate_structure(components)

    view_file = temp_project / "sale" / "views" / "sale.order.form.custom.xml"
    content = view_file.read_text()

    # Verify NO CDATA wrapper
    assert "<![CDATA[" not in content
    assert "]]>" not in content

    # Verify proper inherit_id with ref
    assert "inherit_id" in content
    assert 'ref="sale.view_order_form"' in content

    # Verify arch content directly embedded
    assert '<field name="arch" type="xml">' in content


def test_empty_domain_hiding(temp_project, module_mapper):
    """Test that empty domains are not shown in field definitions."""
    generator = ModuleGenerator(
        project_root=temp_project, model_module_map=module_mapper.load_map(), dry_run=False
    )

    components = [
        Component(
            id=1,
            name="x_partner_id",
            component_type=ComponentType.FIELD,
            model="sale.order",
            complexity="simple",
            raw_data={
                "name": "x_partner_id",
                "ttype": "many2one",
                "field_description": "Partner",
                "relation": "res.partner",
                "domain": "[]",
            },
        )
    ]

    result = generator.generate_structure(components)

    model_file = temp_project / "sale" / "models" / "sale_order.py"
    content = model_file.read_text()

    # Verify domain is NOT shown
    assert "domain=" not in content


def test_filter_domain_cleaning(temp_project, module_mapper):
    """Test that &quot; is replaced with ' in automation filter_domain."""
    generator = ModuleGenerator(
        project_root=temp_project, model_module_map=module_mapper.load_map(), dry_run=False
    )

    components = [
        Component(
            id=1,
            name="Credit Auto-Hold",
            component_type=ComponentType.AUTOMATION,
            model="sale.order",
            complexity="simple",
            raw_data={
                "name": "Credit Auto-Hold",
                "model_name": "sale.order",
                "trigger": "on_write",
                "filter_domain": "[(&quot;amount_total&quot;, &quot;>&quot;, 0)]",
                "active": True,
            },
        )
    ]

    result = generator.generate_structure(components)

    automation_file = (
        temp_project
        / "sale"
        / "actions"
        / "automations"
        / "credit_auto-hold.xml"
    )
    content = automation_file.read_text()

    # Verify &quot; replaced with '
    assert "&quot;" not in content


def test_timestamped_backup_creation(temp_project, module_mapper):
    """Test that timestamped backup is created."""
    generator = ModuleGenerator(
        project_root=temp_project, model_module_map=module_mapper.load_map(), dry_run=False
    )

    # Create initial structure
    (temp_project / "sale" / "models").mkdir(parents=True)
    (temp_project / "sale" / "models" / "sale_order.py").write_text(
        "# Test content"
    )

    components = [
        Component(
            id=1,
            name="x_test",
            component_type=ComponentType.FIELD,
            model="sale.order",
            complexity="simple",
            raw_data={
                "name": "x_test",
                "ttype": "char",
                "field_description": "Test",
            },
        )
    ]

    result = generator.generate_structure(components)

    # Verify backup was created
    assert result.get("backup_created") is not None
    backup_path = Path(result["backup_created"])
    assert backup_path.exists()
    assert backup_path.name.startswith("odoo-history-")


def test_report_template_extraction(temp_project, module_mapper):
    """Test extraction of QWeb templates from views_metadata."""
    views_metadata = [
        {
            "id": 100,
            "name": "report_custom_quote",
            "key": "sale.report_custom_quote",
            "type": "qweb",
            "xml_id": "sale.report_custom_quote",
            "arch_db": '<t t-name="sale.report_custom_quote">\n  <div>Custom content</div>\n</t>',
        }
    ]

    metadata_file = (
        temp_project
        / ".odoo-sync"
        / "data"
        / "extracted"
        / "views_metadata.json"
    )
    metadata_file.write_text(json.dumps(views_metadata))

    generator = ModuleGenerator(
        project_root=temp_project, model_module_map=module_mapper.load_map(), dry_run=False
    )

    components = [
        Component(
            id=1,
            name="Custom Sale Report",
            component_type=ComponentType.REPORT,
            model="sale.order",
            complexity="simple",
            raw_data={
                "name": "Custom Sale Report",
                "model": "sale.order",
                "report_type": "qweb-pdf",
                "report_name": "sale.report_custom_quote",
            },
        )
    ]

    result = generator.generate_structure(components)

    # Verify report action file created
    report_file = temp_project / "sale" / "reports" / "custom_sale_report.xml"
    assert report_file.exists()

    # Verify template file created
    template_file = (
        temp_project / "sale" / "reports" / "report_custom_quote_template.xml"
    )
    assert template_file.exists()

    template_content = template_file.read_text()
    assert '<template id="sale.report_custom_quote">' in template_content


def test_dry_run_no_files_created(temp_project, module_mapper):
    """Test dry-run mode doesn't create any files."""
    generator = ModuleGenerator(
        project_root=temp_project, model_module_map=module_mapper.load_map(), dry_run=True
    )

    components = [
        Component(
            id=1,
            name="x_test",
            component_type=ComponentType.FIELD,
            model="sale.order",
            complexity="simple",
            raw_data={
                "name": "x_test",
                "ttype": "char",
                "field_description": "Test",
            },
        )
    ]

    result = generator.generate_structure(components)

    # Verify no module directories created
    assert not (temp_project / "sale").exists()
    assert result["dry_run"] is True


def test_multiple_models_same_module(temp_project, module_mapper):
    """Test multiple models in same module create separate files."""
    generator = ModuleGenerator(
        project_root=temp_project, model_module_map=module_mapper.load_map(), dry_run=False
    )

    components = [
        Component(
            id=1,
            name="x_field1",
            component_type=ComponentType.FIELD,
            model="sale.order",
            complexity="simple",
            raw_data={
                "name": "x_field1",
                "ttype": "char",
                "field_description": "Field 1",
            },
        ),
        Component(
            id=2,
            name="x_field2",
            component_type=ComponentType.FIELD,
            model="sale.order.line",
            complexity="simple",
            raw_data={
                "name": "x_field2",
                "ttype": "char",
                "field_description": "Field 2",
            },
        ),
    ]

    result = generator.generate_structure(components)

    # Verify both files created in same module
    assert (temp_project / "sale" / "models" / "sale_order.py").exists()
    assert (temp_project / "sale" / "models" / "sale_order_line.py").exists()


def test_related_fields_shown(temp_project, module_mapper):
    """Test that related fields are shown in field definition."""
    generator = ModuleGenerator(
        project_root=temp_project, model_module_map=module_mapper.load_map(), dry_run=False
    )

    components = [
        Component(
            id=1,
            name="x_partner_email",
            component_type=ComponentType.FIELD,
            model="sale.order",
            complexity="simple",
            raw_data={
                "name": "x_partner_email",
                "ttype": "char",
                "field_description": "Partner Email",
                "related": "partner_id.email",
                "readonly": True,
            },
        )
    ]

    result = generator.generate_structure(components)

    model_file = temp_project / "sale" / "models" / "sale_order.py"
    content = model_file.read_text()

    # Verify related field shown
    assert 'related="partner_id.email"' in content


# Helper method tests


def test_sanitize_filename(temp_project, module_mapper):
    """Test filename sanitization."""
    gen = ModuleGenerator(temp_project, module_mapper.load_map(), dry_run=True)

    assert gen._sanitize_filename("Sale Order Form") == "sale_order_form"
    assert gen._sanitize_filename("Test/Action") == "test_action"
    assert gen._sanitize_filename("Test<>Action") == "testaction"
    assert gen._sanitize_filename("") == "unnamed"


def test_sanitize_model_name(temp_project, module_mapper):
    """Test model name sanitization."""
    gen = ModuleGenerator(temp_project, module_mapper.load_map(), dry_run=True)

    assert gen._sanitize_model_name("sale.order") == "sale_order"
    assert gen._sanitize_model_name("res.partner") == "res_partner"


def test_model_to_class_name(temp_project, module_mapper):
    """Test model to class name conversion."""
    gen = ModuleGenerator(temp_project, module_mapper.load_map(), dry_run=True)

    assert gen._model_to_class_name("sale.order") == "SaleOrder"
    assert gen._model_to_class_name("res.partner") == "ResPartner"
    assert gen._model_to_class_name("account.move.line") == "AccountMoveLine"


def test_escape_xml(temp_project, module_mapper):
    """Test XML escaping."""
    gen = ModuleGenerator(temp_project, module_mapper.load_map(), dry_run=True)

    assert gen._escape_xml("Test & Co") == "Test &amp; Co"
    assert gen._escape_xml("Price < 100") == "Price &lt; 100"
    assert gen._escape_xml("Value > 50") == "Value &gt; 50"


# QWeb Report Template Placement Tests


def test_extract_tcall_references(temp_project, module_mapper):
    """Test extraction of t-call references from QWeb arch_db."""
    gen = ModuleGenerator(temp_project, module_mapper.load_map(), dry_run=True)

    # Test with multiple t-call references
    arch_db = '''<t t-name="main_report">
        <t t-call="web.html_container">
            <t t-call="studio_customization.report_document"/>
            <t t-call='studio_customization.report_footer'/>
        </t>
    </t>'''

    tcalls = gen._extract_tcall_references(arch_db)

    # web.* templates should be filtered out
    assert "web.html_container" not in tcalls
    assert "studio_customization.report_document" in tcalls
    assert "studio_customization.report_footer" in tcalls
    assert len(tcalls) == 2


def test_extract_tcall_references_empty(temp_project, module_mapper):
    """Test extraction with no t-call references."""
    gen = ModuleGenerator(temp_project, module_mapper.load_map(), dry_run=True)

    arch_db = '<div class="page"><span t-field="doc.name"/></div>'
    tcalls = gen._extract_tcall_references(arch_db)

    assert len(tcalls) == 0


def test_build_qweb_view_index(temp_project, module_mapper):
    """Test building QWeb view index from views_metadata."""
    gen = ModuleGenerator(temp_project, module_mapper.load_map(), dry_run=True)

    # Manually set up views_metadata for testing
    gen._views_metadata = {
        1: {"id": 1, "name": "test.template", "key": "test.template", "type": "qweb", "model": False},
        2: {"id": 2, "name": "sale.order.form", "type": "form", "model": "sale.order"},
        3: {"id": 3, "name": "another.template", "key": "studio.another", "type": "qweb", "model": False},
    }

    index = gen._build_qweb_view_index()

    # Only QWeb views with model=False should be indexed
    assert "test.template" in index
    assert "studio.another" in index
    assert "another.template" in index  # Also indexed by name
    assert "sale.order.form" not in index  # Not a QWeb view
    

def test_resolve_transitive_tcall_dependencies(temp_project, module_mapper):
    """Test resolving transitive t-call dependencies."""
    gen = ModuleGenerator(temp_project, module_mapper.load_map(), dry_run=True)

    # Set up a chain: main -> doc -> header, footer
    gen._views_metadata = {
        1: {
            "id": 1,
            "name": "studio.main_report",
            "key": "studio.main_report",
            "type": "qweb",
            "model": False,
            "arch_db": '<t t-call="studio.report_document"/>'
        },
        2: {
            "id": 2,
            "name": "studio.report_document",
            "key": "studio.report_document",
            "type": "qweb",
            "model": False,
            "arch_db": '<t t-call="studio.header"/><div/><t t-call="studio.footer"/>'
        },
        3: {
            "id": 3,
            "name": "studio.header",
            "key": "studio.header",
            "type": "qweb",
            "model": False,
            "arch_db": '<div>Header</div>'
        },
        4: {
            "id": 4,
            "name": "studio.footer",
            "key": "studio.footer",
            "type": "qweb",
            "model": False,
            "arch_db": '<div>Footer</div>'
        },
    }

    qweb_index = gen._build_qweb_view_index()
    deps = gen._resolve_all_tcall_dependencies("studio.main_report", qweb_index)

    # Should find all 4 templates
    assert "studio.main_report" in deps
    assert "studio.report_document" in deps
    assert "studio.header" in deps
    assert "studio.footer" in deps
    assert len(deps) == 4


def test_qweb_views_skipped_in_generate_views(temp_project, module_mapper):
    """Test that QWeb views (type=qweb, model=False) are skipped in _generate_views."""
    # Create the studio directory so cleanup doesn't fail
    (temp_project / "studio").mkdir(parents=True, exist_ok=True)
    
    gen = ModuleGenerator(temp_project, module_mapper.load_map(), dry_run=False)

    # Need arch_db > 50 chars to pass validation
    long_arch = '<form string="Sale Order Form"><sheet><group><field name="name"/><field name="partner_id"/></group></sheet></form>'
    qweb_arch = '<t t-name="test"><div class="page"><span t-field="doc.name"/></div></t>'

    components = [
        Component(
            id=1,
            name="studio_customization.qweb_template",
            display_name="QWeb Template",
            component_type=ComponentType.VIEW,
            model="",  # QWeb views have no model
            complexity="simple",
            raw_data={
                "name": "studio_customization.qweb_template",
                "type": "qweb",
                "model": False,  # Key indicator of QWeb report template
                "arch_db": qweb_arch,
            },
        ),
        Component(
            id=2,
            name="sale.order.form.custom",
            display_name="Sale Order Form",
            component_type=ComponentType.VIEW,
            model="sale.order",
            complexity="simple",
            raw_data={
                "name": "sale.order.form.custom",
                "type": "form",
                "model": "sale.order",
                "arch_db": long_arch,
            },
        ),
    ]

    result = gen.generate_structure(components)

    # Check no errors for the form view
    assert result["files_created"]["views"] == 1, f"Expected 1 view, got errors: {result['errors']}"
    
    # QWeb view should NOT be in views folder (it's handled by reports)
    assert not (temp_project / "studio" / "base" / "views" / "studio_customization.qweb_template.xml").exists()
    
    # Regular form view should be generated (note: dots are preserved in filename)
    assert (temp_project / "studio" / "sale" / "views" / "sale.order.form.custom.xml").exists()


def test_qweb_templates_placed_with_report(temp_project, module_mapper):
    """Test that QWeb templates are placed in the same module as their report."""
    # Create extraction result files
    views_metadata = {
        "records": [
            {
                "id": 100,
                "name": "studio_customization.test_label_main",
                "key": "studio_customization.test_label_main",
                "type": "qweb",
                "model": False,
                "arch_db": '<t t-name="main"><t t-call="studio_customization.test_label_doc"/></t>'
            },
            {
                "id": 101,
                "name": "studio_customization.test_label_doc",
                "key": "studio_customization.test_label_doc",
                "type": "qweb",
                "model": False,
                "arch_db": '<div class="page"><span t-field="doc.name"/></div>'
            },
        ]
    }
    
    reports_data = {
        "records": [
            {
                "id": 200,
                "name": "Test Label Report",
                "model": "stock.picking",  # This determines the module
                "report_type": "qweb-pdf",
                "report_name": "studio_customization.test_label_main",
            }
        ]
    }

    # Write test data files
    extraction_dir = temp_project / ".odoo-sync" / "data" / "extraction-results"
    extraction_dir.mkdir(parents=True, exist_ok=True)
    
    import json
    (extraction_dir / "views_metadata.json").write_text(json.dumps(views_metadata))
    (extraction_dir / "reports_output.json").write_text(json.dumps(reports_data))

    # Create generator - it will load the test data
    gen = ModuleGenerator(temp_project, module_mapper.load_map(), dry_run=False)

    # Create a report component
    components = [
        Component(
            id=200,
            name="Test Label Report",
            display_name="Test Label Report",
            component_type=ComponentType.REPORT,
            model="stock.picking",
            complexity="simple",
            raw_data={
                "id": 200,
                "name": "Test Label Report",
                "model": "stock.picking",
                "report_type": "qweb-pdf",
                "report_name": "studio_customization.test_label_main",
            },
        ),
    ]

    result = gen.generate_structure(components)

    # Report should be in stock module (based on stock.picking model)
    assert (temp_project / "studio" / "stock" / "reports" / "test_label_report.xml").exists()
    
    # Both QWeb templates should be in stock module (same as report)
    assert (temp_project / "studio" / "stock" / "reports" / "test_label_main_template.xml").exists()
    assert (temp_project / "studio" / "stock" / "reports" / "test_label_doc_template.xml").exists()
    
    # Templates should NOT be in base module
    assert not (temp_project / "studio" / "base" / "reports").exists()
    
    # reports_map.md should be generated
    reports_map = temp_project / "studio" / "reports_map.md"
    assert reports_map.exists()
    
    content = reports_map.read_text()
    assert "Test Label Report" in content
    assert "stock.picking" in content
    assert "test_label_main" in content
    assert "test_label_doc" in content


def test_reports_map_shows_template_hierarchy(temp_project, module_mapper):
    """Test that reports_map.md shows the template call hierarchy."""
    # Create extraction result files with nested templates
    views_metadata = {
        "records": [
            {
                "id": 100,
                "name": "studio.main_template",
                "key": "studio.main_template",
                "type": "qweb",
                "model": False,
                "arch_db": '<t t-name="main"><t t-call="studio.level1_template"/></t>'
            },
            {
                "id": 101,
                "name": "studio.level1_template",
                "key": "studio.level1_template",
                "type": "qweb",
                "model": False,
                "arch_db": '<t t-name="level1"><t t-call="studio.level2_template"/></t>'
            },
            {
                "id": 102,
                "name": "studio.level2_template",
                "key": "studio.level2_template",
                "type": "qweb",
                "model": False,
                "arch_db": '<div class="page">Leaf content</div>'
            },
        ]
    }
    
    reports_data = {
        "records": [
            {
                "id": 200,
                "name": "Nested Report",
                "model": "sale.order",
                "report_type": "qweb-pdf",
                "report_name": "studio.main_template",
            }
        ]
    }

    # Write test data files
    extraction_dir = temp_project / ".odoo-sync" / "data" / "extraction-results"
    extraction_dir.mkdir(parents=True, exist_ok=True)
    
    import json
    (extraction_dir / "views_metadata.json").write_text(json.dumps(views_metadata))
    (extraction_dir / "reports_output.json").write_text(json.dumps(reports_data))

    # Create generator
    gen = ModuleGenerator(temp_project, module_mapper.load_map(), dry_run=False)

    components = [
        Component(
            id=200,
            name="Nested Report",
            display_name="Nested Report",
            component_type=ComponentType.REPORT,
            model="sale.order",
            complexity="simple",
            raw_data={
                "id": 200,
                "name": "Nested Report",
                "model": "sale.order",
                "report_type": "qweb-pdf",
                "report_name": "studio.main_template",
            },
        ),
    ]

    result = gen.generate_structure(components)

    # Check reports_map.md shows hierarchy
    reports_map = temp_project / "studio" / "reports_map.md"
    assert reports_map.exists()
    
    content = reports_map.read_text()
    
    # Verify hierarchy is shown
    assert "studio.main_template" in content
    assert "studio.level1_template" in content
    assert "studio.level2_template" in content
    assert "called by parent" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
