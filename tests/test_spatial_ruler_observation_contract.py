"""空间尺观测扩展契约测试（.scratch/spatial-ruler-json/）。

覆盖：
1. schema 与样例 JSON 可解析、样例通过 jsonschema 校验；
2. 契约语义：来源四态、verdict 数值对、处方 allow-list、前后置引用闭合；
3. 插件审核映射完整性：integration 映射 ↔ contracts/rule_catalog.py 对拍；
4. 诚实接入状态：integration_status 不得冒充 full（准备层语义）。
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from block_director.contracts.rule_catalog import RULES


ROOT = Path(__file__).resolve().parents[1]
RULER_DIR = ROOT / "block_director" / "contracts" / "spatial_ruler"

SCHEMA = RULER_DIR / "schema" / "spatial-ruler-observation.v1.schema.json"
CONTRACT_V1 = RULER_DIR / "contract.v1.json"
CONTRACT_V2 = RULER_DIR / "contract.v2.json"
EXAMPLE = RULER_DIR / "examples" / "dock-market-observation.v2.json"
MAPPING = RULER_DIR / "integration" / "plugin-audit-mapping.v1.json"


def _load(path: Path):
    assert path.exists(), f"缺少契约文件：{path}"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema() -> dict:
    return _load(SCHEMA)


@pytest.fixture(scope="module")
def example() -> dict:
    return _load(EXAMPLE)


@pytest.fixture(scope="module")
def mapping() -> dict:
    return _load(MAPPING)


def test_all_json_files_parse() -> None:
    for path in [SCHEMA, CONTRACT_V1, CONTRACT_V2, EXAMPLE, MAPPING]:
        assert isinstance(_load(path), dict), f"{path.name} 不是 JSON 对象"


def test_example_validates_against_schema(schema: dict, example: dict) -> None:
    jsonschema.validate(instance=example, schema=schema)


def test_contract_v2_validates_against_schema(schema: dict) -> None:
    contract = _load(CONTRACT_V2)
    jsonschema.validate(instance=contract, schema=schema)


def test_observation_chain_references_close(example: dict) -> None:
    """观测链路：verdict.evidence 与 prescription 引用的 measurement_id 必须存在。"""
    measurement_ids = {m["measurement_id"] for m in example["measurements"]}
    assert measurement_ids, "样例至少要有一条 measurement"
    for verdict in example["verdicts"]:
        for ref in verdict["evidence"]:
            assert ref in measurement_ids, (
                f"{verdict['verdict_id']} 引用了不存在的测量 {ref}")
    for prescription in example["prescriptions"]:
        for ref in (prescription["precondition_measurement_ids"]
                    + prescription["postcondition_measurement_ids"]):
            assert ref in measurement_ids, (
                f"{prescription['prescription_id']} 引用了不存在的测量 {ref}")


def test_provenance_closed_set(example: dict) -> None:
    allowed = {"script_declaration", "plan_intent",
               "algorithmic_measurement", "blender_geometry"}
    for camera in example["camera_specs"]:
        assert camera["source"] in allowed, f"{camera['shot_id']} 来源非法"
    for measurement in example["measurements"]:
        assert measurement["source"] in allowed, f"{measurement['measurement_id']} 来源非法"
        assert measurement["provenance"] in allowed, f"{measurement['measurement_id']} provenance 非法"
        assert measurement["source"] == measurement["provenance"]


def test_verdicts_carry_numeric_pairs(example: dict) -> None:
    """每个 verdict 必须带 expected/actual/threshold/unit（可空值显式出现）。"""
    for verdict in example["verdicts"]:
        assert "expected" in verdict, f"{verdict['verdict_id']} 缺 expected"
        assert "actual" in verdict, f"{verdict['verdict_id']} 缺 actual"
        assert "threshold" in verdict, f"{verdict['verdict_id']} 缺 threshold"
        assert "unit" in verdict, f"{verdict['verdict_id']} 缺 unit"


def test_prescription_operations_are_allow_listed(example: dict) -> None:
    allowed = {"retime_shot", "restore_cast", "reframe", "move_character",
               "change_camera_side", "review_transition"}
    for prescription in example["prescriptions"]:
        assert prescription["operation"] in allowed


def test_registry_covers_rule_catalog(mapping: dict) -> None:
    """插件审核映射必须覆盖 rule_catalog 的全部 R 规则（枚举对拍）。"""
    contract = _load(CONTRACT_V2)
    registry_rules = set(contract["registry"]["rules"])
    catalog_ids = {str(item["id"]) for item in RULES}
    missing_in_registry = catalog_ids - registry_rules
    assert not missing_in_registry, f"registry 缺规则：{sorted(missing_in_registry)}"


def test_mapping_covers_rule_catalog(mapping: dict) -> None:
    mapped = {item["audit_rule"] for item in mapping["mappings"]}
    catalog_ids = {str(item["id"]) for item in RULES}
    missing = catalog_ids - mapped
    assert not missing, f"mapping 缺规则：{sorted(missing)}"


def test_mapping_is_not_overclaiming_integration(mapping: dict, example: dict) -> None:
    """准备层语义：映射与样例都不得冒充 full 接入。"""
    assert mapping["integration_status"] == "partial_plan_level_only"
    assert example["plugin_adapter"]["integration_status"] == "partial_plan_level_only"
    assert example["plugin_adapter"]["consumer"] == "BlockDirector.audit"


def test_example_does_not_replace_existing_artifacts(example: dict) -> None:
    """样例必须声明其依赖的真实运行证据路径（不替代 audit_log / script_compliance）。"""
    source_run = Path(example["run_context"]["source_run"])
    assert (source_run / "runs" / "audit_log.jsonl").exists(), \
        "样例引用的真实审计日志必须存在"
    assert (source_run / "export" / "script_compliance.json").exists(), \
        "样例引用的 script_compliance.json 必须存在"


def test_example_angle_thresholds_are_30_not_40(example: dict) -> None:
    """用户点名的角度口径：当前实现全部是 30°，契约不得引入 40°。"""
    registry = example["registry"]["rules"]
    assert registry["R010"]["min_angle_deg"] == 30.0
    assert registry["R001"]["axis_drift_deg"] == 30.0
    assert registry["R021"]["move_heading_turn_deg"] == 30.0
    assert example["registry"]["guard"]["jump_cut_angle_deg"] == 30.0
    text = json.dumps(example, ensure_ascii=False)
    assert "40.0" not in text and "40°" not in text
