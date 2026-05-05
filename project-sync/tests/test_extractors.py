"""Tests for Odoo component extractors."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from extractors import (
    AutomationsExtractor,
    BaseExtractor,
    ExtractionResult,
    FieldsExtractor,
    ReportsExtractor,
    ServerActionsExtractor,
    ViewsExtractor,
)


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock Odoo client."""
    client = MagicMock()
    client.search_read = MagicMock(return_value=[])
    client.read = MagicMock(return_value=[])
    return client


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    """Create output directory for extraction results."""
    output = tmp_path / ".odoo-sync" / "data" / "extraction-results"
    output.mkdir(parents=True)
    return output


class TestExtractionResult:
    """Tests for ExtractionResult dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = ExtractionResult(
            extractor_name="test",
            model="test.model",
            record_count=5,
            records=[{"id": 1}],
            output_file="test.json",
            dry_run=True,
        )
        data = result.to_dict()

        assert data["extractor"] == "test"
        assert data["model"] == "test.model"
        assert data["record_count"] == 5
        assert len(data["records"]) == 1
        assert data["dry_run"] is True


class TestFieldsExtractor:
    """Tests for FieldsExtractor."""

    def test_get_domain_default(
        self, mock_client: MagicMock, output_dir: Path
    ):
        """Test default domain includes manual state and x_ prefix."""
        extractor = FieldsExtractor(mock_client, output_dir)
        domain = extractor.get_domain()

        # Should have state=manual and x_studio/x_ filters
        assert ["state", "=", "manual"] in domain
        assert "|" in domain
        assert ["name", "=like", "x_studio_%"] in domain
        assert ["name", "=like", "x_%"] in domain

    def test_get_domain_with_base_filters(
        self, mock_client: MagicMock, output_dir: Path
    ):
        """Test domain with custom base filters."""
        extractor = FieldsExtractor(mock_client, output_dir)
        domain = extractor.get_domain([["model", "=", "res.partner"]])

        assert ["model", "=", "res.partner"] in domain

    def test_transform_record_studio_field(
        self, mock_client: MagicMock, output_dir: Path
    ):
        """Test transformation identifies Studio fields."""
        extractor = FieldsExtractor(mock_client, output_dir)
        record = {
            "id": 1,
            "name": "x_studio_custom",
            "ttype": "char",
            "model_id": [10, "res.partner"],
        }
        result = extractor.transform_record(record)

        assert result["is_studio"] is True
        assert result["field_type_display"] == "Text"
        assert result["model_name"] == "res.partner"

    def test_transform_record_custom_field(
        self, mock_client: MagicMock, output_dir: Path
    ):
        """Test transformation identifies non-Studio custom fields."""
        extractor = FieldsExtractor(mock_client, output_dir)
        record = {
            "id": 2,
            "name": "x_my_field",
            "ttype": "many2one",
            "relation": "product.product",
            "model_id": [20, "sale.order"],
        }
        result = extractor.transform_record(record)

        assert result["is_studio"] is False
        assert "Many2One" in result["field_type_display"]
        assert "product.product" in result["field_type_display"]

    def test_extract_dry_run(self, mock_client: MagicMock, output_dir: Path):
        """Test extraction in dry-run mode doesn't write files."""
        mock_client.search_read.return_value = [
            {"id": 1, "name": "x_studio_test", "ttype": "char"}
        ]
        extractor = FieldsExtractor(mock_client, output_dir, dry_run=True)
        result = extractor.extract()

        assert result.dry_run is True
        assert result.record_count == 1
        assert not (output_dir / "custom_fields_output.json").exists()

    def test_extract_execute(self, mock_client: MagicMock, output_dir: Path):
        """Test extraction with execute writes files."""
        mock_client.search_read.return_value = [
            {"id": 1, "name": "x_studio_test", "ttype": "char"}
        ]
        extractor = FieldsExtractor(mock_client, output_dir, dry_run=False)
        result = extractor.extract()

        assert result.dry_run is False
        assert (output_dir / "custom_fields_output.json").exists()

        with open(output_dir / "custom_fields_output.json") as f:
            data = json.load(f)
        assert data["record_count"] == 1


class TestViewsExtractor:
    """Tests for ViewsExtractor with two-phase extraction."""

    def test_get_domain(self, mock_client: MagicMock, output_dir: Path):
        """Test domain targets Studio views."""
        extractor = ViewsExtractor(mock_client, output_dir)
        domain = extractor.get_domain()

        # Should search for studio markers
        assert ["name", "ilike", "studio"] in domain
        assert ["arch_db", "ilike", "x_studio_"] in domain

    def test_two_phase_extraction(
        self, mock_client: MagicMock, output_dir: Path
    ):
        """Test two-phase extraction fetches arch separately."""
        # Phase 1: metadata
        mock_client.search_read.return_value = [
            {
                "id": 1,
                "name": "studio_form",
                "model": "res.partner",
                "type": "form",
            }
        ]
        # Phase 2: arch
        mock_client.read.return_value = [
            {"arch_db": "<form><field name='x_studio_test'/></form>"}
        ]

        extractor = ViewsExtractor(mock_client, output_dir, dry_run=True)
        result = extractor.extract()

        # Verify two-phase calls
        mock_client.search_read.assert_called_once()
        mock_client.read.assert_called_once_with(
            model="ir.ui.view",
            ids=[1],
            fields=["arch_db"],
        )

        assert result.record_count == 1
        assert (
            result.records[0]["arch_db"]
            == "<form><field name='x_studio_test'/></form>"
        )
        assert result.records[0]["has_studio_fields"] is True

    def test_transform_record_complexity(
        self, mock_client: MagicMock, output_dir: Path
    ):
        """Test complexity estimation based on arch size."""
        extractor = ViewsExtractor(mock_client, output_dir)

        # Simple view
        simple = extractor.transform_record(
            {"id": 1, "arch_db": "<form></form>", "inherit_id": False}
        )
        assert simple["complexity"] == "simple"

        # Complex view (> 5000 chars)
        complex_arch = "<form>" + "x" * 6000 + "</form>"
        complex_view = extractor.transform_record(
            {"id": 2, "arch_db": complex_arch, "inherit_id": False}
        )
        assert complex_view["complexity"] == "complex"


