import importlib.util
import csv
import io
import logging
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SYNC_PATH = Path(__file__).resolve().parent / "sync.py"
SPEC = importlib.util.spec_from_file_location("odoo_sync_script", SYNC_PATH)
SYNC = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SYNC
SPEC.loader.exec_module(SYNC)


class FakeRecordBase:
    def __init__(self, model_name, record_id, **values):
        self._name = model_name
        self.id = record_id
        for key, value in values.items():
            setattr(self, key, value)

    def exists(self):
        return self


class MissingFakeRecord(FakeRecordBase):
    def exists(self):
        return False


class FakeRecordSet(list):
    @property
    def ids(self):
        return [record.id for record in self]

    def sorted(self, key=None):
        return FakeRecordSet(sorted(list(self), key=key))

    def exists(self):
        return self

    def browse(self, ids):
        if isinstance(ids, int):
            ids = [ids]
        id_set = set(ids)
        return FakeRecordSet(record for record in self if record.id in id_set)

    def __getattr__(self, name):
        if len(self) == 1:
            return getattr(self[0], name)
        raise AttributeError(name)


class FakeIRModelDataRecord(FakeRecordBase):
    pass


class FakeIRModelDataModel:
    def __init__(self, records):
        self.records = records

    def search(self, domain, limit=None):
        results = self.records
        for field_name, operator, value in domain:
            if operator == "=":
                results = [record for record in results if getattr(record, field_name) == value]
            elif operator == "in":
                results = [record for record in results if getattr(record, field_name) in value]
            else:
                raise AssertionError(f"Unsupported operator: {operator}")
        if limit:
            results = results[:limit]
        return FakeRecordSet(results)


class FakeValueModel:
    def __init__(self, records):
        self.records = FakeRecordSet(records)
        self._fields = {
            "attribute_id": SimpleNamespace(type="many2one"),
            "name": SimpleNamespace(type="char"),
            "sequence": SimpleNamespace(type="integer"),
        }

    def search(self, domain):
        results = list(self.records)
        for field_name, operator, value in domain:
            if field_name == "attribute_id":
                accessor = lambda record: record.attribute_id.id
            else:
                accessor = lambda record, field_name=field_name: getattr(record, field_name)
            if operator == "=":
                results = [record for record in results if accessor(record) == value]
            elif operator == "!=":
                results = [record for record in results if accessor(record) != value]
            elif operator == "in":
                results = [record for record in results if accessor(record) in value]
            else:
                raise AssertionError(f"Unsupported operator: {operator}")
        return FakeRecordSet(results)

    def browse(self, ids):
        return self.records.browse(ids)


class FakeGenericModel:
    def __init__(self, records, field_types=None, defaults=None, table_objects=None):
        self.records = {record.id: record for record in records}
        self.defaults = defaults or {}
        self._table_objects = table_objects or {}
        self._fields = {}
        for field_name, field_type in (field_types or {}).items():
            if isinstance(field_type, str):
                self._fields[field_name] = SimpleNamespace(type=field_type)
            else:
                self._fields[field_name] = field_type

    def browse(self, record_id):
        return self.records[record_id]

    def search(self, domain):
        results = list(self.records.values())
        for field_name, operator, value in domain:
            def accessor(record, field_name=field_name):
                attr_value = getattr(record, field_name)
                if hasattr(attr_value, "id"):
                    return attr_value.id
                return attr_value

            if operator == "=":
                results = [record for record in results if accessor(record) == value]
            elif operator == "in":
                results = [record for record in results if accessor(record) in value]
            else:
                raise AssertionError(f"Unsupported operator: {operator}")
        return FakeRecordSet(results)

    def default_get(self, field_names):
        return {
            field_name: self.defaults[field_name]
            for field_name in field_names
            if field_name in self.defaults
        }


class FakeEnv(dict):
    def __init__(self, models, xmlid_map):
        super().__init__(models)
        self.xmlid_map = xmlid_map

    def ref(self, xml_id, raise_if_not_found=True):
        record = self.xmlid_map.get(xml_id)
        if record or not raise_if_not_found:
            return record
        raise KeyError(xml_id)


class FakeUniqueIndex:
    unique = True

    def __init__(self, definition):
        self.definition = definition

    def get_definition(self, registry=None):
        return f"UNIQUE INDEX {self.definition}"


def make_env():
    attribute = FakeRecordBase(
        "product.attribute",
        10,
        name="Test",
        sequence=1,
        hide_single_value_in_configurator=False,
        exclude_in_bulk_change=False,
        formula=False,
    )
    template = FakeRecordBase("product.template", 20)
    value_a = FakeRecordBase(
        "product.attribute.value",
        100,
        attribute_id=attribute,
        sequence=1,
        name="A",
    )
    value_b = FakeRecordBase(
        "product.attribute.value",
        101,
        attribute_id=attribute,
        sequence=2,
        name="B",
    )
    value_c = FakeRecordBase(
        "product.attribute.value",
        102,
        attribute_id=attribute,
        sequence=3,
        name="C",
    )
    line = FakeRecordBase(
        "product.template.attribute.line",
        200,
        product_tmpl_id=template,
        attribute_id=attribute,
        sequence=10,
        value_ids=FakeRecordSet([value_b, value_a]),
    )
    xmlid_map = {
        "ibcorr_stock.product_template_test": template,
        "ibcorr_stock.product_attribute_test": attribute,
        "ibcorr_stock.value_a": value_a,
        "ibcorr_stock.value_b": value_b,
        "ibcorr_stock.value_c": value_c,
        "ibcorr_stock.line_test": line,
    }
    ir_model_data_records = [
        FakeIRModelDataRecord(
            "ir.model.data",
            1,
            module="ibcorr_stock",
            name="line_test",
            model="product.template.attribute.line",
            res_id=line.id,
        ),
        FakeIRModelDataRecord(
            "ir.model.data",
            2,
            module="ibcorr_stock",
            name="product_template_test",
            model="product.template",
            res_id=template.id,
        ),
        FakeIRModelDataRecord(
            "ir.model.data",
            3,
            module="ibcorr_stock",
            name="product_attribute_test",
            model="product.attribute",
            res_id=attribute.id,
        ),
        FakeIRModelDataRecord(
            "ir.model.data",
            4,
            module="ibcorr_stock",
            name="value_a",
            model="product.attribute.value",
            res_id=value_a.id,
        ),
        FakeIRModelDataRecord(
            "ir.model.data",
            5,
            module="ibcorr_stock",
            name="value_b",
            model="product.attribute.value",
            res_id=value_b.id,
        ),
        FakeIRModelDataRecord(
            "ir.model.data",
            6,
            module="ibcorr_stock",
            name="value_c",
            model="product.attribute.value",
            res_id=value_c.id,
        ),
    ]
    models = {
        "ir.model.data": FakeIRModelDataModel(ir_model_data_records),
        "product.attribute.value": FakeValueModel([value_a, value_b, value_c]),
        "product.attribute": FakeGenericModel(
            [attribute],
            field_types={
                "sequence": "integer",
                "hide_single_value_in_configurator": "boolean",
                "exclude_in_bulk_change": "boolean",
                "formula": "char",
            },
        ),
        "product.template.attribute.line": FakeGenericModel(
            [line],
            field_types={
                "product_tmpl_id": "many2one",
                "attribute_id": "many2one",
                "sequence": "integer",
                "value_ids": "many2many",
            },
        ),
    }
    return FakeEnv(models, xmlid_map), line


