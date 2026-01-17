"""Base extractor class for Odoo components."""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from odoo_client import OdooClient

try:
    from .file_manager import FileManager
except ImportError:
    from file_manager import FileManager


@dataclass
class ExtractionResult:
    """Result of an extraction operation."""

    extractor_name: str
    model: str
    record_count: int
    records: list[dict[str, Any]]
    output_file: str
    extracted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    dry_run: bool = True
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "extractor": self.extractor_name,
            "model": self.model,
            "record_count": self.record_count,
            "extracted_at": self.extracted_at,
            "dry_run": self.dry_run,
            "output_file": self.output_file,
            "records": self.records,
            "errors": self.errors,
        }


try:
    from ..interfaces import ExtractorInterface
except ImportError:
    try:
        from interfaces import ExtractorInterface
    except ImportError:
        # Create a dummy interface to avoid ABC duplication
        class ExtractorInterface:
            pass


class BaseExtractor(ExtractorInterface):
    """Base class for Odoo component extractors.

    All extractors follow a common pattern:
    1. Build domain filter for Studio customizations
    2. Query Odoo for matching records
    3. Transform/enrich the data
    4. Output to JSON file (if not dry-run)
    """

    # Subclasses must define these
    name: str = ""
    model: str = ""
    output_filename: str = ""

    # Default fields to extract (subclasses can override)
    default_fields: list[str] = ["id", "name", "display_name"]

    @property
    def name(self) -> str:
        """Extractor name."""
        return self.__class__.name

    def __init__(
        self,
        client: "OdooClient",
        output_dir: Path,
        dry_run: bool = True,
    ):
        """Initialize extractor.

        Args:
            client: Authenticated Odoo client
            output_dir: Directory for extraction output
            dry_run: If True, do not write files
        """
        self.client = client
        self.output_dir = output_dir
        self.dry_run = dry_run
        self.file_manager = FileManager(output_dir.parent)
        self._errors: list[str] = []

    @abstractmethod
    def get_domain(
        self, base_filters: list[list[Any]] | None = None
    ) -> list[Any]:
        """Build the search domain for this extractor.

        Args:
            base_filters: Additional filters from config

        Returns:
            Odoo search domain
        """
        pass

    @abstractmethod
    def get_fields(self) -> list[str]:
        """Get list of fields to extract.

        Returns:
            List of field names
        """
        pass

    def transform_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Transform a record after extraction.

        Override in subclasses for custom transformation.

        Args:
            record: Raw record from Odoo

        Returns:
            Transformed record
        """
        return record

    def extract(
        self,
        base_filters: list[list[Any]] | None = None,
    ) -> ExtractionResult:
        """Extract records from Odoo.

        Args:
            base_filters: Additional filters from config

        Returns:
            ExtractionResult with extracted data
        """
        domain = self.get_domain(base_filters)
        fields = self.get_fields()

        try:
            records = self.client.search_read(
                model=self.model,
                domain=domain,
                fields=fields,
            )
        except Exception as e:
            self._errors.append(f"Query failed: {e}")
            records = []

        # Transform records
        transformed = []
        for record in records:
            try:
                transformed.append(self.transform_record(record))
            except Exception as e:
                self._errors.append(
                    f"Transform failed for record {record.get('id')}: {e}"
                )
                transformed.append(record)

        result = ExtractionResult(
            extractor_name=self.name,
            model=self.model,
            record_count=len(transformed),
            records=transformed,
            output_file=self.output_filename,
            dry_run=self.dry_run,
            errors=self._errors.copy(),
        )

        if not self.dry_run:
            self._write_output(result)

        return result

    def _write_output(self, result: ExtractionResult) -> Path:
        """Write extraction result to JSON file.

        Args:
            result: Extraction result to write

        Returns:
            Path to written file
        """
        self.file_manager.ensure_directory(self.output_dir)
        output_path = self.output_dir / self.output_filename

        content = json.dumps(result.to_dict(), indent=2, default=str)
        self.file_manager.write_text(output_path, content)

        return output_path