class TestServerActionsExtractor:
    """Tests for ServerActionsExtractor."""

    def test_get_domain(self, mock_client: MagicMock, output_dir: Path):
        """Test domain targets Studio server actions."""
        extractor = ServerActionsExtractor(mock_client, output_dir)
        domain = extractor.get_domain()

        assert ["name", "ilike", "studio"] in domain
        assert ["code", "ilike", "x_studio_"] in domain

    def test_transform_record(self, mock_client: MagicMock, output_dir: Path):
        """Test transformation of server action records."""
        extractor = ServerActionsExtractor(mock_client, output_dir)
        record = {
            "id": 1,
            "name": "Studio Action",
            "state": "code",
            "code": "record.x_studio_field = True",
            "model_id": [5, "res.partner"],
            "binding_model_id": [5, "res.partner"],
        }
        result = extractor.transform_record(record)

        assert result["action_type_display"] == "Execute Python Code"
        assert result["has_studio_fields"] is True
        assert result["model_display"] == "res.partner"
        assert result["binding_model_display"] == "res.partner"


class TestAutomationsExtractor:
    """Tests for AutomationsExtractor."""

    def test_get_domain_default_active(
        self, mock_client: MagicMock, output_dir: Path
    ):
        """Test default domain includes active=True."""
        extractor = AutomationsExtractor(mock_client, output_dir)
        domain = extractor.get_domain()

        assert ["active", "=", True] in domain

    def test_transform_record_triggers(
        self, mock_client: MagicMock, output_dir: Path
    ):
        """Test transformation of automation triggers."""
        extractor = AutomationsExtractor(mock_client, output_dir)
        record = {
            "id": 1,
            "name": "Studio Automation",
            "trigger": "on_create",
            "model_id": [10, "sale.order"],
            "filter_domain": "[('x_studio_status', '=', 'new')]",
            "filter_pre_domain": "",
            "trigger_field_ids": [1, 2],
            "action_server_ids": [5],
        }
        result = extractor.transform_record(record)

        assert result["trigger_display"] == "On Creation"
        assert result["has_studio_fields"] is True
        assert result["trigger_field_count"] == 2
        assert result["action_count"] == 1


class TestReportsExtractor:
    """Tests for ReportsExtractor."""

    def test_get_domain(self, mock_client: MagicMock, output_dir: Path):
        """Test domain targets Studio reports."""
        extractor = ReportsExtractor(mock_client, output_dir)
        domain = extractor.get_domain()

        assert ["name", "ilike", "studio"] in domain
        assert ["model", "ilike", "x_"] in domain

    def test_transform_record(self, mock_client: MagicMock, output_dir: Path):
        """Test transformation of report records."""
        extractor = ReportsExtractor(mock_client, output_dir)
        record = {
            "id": 1,
            "name": "Studio Invoice Report",
            "report_name": "studio_invoice",
            "report_type": "qweb-pdf",
            "model": "account.move",
            "binding_model_id": [15, "account.move"],
            "paperformat_id": [1, "A4"],
            "attachment": False,
            "print_report_name": "",
            "groups_id": [],
        }
        result = extractor.transform_record(record)

        assert result["report_type_display"] == "PDF Report"
        assert result["is_studio_report"] is True
        assert result["is_custom_model"] is False
        assert result["complexity"] == "simple"


class TestMockProjectIntegration:
    """Integration tests using the mock project structure."""

    @pytest.fixture
    def mock_project_path(self) -> Path:
        """Get path to mock project fixture."""
        return Path(__file__).parent / "fixtures" / "mock_project"

    def test_mock_project_config_exists(self, mock_project_path: Path):
        """Verify mock project has config file."""
        config_path = mock_project_path / ".odoo-sync" / "odoo-instances.json"
        assert config_path.exists()

        with open(config_path) as f:
            config = json.load(f)

        assert "implementation" in config["instances"]
        assert "development" in config["instances"]
        assert config["instances"]["implementation"]["read_only"] is True

    def test_mock_project_output_dir_exists(self, mock_project_path: Path):
        """Verify mock project has extraction output directory."""
        output_dir = (
            mock_project_path / ".odoo-sync" / "data" / "extraction-results"
        )
        assert output_dir.exists()