class TestSyncPTAL(unittest.TestCase):
    def test_discover_project_model_fields_uses_target_module_dependency_closure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            for module_name in ("target_mod", "dep_mod", "unrelated_mod"):
                (project_root / module_name / "models").mkdir(parents=True)
            (project_root / "target_mod" / "__manifest__.py").write_text(
                "{'name': 'Target', 'depends': ['base', 'dep_mod']}",
                encoding="utf-8",
            )
            (project_root / "dep_mod" / "__manifest__.py").write_text(
                "{'name': 'Dependency', 'depends': ['base']}",
                encoding="utf-8",
            )
            (project_root / "unrelated_mod" / "__manifest__.py").write_text(
                "{'name': 'Unrelated', 'depends': ['base']}",
                encoding="utf-8",
            )
            (project_root / "target_mod" / "models" / "product_attribute.py").write_text(
                """
from odoo import fields, models

class ProductAttribute(models.Model):
    _inherit = "product.attribute"

    exclude_in_bulk_change = fields.Boolean()
""",
                encoding="utf-8",
            )
            (project_root / "dep_mod" / "models" / "product_attribute.py").write_text(
                """
from odoo import fields, models

class ProductAttribute(models.Model):
    _inherit = "product.attribute"

    dep_flag = fields.Boolean()
""",
                encoding="utf-8",
            )
            (project_root / "unrelated_mod" / "models" / "product_attribute.py").write_text(
                """
from odoo import fields, models

class ProductAttribute(models.Model):
    _inherit = "product.attribute"

    unrelated_flag = fields.Boolean()
""",
                encoding="utf-8",
            )

            model_fields = SYNC.discover_project_model_fields(project_root, "target_mod")

        self.assertEqual(
            model_fields["product.attribute"],
            {"exclude_in_bulk_change", "dep_flag"},
        )

    def test_resolve_model_filter_accepts_python_class_name(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            (project_root / "target_mod" / "models").mkdir(parents=True)
            (project_root / "target_mod" / "__manifest__.py").write_text(
                "{'name': 'Target', 'depends': ['base']}",
                encoding="utf-8",
            )
            (project_root / "target_mod" / "models" / "source_item_code_part.py").write_text(
                """
from odoo import fields, models

class SourceItemCodePart(models.Model):
    _name = "ibcorr.import.source.item.code.part"

    name = fields.Char()
""",
                encoding="utf-8",
            )

            project_models = SYNC.discover_project_models(project_root, "target_mod")

        self.assertEqual(
            SYNC.resolve_model_filter("SourceItemCodePart", set(), project_models),
            "ibcorr.import.source.item.code.part",
        )
        self.assertEqual(
            SYNC.resolve_model_filter("source_item_code_part", set(), project_models),
            "ibcorr.import.source.item.code.part",
        )

    def test_comparison_model_scope_uses_xml_models_without_filter(self):
        self.assertEqual(
            SYNC.comparison_model_scope({"parent.model", "other.model"}),
            {"parent.model", "other.model"},
        )

    def test_comparison_model_scope_includes_resolved_filter(self):
        self.assertEqual(
            SYNC.comparison_model_scope({"parent.model"}, "child.model"),
            {"parent.model", "child.model"},
        )

    def test_update_arg_parsing_supports_optional_success_limit(self):
        parser = SYNC.build_arg_parser()

        self.assertIs(
            parser.parse_args(["--module", "target_mod"]).update,
            False,
        )
        self.assertIsNone(
            parser.parse_args(["--module", "target_mod", "--update"]).update
        )
        self.assertEqual(
            parser.parse_args(["--module", "target_mod", "--update", "3"]).update,
            3,
        )

    def test_profile_arg_parsing_is_opt_in(self):
        parser = SYNC.build_arg_parser()

        self.assertFalse(parser.parse_args(["--module", "target_mod"]).profile)
        self.assertTrue(
            parser.parse_args(["--module", "target_mod", "--profile"]).profile
        )

    def test_profiler_disabled_produces_no_report(self):
        profiler = SYNC.SyncProfiler(False)

        with profiler.time("ignored timing"):
            profiler.count("ignored counter")

        self.assertEqual(profiler.format_report(), "")
        self.assertEqual(dict(profiler.timings), {})
        self.assertEqual(dict(profiler.counts), {})

    def test_profiler_enabled_records_timing_and_counter_report(self):
        profiler = SYNC.SyncProfiler(True)

        with profiler.time("test phase"):
            profiler.count("test counter", 2)

        report = profiler.format_report()
        self.assertIn("PROFILE", report)
        self.assertIn("test phase", report)
        self.assertIn("test counter", report)
        self.assertEqual(profiler.counts["test counter"], 2)
        self.assertIn("test phase", profiler.timings)

    def test_update_arg_parsing_rejects_non_positive_limit(self):
        parser = SYNC.build_arg_parser()

        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            parser.parse_args(["--module", "target_mod", "--update", "0"])

        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            parser.parse_args(["--module", "target_mod", "--update", "-1"])

    def test_update_requested_and_limit_helpers(self):
        self.assertFalse(SYNC.update_requested(False))
        self.assertTrue(SYNC.update_requested(None))
        self.assertTrue(SYNC.update_requested(5))
        self.assertIsNone(SYNC.update_limit_from_arg(False))
        self.assertIsNone(SYNC.update_limit_from_arg(None))
        self.assertEqual(SYNC.update_limit_from_arg(5), 5)

    def test_parse_csv_data_file_builds_source_records(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_path = Path(tmp_dir)
            csv_path = data_path / "product.attribute.csv"
            csv_path.write_text(
                "id,name,name@fr_FR,sequence\n"
                "product_attribute_test,Test,Essai,1\n",
                encoding="utf-8",
            )

            parser = SYNC.XMLDataParser(str(data_path), "ibcorr_stock")
            records = parser.parse_all_files()

        record = records["ibcorr_stock.product_attribute_test"]
        self.assertEqual(record["model"], "product.attribute")
        self.assertEqual(record["source_type"], "csv")
        self.assertEqual(record["fields"]["name"]["value"], "Test")
        self.assertEqual(record["fields"]["sequence"]["value"], "1")
        self.assertNotIn("name@fr_FR", record["fields"])

    def test_compare_csv_scalar_field_reports_difference(self):
        env, _line = make_env()
        xml_records = {
            "ibcorr_stock.product_attribute_test": {
                "xml_id": "product_attribute_test",
                "model": "product.attribute",
                "source_type": "csv",
                "file": "product.attribute.csv",
                "csv_row_index": 1,
                "fields": {
                    "sequence": {
                        "type": "value",
                        "value": "99",
                        "source_type": "csv",
                        "csv_header": "sequence",
                    }
                },
            }
        }
        comparator = SYNC.DatabaseComparator(
            env,
            "ibcorr_stock",
            project_model_fields={},
        )

        discrepancies = comparator.compare(xml_records, {"product.attribute"})

        self.assertEqual(len(discrepancies), 1)
        self.assertEqual(discrepancies[0].details["source_type"], "csv")
        self.assertEqual(discrepancies[0].field_differences["sequence"], (1, 99))

    def test_comparator_profiler_counts_natural_search_and_db_scan_paths(self):
        env, _line = make_env()
        profiler = SYNC.SyncProfiler(True)
        xml_records = {
            "ibcorr_stock.product_attribute_generated": {
                "xml_id": "product_attribute_generated",
                "model": "product.attribute",
                "source_type": "xml",
                "file": "attributes/test.xml",
                "fields": {
                    "name": {
                        "type": "value",
                        "value": "Test",
                    }
                },
            }
        }
        comparator = SYNC.DatabaseComparator(
            env,
            "ibcorr_stock",
            project_model_fields={},
            profiler=profiler,
        )

        comparator.compare(xml_records, {"product.attribute"})

        self.assertEqual(profiler.counts["XML records compared"], 1)
        self.assertGreaterEqual(profiler.counts["natural-key searches"], 1)
        self.assertGreaterEqual(profiler.counts["full-model DB scans"], 1)
        self.assertGreaterEqual(profiler.counts["DB records scanned"], 1)
        self.assertGreaterEqual(profiler.counts["ir.model.data lookups"], 1)

    def test_source_term_ptav_matches_by_unique_many2one_search_key(self):
        source_term = FakeRecordBase(
            "ibcorr.import.source.term",
            1,
            term="HH",
            term_to_use="HH",
        )
        template = FakeRecordBase("product.template", 2, name="Accessories")
        attribute = FakeRecordBase("product.attribute", 3, name="Type")
        attribute_value = FakeRecordBase(
            "product.attribute.value",
            4,
            attribute_id=attribute,
            name="Hex",
        )
        ptav = FakeRecordBase(
            "product.template.attribute.value",
            5,
            product_tmpl_id=template,
            attribute_id=attribute,
            product_attribute_value_id=attribute_value,
        )
        source_term_ptav = FakeRecordBase(
            "ibcorr.import.source.term.ptav",
            6,
            source_term_id=source_term,
            sequence=10,
            product_template_attribute_value_id=ptav,
        )
        env = FakeEnv(
            {
                "ir.model.data": FakeIRModelDataModel([]),
                "product.template.attribute.value": FakeGenericModel(
                    [ptav],
                    field_types={
                        "product_tmpl_id": "many2one",
                        "attribute_id": "many2one",
                        "product_attribute_value_id": "many2one",
                    },
                ),
                "ibcorr.import.source.term.ptav": FakeGenericModel(
                    [source_term_ptav],
                    field_types={
                        "source_term_id": "many2one",
                        "sequence": "integer",
                        "product_template_attribute_value_id": SimpleNamespace(
                            type="many2one",
                            comodel_name="product.template.attribute.value",
                        ),
                    },
                    table_objects={
                        "source_term_ptav_unique": FakeUniqueIndex(
                            "(source_term_id, product_template_attribute_value_id)"
                        )
                    },
                ),
            },
            {
                "ibcorr_import.source_term_hh": source_term,
                "ibcorr_stock.product_template_accessories": template,
                "ibcorr_stock.product_attribute_type": attribute,
                "ibcorr_stock.product_attribute_value_hex": attribute_value,
            },
        )
        comparator = SYNC.DatabaseComparator(
            env,
            "ibcorr_import",
            project_model_fields={},
        )

        discrepancies = comparator.compare(
            {
                "ibcorr_import.source_term_ptav_000001": {
                    "xml_id": "source_term_ptav_000001",
                    "model": "ibcorr.import.source.term.ptav",
                    "source_type": "xml",
                    "file": "source_term_ptavs.xml",
                    "fields": {
                        "source_term_id": {
                            "type": "ref",
                            "value": "ibcorr_import.source_term_hh",
                        },
                        "sequence": {"type": "value", "value": "10"},
                        "product_template_attribute_value_id": {
                            "type": "search",
                            "value": (
                                "[('product_tmpl_id', '=', "
                                "ref('ibcorr_stock.product_template_accessories')), "
                                "('attribute_id', '=', "
                                "ref('ibcorr_stock.product_attribute_type')), "
                                "('product_attribute_value_id', '=', "
                                "ref('ibcorr_stock.product_attribute_value_hex'))]"
                            ),
                        },
                    },
                }
            },
            {"ibcorr.import.source.term.ptav"},
        )

        self.assertEqual(discrepancies, [])

    def test_many2many_fields_are_not_used_for_natural_key_matching(self):
        tag = FakeRecordBase("custom.tag", 1, name="Tag")
        record = FakeRecordBase("custom.model", 2, tag_ids=FakeRecordSet([tag]))
        env = FakeEnv(
            {
                "ir.model.data": FakeIRModelDataModel([]),
                "custom.model": FakeGenericModel(
                    [record],
                    field_types={
                        "tag_ids": SimpleNamespace(
                            type="many2many",
                            comodel_name="custom.tag",
                        ),
                    },
                    table_objects={"tag_ids_unique": FakeUniqueIndex("(tag_ids)")},
                ),
            },
            {},
        )
        comparator = SYNC.DatabaseComparator(env, "target_mod", project_model_fields={})

        domains = comparator._natural_key_domains(
            "custom.model",
            {
                "tag_ids": {
                    "type": "eval",
                    "value": "[(6, 0, [1])]",
                }
            },
        )

        self.assertEqual(domains, [])

    def test_compare_csv_many2one_ref_matches_by_external_id(self):
        env, _line = make_env()
        xml_records = {
            "ibcorr_stock.value_a": {
                "xml_id": "value_a",
                "model": "product.attribute.value",
                "source_type": "csv",
                "file": "product.attribute.value.csv",
                "csv_row_index": 1,
                "fields": {
                    "name": {
                        "type": "value",
                        "value": "A",
                        "source_type": "csv",
                        "csv_header": "name",
                    },
                    "attribute_id": {
                        "type": "ref",
                        "value": "product_attribute_test",
                        "ref": "product_attribute_test",
                        "source_type": "csv",
                        "csv_header": "attribute_id/id",
                    },
                },
            }
        }
        comparator = SYNC.DatabaseComparator(
            env,
            "ibcorr_stock",
            project_model_fields={},
        )

        discrepancies = comparator.compare(xml_records, {"product.attribute.value"})

        self.assertFalse(
            [
                disc
                for disc in discrepancies
                if disc.discrepancy_type == SYNC.DiscrepancyType.FIELD_DIFFERENCE
            ]
        )

    def test_compare_csv_only_model_reports_untracked_db_records(self):
        env, _line = make_env()
        extra_attribute = FakeRecordBase(
            "product.attribute",
            11,
            name="Extra",
            sequence=2,
            hide_single_value_in_configurator=False,
            exclude_in_bulk_change=False,
            formula=False,
        )
        env["product.attribute"].records[extra_attribute.id] = extra_attribute
        xml_records = {
            "ibcorr_stock.product_attribute_test": {
                "xml_id": "product_attribute_test",
                "model": "product.attribute",
                "source_type": "csv",
                "file": "product.attribute.csv",
                "csv_row_index": 1,
                "fields": {
                    "name": {
                        "type": "value",
                        "value": "Test",
                        "source_type": "csv",
                        "csv_header": "name",
                    }
                },
            }
        }
        comparator = SYNC.DatabaseComparator(
            env,
            "ibcorr_stock",
            project_model_fields={},
        )

        discrepancies = comparator.compare(xml_records, {"product.attribute"})

        self.assertEqual(
            [disc.discrepancy_type for disc in discrepancies],
            [SYNC.DiscrepancyType.MISSING_IN_XML],
        )
        self.assertEqual(discrepancies[0].model, "product.attribute")
        self.assertEqual(discrepancies[0].details["source_type"], "csv")

    def test_update_existing_csv_scalar_field(self):
        env, _line = make_env()
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_path = Path(tmp_dir)
            csv_path = data_path / "product.attribute.csv"
            csv_path.write_text(
                "id,name,sequence\n"
                "product_attribute_test,Test,99\n",
                encoding="utf-8",
            )
            parser = SYNC.XMLDataParser(str(data_path), "ibcorr_stock")
            records = parser.parse_all_files()
            comparator = SYNC.DatabaseComparator(
                env,
                "ibcorr_stock",
                project_model_fields={},
            )
            discrepancies = comparator.compare(records, {"product.attribute"})
            resolver = SYNC.InteractiveResolver(
                str(data_path),
                "ibcorr_stock",
                env,
                xml_records=records,
            )

            changed = resolver._update_xml(discrepancies[0])

            with csv_path.open(encoding="utf-8", newline="") as csv_file:
                rows = list(csv.reader(csv_file))

        self.assertTrue(changed)
        self.assertEqual(rows[1], ["product_attribute_test", "Test", "1"])

    def test_update_existing_csv_many2one_ref_field(self):
        env, _line = make_env()
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_path = Path(tmp_dir)
            csv_path = data_path / "product.attribute.value.csv"
            csv_path.write_text(
                "id,name,attribute_id/id\n"
                "value_a,A,\n",
                encoding="utf-8",
            )
            parser = SYNC.XMLDataParser(str(data_path), "ibcorr_stock")
            records = parser.parse_all_files()
            comparator = SYNC.DatabaseComparator(
                env,
                "ibcorr_stock",
                project_model_fields={},
            )
            discrepancies = comparator.compare(records, {"product.attribute.value"})
            resolver = SYNC.InteractiveResolver(
                str(data_path),
                "ibcorr_stock",
                env,
                xml_records=records,
            )

            changed = resolver._update_xml(discrepancies[0])

            with csv_path.open(encoding="utf-8", newline="") as csv_file:
                rows = list(csv.reader(csv_file))

        self.assertTrue(changed)
        self.assertEqual(rows[1], ["value_a", "A", "ibcorr_stock.product_attribute_test"])

    def test_update_csv_missing_source_record_is_skipped(self):
        env, _line = make_env()
        resolver = SYNC.InteractiveResolver(
            "/tmp",
            "ibcorr_stock",
            env,
            xml_records={},
        )
        discrepancy = SYNC.Discrepancy(
            xml_id="ibcorr_stock.product_attribute_missing",
            model="product.attribute",
            discrepancy_type=SYNC.DiscrepancyType.MISSING_IN_XML,
            db_values={"res_id": 10},
            details={"source_type": "csv"},
        )
        output = io.StringIO()

        with redirect_stdout(output):
            changed = resolver._update_xml(discrepancy)

        self.assertFalse(changed)
        self.assertIn("CSV add/remove/rename is not supported", output.getvalue())

    def test_compare_attribute_custom_boolean_reports_missing_true_boolean(self):
        env, line = make_env()
        line.attribute_id.exclude_in_bulk_change = True

        discrepancies = self._compare_attribute(env)

        self.assertEqual(len(discrepancies), 1)
        self.assertEqual(
            discrepancies[0].field_differences["exclude_in_bulk_change"],
            (True, False),
        )

    def test_compare_attribute_custom_char_reports_missing_db_value(self):
        env, line = make_env()
        line.attribute_id.formula = "name"

        discrepancies = self._compare_attribute(env)

        self.assertEqual(len(discrepancies), 1)
        self.assertEqual(discrepancies[0].field_differences["formula"], ("name", None))

    def test_compare_missing_custom_integer_uses_model_default(self):
        record = FakeRecordBase("custom.model", 300, sequence=10)
        env = FakeEnv(
            {
                "ir.model.data": FakeIRModelDataModel(
                    [
                        FakeIRModelDataRecord(
                            "ir.model.data",
                            30,
                            module="target_mod",
                            name="record_test",
                            model="custom.model",
                            res_id=300,
                        )
                    ]
                ),
                "custom.model": FakeGenericModel(
                    [record],
                    field_types={"sequence": "integer"},
                    defaults={"sequence": 10},
                ),
            },
            {},
        )
        comparator = SYNC.DatabaseComparator(
            env,
            "target_mod",
            project_model_fields={"custom.model": {"sequence"}},
        )

        discrepancies = comparator.compare(
            {
                "target_mod.record_test": {
                    "model": "custom.model",
                    "fields": {},
                    "file": "data.xml",
                }
            },
            {"custom.model"},
        )

        self.assertEqual(discrepancies, [])

    def test_compare_omitted_one2many_is_ignored_by_default(self):
        child = FakeRecordBase("child.model", 401, name="Child")
        parent = FakeRecordBase(
            "parent.model",
            400,
            name="Parent",
            child_ids=FakeRecordSet([child]),
        )
        env = FakeEnv(
            {
                "ir.model.data": FakeIRModelDataModel(
                    [
                        FakeIRModelDataRecord(
                            "ir.model.data",
                            40,
                            module="target_mod",
                            name="parent_record",
                            model="parent.model",
                            res_id=parent.id,
                        )
                    ]
                ),
                "parent.model": FakeGenericModel(
                    [parent],
                    field_types={
                        "name": "char",
                        "child_ids": SimpleNamespace(
                            type="one2many",
                            comodel_name="child.model",
                        ),
                    },
                ),
                "child.model": FakeGenericModel([child], field_types={"name": "char"}),
            },
            {"target_mod.parent_record": parent},
        )
        comparator = SYNC.DatabaseComparator(
            env,
            "target_mod",
            project_model_fields={"parent.model": {"child_ids", "name"}},
        )

        discrepancies = comparator.compare(
            {
                "target_mod.parent_record": {
                    "model": "parent.model",
                    "fields": {"name": {"type": "value", "value": "Parent"}},
                    "file": "data.xml",
                }
            },
            {"parent.model"},
        )

        self.assertEqual(discrepancies, [])

    def test_compare_explicit_one2many_is_ignored(self):
        child = FakeRecordBase("child.model", 401, name="Child")
        parent = FakeRecordBase(
            "parent.model",
            400,
            name="Parent",
            child_ids=FakeRecordSet([child]),
        )
        env = FakeEnv(
            {
                "ir.model.data": FakeIRModelDataModel(
                    [
                        FakeIRModelDataRecord(
                            "ir.model.data",
                            40,
                            module="target_mod",
                            name="parent_record",
                            model="parent.model",
                            res_id=parent.id,
                        )
                    ]
                ),
                "parent.model": FakeGenericModel(
                    [parent],
                    field_types={
                        "name": "char",
                        "child_ids": SimpleNamespace(
                            type="one2many",
                            comodel_name="child.model",
                        ),
                    },
                ),
                "child.model": FakeGenericModel([child], field_types={"name": "char"}),
            },
            {"target_mod.parent_record": parent},
        )
        comparator = SYNC.DatabaseComparator(
            env,
            "target_mod",
            project_model_fields={"parent.model": {"child_ids", "name"}},
        )

        discrepancies = comparator.compare(
            {
                "target_mod.parent_record": {
                    "model": "parent.model",
                    "fields": {
                        "name": {"type": "value", "value": "Parent"},
                        "child_ids": {
                            "type": "value",
                            "value": "['child.model,999']",
                        },
                    },
                    "file": "data.xml",
                }
            },
            {"parent.model"},
        )

        self.assertEqual(discrepancies, [])

    def test_resolver_update_limit_counts_successful_updates_only(self):
        class CountingResolver(SYNC.InteractiveResolver):
            def __init__(self, outcomes):
                super().__init__("/tmp/data", "target_mod", {}, xml_records={})
                self.outcomes = list(outcomes)
                self.updated_ids = []

            def _update_xml(self, discrepancy):
                self.updated_ids.append(discrepancy.xml_id)
                return self.outcomes.pop(0)

        discrepancies = [
            SYNC.Discrepancy(
                xml_id=f"target_mod.record_{index}",
                model="custom.model",
                discrepancy_type=SYNC.DiscrepancyType.FIELD_DIFFERENCE,
                field_differences={"name": (f"DB {index}", f"XML {index}")},
            )
            for index in range(1, 5)
        ]
        resolver = CountingResolver([True, False, True, True])

        output = io.StringIO()
        with redirect_stdout(output):
            resolver.resolve(discrepancies, auto_action="update", update_limit=2)

        self.assertEqual(resolver.stats["updated"], 2)
        self.assertEqual(resolver.stats["total"], 3)
        self.assertEqual(
            resolver.updated_ids,
            ["target_mod.record_1", "target_mod.record_2", "target_mod.record_3"],
        )
        self.assertIn("Update limit reached: 2 successful source changes", output.getvalue())

    def test_resolver_flushes_xml_writes_in_batches_of_100(self):
        self.assertEqual(SYNC.InteractiveResolver.XML_FLUSH_INTERVAL, 100)

    def test_resolver_unlimited_update_keeps_processing_all_discrepancies(self):
        class CountingResolver(SYNC.InteractiveResolver):
            def __init__(self, outcomes):
                super().__init__("/tmp/data", "target_mod", {}, xml_records={})
                self.outcomes = list(outcomes)

            def _update_xml(self, discrepancy):
                return self.outcomes.pop(0)

        discrepancies = [
            SYNC.Discrepancy(
                xml_id=f"target_mod.record_{index}",
                model="custom.model",
                discrepancy_type=SYNC.DiscrepancyType.FIELD_DIFFERENCE,
                field_differences={"name": (f"DB {index}", f"XML {index}")},
            )
            for index in range(1, 4)
        ]
        resolver = CountingResolver([True, False, True])

        with redirect_stdout(io.StringIO()):
            resolver.resolve(discrepancies, auto_action="update")

        self.assertEqual(resolver.stats["updated"], 2)
        self.assertEqual(resolver.stats["total"], 3)

    def _compare_attribute(self, env, fields=None):
        comparator = SYNC.DatabaseComparator(
            env,
            "ibcorr_stock",
            project_model_fields={
                "product.attribute": {
                    "exclude_in_bulk_change",
                    "formula",
                    "hide_single_value_in_configurator",
                }
            },
        )
        xml_record = {
            "model": "product.attribute",
            "fields": fields or {},
            "file": "attributes/test.xml",
        }
        return comparator.compare(
            {"ibcorr_stock.product_attribute_test": xml_record},
            {"product.attribute"},
        )

    def test_compare_attribute_hidden_single_value_reports_missing_true_boolean(self):
        env, line = make_env()
        line.attribute_id.hide_single_value_in_configurator = True

        discrepancies = self._compare_attribute(env)

        self.assertEqual(len(discrepancies), 1)
        self.assertEqual(
            discrepancies[0].field_differences["hide_single_value_in_configurator"],
            (True, False),
        )

    def test_compare_attribute_hidden_single_value_omitted_false_is_synced(self):
        env, _line = make_env()

        discrepancies = self._compare_attribute(env)

        self.assertEqual(discrepancies, [])

    def test_compare_attribute_hidden_single_value_reports_eval_false_difference(self):
        env, line = make_env()
        line.attribute_id.hide_single_value_in_configurator = True

        discrepancies = self._compare_attribute(
            env,
            {
                "hide_single_value_in_configurator": {
                    "type": "eval",
                    "value": "False",
                },
            },
        )

        self.assertEqual(len(discrepancies), 1)
        self.assertEqual(
            discrepancies[0].field_differences["hide_single_value_in_configurator"],
            (True, False),
        )

    def test_compare_attribute_hidden_single_value_reports_eval_true_difference(self):
        env, _line = make_env()

        discrepancies = self._compare_attribute(
            env,
            {
                "hide_single_value_in_configurator": {
                    "type": "eval",
                    "value": "True",
                },
            },
        )

        self.assertEqual(len(discrepancies), 1)
        self.assertEqual(
            discrepancies[0].field_differences["hide_single_value_in_configurator"],
            (False, True),
        )

    def test_update_existing_xml_adds_missing_boolean_as_eval_true(self):
        env, _line = make_env()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            file_path = tmp_path / "attributes" / "test.xml"
            file_path.parent.mkdir(parents=True)
            file_path.write_text(
                """<?xml version='1.0' encoding='utf-8' ?>
<odoo>
    <record id="product_attribute_test" model="product.attribute">
        <field name="name">Test</field>
    </record>
</odoo>
""",
                encoding="utf-8",
            )
            resolver = SYNC.InteractiveResolver(str(tmp_path), "ibcorr_stock", env)
            discrepancy = SYNC.Discrepancy(
                xml_id="ibcorr_stock.product_attribute_test",
                model="product.attribute",
                discrepancy_type=SYNC.DiscrepancyType.FIELD_DIFFERENCE,
                field_differences={"hide_single_value_in_configurator": (True, False)},
                file_path="attributes/test.xml",
            )
            resolver._update_existing_xml(discrepancy)
            updated = file_path.read_text(encoding="utf-8")

        self.assertIn('name="hide_single_value_in_configurator" eval="True"', updated)

    def test_update_existing_xml_rewrites_boolean_as_eval_false(self):
        env, _line = make_env()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            file_path = tmp_path / "attributes" / "test.xml"
            file_path.parent.mkdir(parents=True)
            file_path.write_text(
                """<?xml version='1.0' encoding='utf-8' ?>
<odoo>
    <record id="product_attribute_test" model="product.attribute">
        <field name="hide_single_value_in_configurator" eval="True" />
    </record>
</odoo>
""",
                encoding="utf-8",
            )
            resolver = SYNC.InteractiveResolver(str(tmp_path), "ibcorr_stock", env)
            discrepancy = SYNC.Discrepancy(
                xml_id="ibcorr_stock.product_attribute_test",
                model="product.attribute",
                discrepancy_type=SYNC.DiscrepancyType.FIELD_DIFFERENCE,
                field_differences={"hide_single_value_in_configurator": (False, True)},
                file_path="attributes/test.xml",
            )
            resolver._update_existing_xml(discrepancy)
            updated = file_path.read_text(encoding="utf-8")

        self.assertIn('name="hide_single_value_in_configurator" eval="False"', updated)
        self.assertNotIn('>False</field>', updated)

    def test_compare_ptal_value_ids_ignores_order(self):
        env, _line = make_env()
        comparator = SYNC.DatabaseComparator(env, "ibcorr_stock")
        xml_record = {
            "model": "product.template.attribute.line",
            "fields": {
                "product_tmpl_id": {"type": "ref", "value": "ibcorr_stock.product_template_test"},
                "attribute_id": {"type": "ref", "value": "ibcorr_stock.product_attribute_test"},
                "sequence": {"type": "value", "value": "10"},
                "value_ids": {
                    "type": "eval",
                    "value": "[(6, 0, [ref('ibcorr_stock.value_a'), ref('ibcorr_stock.value_b')])]",
                },
            },
            "file": "template_attributes/test.xml",
        }
        with patch.object(SYNC.models, "Model", FakeRecordBase):
            discrepancies = comparator.compare(
                {"ibcorr_stock.line_test": xml_record},
                {"product.template.attribute.line"},
            )
        self.assertEqual(discrepancies, [])

    def test_compare_ptal_value_ids_reports_membership_difference(self):
        env, _line = make_env()
        comparator = SYNC.DatabaseComparator(env, "ibcorr_stock")
        xml_record = {
            "model": "product.template.attribute.line",
            "fields": {
                "product_tmpl_id": {"type": "ref", "value": "ibcorr_stock.product_template_test"},
                "attribute_id": {"type": "ref", "value": "ibcorr_stock.product_attribute_test"},
                "sequence": {"type": "value", "value": "10"},
                "value_ids": {
                    "type": "search",
                    "value": "[('attribute_id', '=', ref('ibcorr_stock.product_attribute_test')), ('id', '!=', ref('ibcorr_stock.value_b'))]",
                },
            },
            "file": "template_attributes/test.xml",
        }
        with patch.object(SYNC.models, "Model", FakeRecordBase):
            discrepancies = comparator.compare(
                {"ibcorr_stock.line_test": xml_record},
                {"product.template.attribute.line"},
            )
        self.assertEqual(len(discrepancies), 1)
        self.assertEqual(
            discrepancies[0].field_differences["value_ids"],
            (
                ["ibcorr_stock.value_a", "ibcorr_stock.value_b"],
                ["ibcorr_stock.value_a", "ibcorr_stock.value_c"],
            ),
        )

    def test_compare_ptal_search_ignores_matching_anonymous_db_values(self):
        env, line = make_env()
        value_a = line.value_ids[1]
        value_b = line.value_ids[0]
        anonymous_value = FakeRecordBase(
            "product.attribute.value",
            999,
            attribute_id=line.attribute_id,
            sequence=9,
            name="Anonymous",
        )
        env["product.attribute.value"].records = FakeRecordSet(
            [value_a, value_b, anonymous_value]
        )
        line.value_ids = FakeRecordSet([value_b, value_a, anonymous_value])
        comparator = SYNC.DatabaseComparator(env, "ibcorr_stock")
        xml_record = {
            "model": "product.template.attribute.line",
            "fields": {
                "product_tmpl_id": {"type": "ref", "value": "ibcorr_stock.product_template_test"},
                "attribute_id": {"type": "ref", "value": "ibcorr_stock.product_attribute_test"},
                "sequence": {"type": "value", "value": "10"},
                "value_ids": {
                    "type": "search",
                    "value": "[('attribute_id', '=', ref('ibcorr_stock.product_attribute_test'))]",
                },
            },
            "file": "template_attributes/test.xml",
        }
        with patch.object(SYNC.models, "Model", FakeRecordBase):
            discrepancies = comparator.compare(
                {"ibcorr_stock.line_test": xml_record},
                {"product.template.attribute.line"},
            )
        self.assertEqual(discrepancies, [])

    def test_compare_skips_missing_in_xml_when_ir_model_data_points_to_missing_record(self):
        env, _line = make_env()
        missing_value = MissingFakeRecord("product.attribute.value", 227, name="Missing")
        env["product.attribute.value"] = FakeGenericModel([missing_value])
        env["ir.model.data"].records.append(
            FakeIRModelDataRecord(
                "ir.model.data",
                99,
                module="ibcorr_stock",
                name="product_attribute_value_missing",
                model="product.attribute.value",
                res_id=227,
            )
        )
        comparator = SYNC.DatabaseComparator(env, "ibcorr_stock")
        with patch.object(SYNC.models, "Model", FakeRecordBase):
            discrepancies = comparator.compare({}, {"product.attribute.value"})
        self.assertEqual(discrepancies, [])

    def test_update_existing_xml_rewrites_ptal_value_ids_as_explicit_eval(self):
        env, line = make_env()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            file_path = tmp_path / "template_attributes" / "test.xml"
            file_path.parent.mkdir(parents=True)
            file_path.write_text(
                """<?xml version='1.0' encoding='utf-8' ?>
<odoo>
    <record id="line_test" model="product.template.attribute.line">
        <field name="product_tmpl_id" ref="ibcorr_stock.product_template_test" />
        <field name="attribute_id" ref="ibcorr_stock.product_attribute_test" />
        <field name="sequence">10</field>
        <field name="value_ids" search="[('attribute_id', '=', ref('ibcorr_stock.product_attribute_test'))]" />
    </record>
</odoo>
""",
                encoding="utf-8",
            )
            resolver = SYNC.InteractiveResolver(
                str(tmp_path),
                "ibcorr_stock",
                env,
                xml_records={
                    "ibcorr_stock.line_test": {
                        "model": "product.template.attribute.line",
                        "file": "template_attributes/test.xml",
                        "fields": {
                            "product_tmpl_id": {
                                "type": "ref",
                                "value": "ibcorr_stock.product_template_test",
                            },
                        },
                    }
                },
            )
            discrepancy = SYNC.Discrepancy(
                xml_id="ibcorr_stock.line_test",
                model="product.template.attribute.line",
                discrepancy_type=SYNC.DiscrepancyType.FIELD_DIFFERENCE,
                db_values={"value_ids": line.value_ids},
                field_differences={"value_ids": (["ibcorr_stock.value_a"], ["ibcorr_stock.value_b"])},
                file_path="template_attributes/test.xml",
            )
            with patch.object(SYNC.models, "Model", FakeRecordBase):
                resolver._update_existing_xml(discrepancy)
            updated = file_path.read_text(encoding="utf-8")
        self.assertNotIn("search=", updated)
        self.assertIn('eval="[(6, 0, [ref(', updated)
        self.assertIn("ref('ibcorr_stock.value_a')", updated)
        self.assertIn("ref('ibcorr_stock.value_b')", updated)

    def test_determine_target_file_reuses_sibling_ptal_file(self):
        env, _line = make_env()
        resolver = SYNC.InteractiveResolver(
            "/tmp/data",
            "ibcorr_stock",
            env,
            xml_records={
                "ibcorr_stock.existing_line": {
                    "model": "product.template.attribute.line",
                    "file": "template_attributes/roof_sheet_attributes.xml",
                    "fields": {
                        "product_tmpl_id": {
                            "type": "ref",
                            "value": "ibcorr_stock.product_template_test",
                        },
                    },
                }
            },
        )
        discrepancy = SYNC.Discrepancy(
            xml_id="ibcorr_stock.line_test",
            model="product.template.attribute.line",
            discrepancy_type=SYNC.DiscrepancyType.MISSING_IN_XML,
            db_values={"res_id": 200},
        )
        with patch.object(SYNC.models, "Model", FakeRecordBase):
            target_file = resolver._determine_target_file(discrepancy.model, discrepancy)
        self.assertEqual(
            target_file,
            "template_attributes/roof_sheet_attributes.xml",
        )

    def test_update_existing_xml_refuses_ptal_values_without_xml_id(self):
        env, line = make_env()
        orphan_value = FakeRecordBase(
            "product.attribute.value",
            999,
            attribute_id=line.attribute_id,
            sequence=9,
            name="Orphan",
        )
        line.value_ids = FakeRecordSet([orphan_value])
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            file_path = tmp_path / "template_attributes" / "test.xml"
            file_path.parent.mkdir(parents=True)
            file_path.write_text(
                """<?xml version='1.0' encoding='utf-8' ?>
<odoo>
    <record id="line_test" model="product.template.attribute.line">
        <field name="product_tmpl_id" ref="ibcorr_stock.product_template_test" />
        <field name="attribute_id" ref="ibcorr_stock.product_attribute_test" />
        <field name="sequence">10</field>
        <field name="value_ids" search="[('attribute_id', '=', ref('ibcorr_stock.product_attribute_test'))]" />
    </record>
</odoo>
""",
                encoding="utf-8",
            )
            resolver = SYNC.InteractiveResolver(
                str(tmp_path),
                "ibcorr_stock",
                env,
                xml_records={},
            )
            discrepancy = SYNC.Discrepancy(
                xml_id="ibcorr_stock.line_test",
                model="product.template.attribute.line",
                discrepancy_type=SYNC.DiscrepancyType.FIELD_DIFFERENCE,
                db_values={"value_ids": line.value_ids},
                field_differences={"value_ids": ([], [])},
                file_path="template_attributes/test.xml",
            )
            original = file_path.read_text(encoding="utf-8")
            output = io.StringIO()
            with patch.object(SYNC.models, "Model", FakeRecordBase):
                with redirect_stdout(output):
                    resolver._update_existing_xml(discrepancy)
            self.assertIn("Cannot update", output.getvalue())
            self.assertEqual(file_path.read_text(encoding="utf-8"), original)

    def test_detail_report_formats_collection_diffs_without_wide_table(self):
        discrepancy = SYNC.Discrepancy(
            xml_id="ibcorr_stock.line_roofsheet_material",
            model="product.template.attribute.line",
            discrepancy_type=SYNC.DiscrepancyType.FIELD_DIFFERENCE,
            field_differences={
                "value_ids": (
                    [
                        "ibcorr_stock.product_attribute_value_aluzinc",
                        "ibcorr_stock.product_attribute_value_colorbond",
                    ],
                    [
                        "ibcorr_stock.product_attribute_value_aluminium",
                        "ibcorr_stock.product_attribute_value_aluzinc",
                        "ibcorr_stock.product_attribute_value_colorbond",
                    ],
                )
            },
        )
        report = SYNC.format_report_text([discrepancy])
        self.assertIn("Only in Source", report)
        self.assertIn("ibcorr_stock.product_attribute_value_aluminium", report)
        self.assertNotIn("┌", report)
        self.assertNotIn("│ Field ", report)

    def test_resolve_uses_compact_diff_output_and_counts_only_successful_updates(self):
        env, line = make_env()
        orphan_value = FakeRecordBase(
            "product.attribute.value",
            999,
            attribute_id=line.attribute_id,
            sequence=9,
            name="Orphan",
        )
        line.value_ids = FakeRecordSet([orphan_value])
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            file_path = tmp_path / "template_attributes" / "test.xml"
            file_path.parent.mkdir(parents=True)
            file_path.write_text(
                """<?xml version='1.0' encoding='utf-8' ?>
<odoo>
    <record id="line_test" model="product.template.attribute.line">
        <field name="product_tmpl_id" ref="ibcorr_stock.product_template_test" />
        <field name="attribute_id" ref="ibcorr_stock.product_attribute_test" />
        <field name="sequence">10</field>
        <field name="value_ids" search="[('attribute_id', '=', ref('ibcorr_stock.product_attribute_test'))]" />
    </record>
</odoo>
""",
                encoding="utf-8",
            )
            resolver = SYNC.InteractiveResolver(
                str(tmp_path),
                "ibcorr_stock",
                env,
                xml_records={},
            )
            discrepancies = [
                SYNC.Discrepancy(
                    xml_id="ibcorr_stock.line_test",
                    model="product.template.attribute.line",
                    discrepancy_type=SYNC.DiscrepancyType.FIELD_DIFFERENCE,
                    db_values={"value_ids": line.value_ids},
                    field_differences={"value_ids": (["product.attribute.value,999"], [])},
                    file_path="template_attributes/test.xml",
                ),
                SYNC.Discrepancy(
                    xml_id="ibcorr_stock.line_missing",
                    model="product.template.attribute.line",
                    discrepancy_type=SYNC.DiscrepancyType.MISSING_IN_DB,
                    file_path="template_attributes/test.xml",
                ),
            ]
            output = io.StringIO()
            with patch.object(SYNC.models, "Model", FakeRecordBase):
                with redirect_stdout(output):
                    resolver.resolve(discrepancies, auto_action="update")
            rendered = output.getvalue()
            self.assertIn("Only in DB", rendered)
            self.assertNotIn("┌", rendered)
            self.assertIn("Source changes applied:    0", rendered)

    def test_detail_report_renders_one_table_row_per_collection_issue(self):
        discrepancy = SYNC.Discrepancy(
            xml_id="ibcorr_stock.line_test",
            model="product.template.attribute.line",
            discrepancy_type=SYNC.DiscrepancyType.FIELD_DIFFERENCE,
            field_differences={
                "value_ids": (
                    ["ibcorr_stock.value_a", "ibcorr_stock.value_b"],
                    ["ibcorr_stock.value_a", "ibcorr_stock.value_c"],
                )
            },
        )

        report = SYNC.format_report_text([discrepancy])

        self.assertIn("Model", report)
        self.assertIn("Source State", report)
        self.assertIn("DB State", report)
        self.assertIn("Only in Source", report)
        self.assertIn("Only in DB", report)
        self.assertIn("ibcorr_stock.value_b", report)
        self.assertIn("ibcorr_stock.value_c", report)
        self.assertNotIn("Field differences:", report)
        self.assertNotIn("┌", report)

    def test_compare_xml_record_with_natural_db_match_is_synced(self):
        env, _line = make_env()
        env["ir.model.data"].records = [
            record
            for record in env["ir.model.data"].records
            if record.name != "product_attribute_test"
        ]
        comparator = SYNC.DatabaseComparator(env, "ibcorr_stock")

        discrepancies = comparator.compare(
            {
                "ibcorr_stock.legacy_attribute_test": {
                    "xml_id": "legacy_attribute_test",
                    "model": "product.attribute",
                    "fields": {"name": {"type": "value", "value": "Test"}},
                    "file": "attributes/test.xml",
                }
            },
            {"product.attribute"},
        )

        self.assertEqual(discrepancies, [])

    def test_compare_discovers_untracked_records_for_any_xml_model(self):
        existing = FakeRecordBase("custom.model", 300, name="Existing")
        new = FakeRecordBase("custom.model", 301, name="New")
        env = FakeEnv(
            {
                "ir.model.data": FakeIRModelDataModel(
                    [
                        FakeIRModelDataRecord(
                            "ir.model.data",
                            30,
                            module="target_mod",
                            name="record_existing",
                            model="custom.model",
                            res_id=existing.id,
                        )
                    ]
                ),
                "custom.model": FakeGenericModel(
                    [existing, new],
                    field_types={"name": "char"},
                ),
            },
            {"target_mod.record_existing": existing},
        )
        comparator = SYNC.DatabaseComparator(env, "target_mod")

        discrepancies = comparator.compare(
            {
                "target_mod.record_existing": {
                    "xml_id": "record_existing",
                    "model": "custom.model",
                    "fields": {"name": {"type": "value", "value": "Existing"}},
                    "file": "data.xml",
                }
            },
            {"custom.model"},
        )

        missing_xml = [
            discrepancy
            for discrepancy in discrepancies
            if discrepancy.discrepancy_type == SYNC.DiscrepancyType.MISSING_IN_XML
        ]
        self.assertEqual(len(missing_xml), 1)
        self.assertEqual(missing_xml[0].db_values["res_id"], new.id)
        self.assertEqual(missing_xml[0].xml_id, "target_mod.custom_model_new")

    def test_compare_discovers_untracked_records_for_requested_model_without_xml_records(self):
        generated = FakeRecordBase("generated.child.model", 301, name="Generated")
        env = FakeEnv(
            {
                "ir.model.data": FakeIRModelDataModel([]),
                "generated.child.model": FakeGenericModel(
                    [generated],
                    field_types={"name": "char"},
                ),
            },
            {},
        )
        comparator = SYNC.DatabaseComparator(env, "target_mod")

        discrepancies = comparator.compare({}, {"generated.child.model"})

        self.assertEqual(len(discrepancies), 1)
        self.assertEqual(
            discrepancies[0].discrepancy_type,
            SYNC.DiscrepancyType.MISSING_IN_XML,
        )
        self.assertEqual(discrepancies[0].db_values["res_id"], generated.id)
        self.assertEqual(
            discrepancies[0].xml_id,
            "target_mod.generated_child_model_generated",
        )

    def test_compare_skips_untracked_record_with_xml_id_from_other_module(self):
        existing = FakeRecordBase("custom.model", 300, name="Existing")
        external = FakeRecordBase("custom.model", 301, name="External")
        env = FakeEnv(
            {
                "ir.model.data": FakeIRModelDataModel(
                    [
                        FakeIRModelDataRecord(
                            "ir.model.data",
                            30,
                            module="target_mod",
                            name="record_existing",
                            model="custom.model",
                            res_id=existing.id,
                        ),
                        FakeIRModelDataRecord(
                            "ir.model.data",
                            31,
                            module="base",
                            name="record_external",
                            model="custom.model",
                            res_id=external.id,
                        ),
                    ]
                ),
                "custom.model": FakeGenericModel(
                    [existing, external],
                    field_types={"name": "char"},
                ),
            },
            {
                "target_mod.record_existing": existing,
                "base.record_external": external,
            },
        )
        comparator = SYNC.DatabaseComparator(env, "target_mod")

        discrepancies = comparator.compare(
            {
                "target_mod.record_existing": {
                    "xml_id": "record_existing",
                    "model": "custom.model",
                    "fields": {"name": {"type": "value", "value": "Existing"}},
                    "file": "data.xml",
                }
            },
            {"custom.model"},
        )

        missing_ids = {
            discrepancy.db_values.get("res_id")
            for discrepancy in discrepancies
            if discrepancy.discrepancy_type == SYNC.DiscrepancyType.MISSING_IN_XML
        }
        self.assertNotIn(external.id, missing_ids)

    def test_compare_natural_key_match_without_xml_id_is_synced(self):
        existing = FakeRecordBase("custom.model", 300, name="Existing")
        env = FakeEnv(
            {
                "ir.model.data": FakeIRModelDataModel([]),
                "custom.model": FakeGenericModel(
                    [existing],
                    field_types={"name": "char"},
                ),
            },
            {},
        )
        comparator = SYNC.DatabaseComparator(env, "target_mod")

        discrepancies = comparator.compare(
            {
                "target_mod.legacy_existing": {
                    "xml_id": "legacy_existing",
                    "model": "custom.model",
                    "fields": {"name": {"type": "value", "value": "Existing"}},
                    "file": "data.xml",
                }
            },
            {"custom.model"},
        )

        self.assertEqual(discrepancies, [])

    def test_compare_discovers_untracked_attribute_values_in_xml_scope(self):
        env, line = make_env()
        orphan_value = FakeRecordBase(
            "product.attribute.value",
            999,
            attribute_id=line.attribute_id,
            sequence=9,
            name="Orphan",
        )
        env["product.attribute.value"].records.append(orphan_value)
        comparator = SYNC.DatabaseComparator(env, "ibcorr_stock")

        discrepancies = comparator.compare(
            {
                "ibcorr_stock.product_attribute_test": {
                    "xml_id": "product_attribute_test",
                    "model": "product.attribute",
                    "fields": {"name": {"type": "value", "value": "Test"}},
                    "file": "attributes/test.xml",
                }
            },
            {"product.attribute", "product.attribute.value"},
        )

        missing_xml = [
            discrepancy
            for discrepancy in discrepancies
            if discrepancy.discrepancy_type == SYNC.DiscrepancyType.MISSING_IN_XML
        ]
        orphan_discrepancies = [
            discrepancy
            for discrepancy in missing_xml
            if discrepancy.db_values["res_id"] == 999
        ]
        self.assertEqual(len(orphan_discrepancies), 1)
        self.assertEqual(
            orphan_discrepancies[0].xml_id,
            "ibcorr_stock.product_attribute_value_test_orphan",
        )

    def test_resolver_serializes_generated_dependency_refs_without_db_writes(self):
        env, line = make_env()
        orphan_value = FakeRecordBase(
            "product.attribute.value",
            999,
            attribute_id=line.attribute_id,
            sequence=9,
            name="Orphan",
        )
        line.value_ids = FakeRecordSet([orphan_value])
        env["product.attribute.value"].records.append(orphan_value)
        resolver = SYNC.InteractiveResolver("/tmp/data", "ibcorr_stock", env)
        value_discrepancy = SYNC.Discrepancy(
            xml_id="ibcorr_stock.product_attribute_value_test_orphan",
            model="product.attribute.value",
            discrepancy_type=SYNC.DiscrepancyType.MISSING_IN_XML,
            db_values={"res_id": 999},
            details={
                "generated_xml_id": "ibcorr_stock.product_attribute_value_test_orphan",
            },
        )
        line_discrepancy = SYNC.Discrepancy(
            xml_id="ibcorr_stock.line_test",
            model="product.template.attribute.line",
            discrepancy_type=SYNC.DiscrepancyType.MISSING_IN_XML,
            db_values={"res_id": line.id},
        )

        with patch.object(SYNC.models, "Model", FakeRecordBase):
            resolver._prepare_generated_xml_ids([value_discrepancy, line_discrepancy])
            xml = resolver._generate_ptal_record_xml(line_discrepancy, line)

        self.assertIn("ref('ibcorr_stock.product_attribute_value_test_orphan')", xml)

    def test_resolver_places_generic_missing_record_in_existing_model_file(self):
        env, _line = make_env()
        resolver = SYNC.InteractiveResolver(
            "/tmp/data",
            "target_mod",
            env,
            xml_records={
                "target_mod.custom_a": {
                    "model": "custom.model",
                    "file": "data/custom.xml",
                },
                "target_mod.custom_b": {
                    "model": "custom.model",
                    "file": "data/custom.xml",
                },
                "target_mod.custom_c": {
                    "model": "custom.model",
                    "file": "data/other.xml",
                },
            },
        )

        self.assertEqual(
            resolver._determine_target_file("custom.model"),
            "data/custom.xml",
        )

    def test_update_xml_removes_duplicate_xml_record_without_reference_check(self):
        env, _line = make_env()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            file_path = tmp_path / "attributes" / "test.xml"
            file_path.parent.mkdir(parents=True)
            file_path.write_text(
                """<?xml version='1.0' encoding='utf-8' ?>
<odoo>
    <record id="value_duplicate" model="product.attribute.value">
        <field name="name">Original</field>
    </record>
    <record id="value_duplicate" model="product.attribute.value">
        <field name="name">Duplicate</field>
    </record>
    <record id="dependent_line" model="product.template.attribute.line">
        <field name="value_ids" eval="[(6, 0, [ref('value_duplicate')])]"/>
    </record>
</odoo>
""",
                encoding="utf-8",
            )
            resolver = SYNC.InteractiveResolver(str(tmp_path), "ibcorr_stock", env)
            discrepancy = SYNC.Discrepancy(
                xml_id="ibcorr_stock.value_duplicate",
                model="product.attribute.value",
                discrepancy_type=SYNC.DiscrepancyType.DUPLICATE_IN_XML,
                file_path="attributes/test.xml",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                changed = resolver._update_xml(discrepancy)
            updated = file_path.read_text(encoding="utf-8")

        self.assertTrue(changed)
        self.assertIn("Original", updated)
        self.assertNotIn("Duplicate", updated)
        self.assertIn("dependent_line", updated)

    def test_update_xml_removes_xml_only_record(self):
        env, _line = make_env()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            file_path = tmp_path / "attributes" / "test.xml"
            file_path.parent.mkdir(parents=True)
            file_path.write_text(
                """<?xml version='1.0' encoding='utf-8' ?>
<odoo>
    <record id="value_xml_only" model="product.attribute.value">
        <field name="name">XML Only</field>
    </record>
    <record id="value_kept" model="product.attribute.value">
        <field name="name">Kept</field>
    </record>
</odoo>
""",
                encoding="utf-8",
            )
            resolver = SYNC.InteractiveResolver(
                str(tmp_path),
                "ibcorr_stock",
                env,
                xml_records={
                    "ibcorr_stock.value_xml_only": {
                        "model": "product.attribute.value",
                        "file": "attributes/test.xml",
                        "fields": {"name": {"type": "value", "value": "XML Only"}},
                    },
                    "ibcorr_stock.value_kept": {
                        "model": "product.attribute.value",
                        "file": "attributes/test.xml",
                        "fields": {"name": {"type": "value", "value": "Kept"}},
                    },
                },
            )
            discrepancy = SYNC.Discrepancy(
                xml_id="ibcorr_stock.value_xml_only",
                model="product.attribute.value",
                discrepancy_type=SYNC.DiscrepancyType.MISSING_IN_DB,
                file_path="attributes/test.xml",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                resolver.resolve([discrepancy], auto_action="update")
            updated = file_path.read_text(encoding="utf-8")
        self.assertNotIn("value_xml_only", updated)
        self.assertIn("value_kept", updated)
        self.assertIn("[Update XML] Removing source-only XML record", output.getvalue())
        self.assertIn("Source changes applied:    1", output.getvalue())

    def test_update_xml_blocks_removing_referenced_xml_only_record(self):
        env, _line = make_env()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            file_path = tmp_path / "attributes" / "test.xml"
            file_path.parent.mkdir(parents=True)
            file_path.write_text(
                """<?xml version='1.0' encoding='utf-8' ?>
<odoo>
    <record id="value_xml_only" model="product.attribute.value">
        <field name="name">XML Only</field>
    </record>
    <record id="dependent_line" model="product.template.attribute.line">
        <field name="value_ids" eval="[(6, 0, [ref('value_xml_only')])]"/>
    </record>
</odoo>
""",
                encoding="utf-8",
            )
            original = file_path.read_text(encoding="utf-8")
            resolver = SYNC.InteractiveResolver(
                str(tmp_path),
                "ibcorr_stock",
                env,
                xml_records={
                    "ibcorr_stock.value_xml_only": {
                        "model": "product.attribute.value",
                        "file": "attributes/test.xml",
                        "fields": {"name": {"type": "value", "value": "XML Only"}},
                    },
                    "ibcorr_stock.dependent_line": {
                        "model": "product.template.attribute.line",
                        "file": "attributes/test.xml",
                        "fields": {
                            "value_ids": {
                                "type": "eval",
                                "value": "[(6, 0, [ref('value_xml_only')])]",
                                "eval": "[(6, 0, [ref('value_xml_only')])]",
                            }
                        },
                    },
                },
            )
            discrepancy = SYNC.Discrepancy(
                xml_id="ibcorr_stock.value_xml_only",
                model="product.attribute.value",
                discrepancy_type=SYNC.DiscrepancyType.MISSING_IN_DB,
                file_path="attributes/test.xml",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                changed = resolver._update_xml(discrepancy)
            current = file_path.read_text(encoding="utf-8")
        self.assertFalse(changed)
        self.assertEqual(current, original)
        self.assertIn("referenced by XML records", output.getvalue())
        self.assertIn("ibcorr_stock.dependent_line.value_ids", output.getvalue())

    def test_source_xml_id_lookup_uses_index_for_source_segments(self):
        segment_model = "ibcorr.import.source.code.segment"
        segment = FakeRecordBase(segment_model, 500, position=1, source_token="ABC")
        env = FakeEnv(
            {
                "ir.model.data": FakeIRModelDataModel([]),
                segment_model: FakeGenericModel(
                    [segment],
                    field_types={"position": "integer", "source_token": "char"},
                ),
            },
            {},
        )
        resolver = SYNC.InteractiveResolver(
            "/tmp",
            "target_mod",
            env,
            xml_records={
                "target_mod.source_code_segment_1_abc": {
                    "xml_id": "source_code_segment_1_abc",
                    "model": segment_model,
                    "file": "source_code_segments.xml",
                    "fields": {
                        "position": {"type": "value", "value": "1"},
                        "source_token": {"type": "value", "value": "ABC"},
                    },
                }
            },
        )

        with patch.object(
            resolver,
            "_xml_record_matches_db_record",
            side_effect=AssertionError("fallback scan should not run"),
        ):
            xml_id = resolver._get_xml_id_for_record(segment)

        self.assertEqual(xml_id, "target_mod.source_code_segment_1_abc")

    def test_configure_quiet_odoo_logging_suppresses_schema_warnings(self):
        logging.getLogger("odoo.schema").setLevel(logging.WARNING)
        SYNC._configure_quiet_odoo_logging()
        self.assertEqual(logging.getLogger("odoo.schema").level, logging.ERROR)


if __name__ == "__main__":
    unittest.main()
