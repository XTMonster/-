"""计划 v4 的 R9：**判据执行环境在重建期间逐字节不动**。

为什么需要这条守门（而不是靠"我记得没改"）：本项目已经有过两次
"判据被悄悄挪走而一切照绿"的现场——

* 往 `QUALIFIER_KINDS` 加一个 qualifier，缓存键**不动**，于是新槽位从未被抽取
  （S0 修的就是这个洞，`ACCEPTANCE_STATUS.md §九十八`）；
* `tools/sidecar_server.py` 手抄了一份 trace 字面量，S1a 新加的键在降级部署里
  根本不存在（`53d3e3f` 的提交信息原文："sidecar 手抄的那份已经漂了"）。

计划 v4 要重建的是**知识产物**（语料／抽取实现／检索实现／缓存键），
**不是**测量仪器。所以仪器的 sha256 冻在 `tests/plan_v4_instruments.sha256.json` 里：
改了它就当场红，要过就得**单独提交**一次显式的重新冻结，并把理由写进那个文件的
`_frozen_at` / `_reason`——这正是"任何涉判据的变动只能以待裁决单列、经用户明示批准"
在机器上的形态。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FREEZE_FILE = ROOT / "tests" / "plan_v4_instruments.sha256.json"


def load_freeze() -> dict:
    return json.loads(FREEZE_FILE.read_text(encoding="utf-8"))


def instrument_hash(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def test_the_freeze_file_names_only_files_that_exist():
    frozen = load_freeze()["instruments"]
    missing = [name for name in frozen if not (ROOT / name).is_file()]
    assert missing == [], "冻结清单里点了不存在的文件：%s" % missing


@pytest.mark.parametrize("relative", sorted(load_freeze()["instruments"]))
def test_instrument_is_byte_identical_to_the_frozen_hash(relative):
    frozen = load_freeze()["instruments"][relative]
    actual = instrument_hash(relative)
    assert actual == frozen["sha256"], (
        "%s 与计划 v4 冻结的哈希不一致。\n"
        "  它守的是：%s\n"
        "  若这次改动是**有意的**（例如用户批准的判据演进），"
        "请单独提交一次重新冻结，并在 tests/plan_v4_instruments.sha256.json 里"
        "更新 _frozen_at 与 _reason；否则请撤回这次改动。"
        % (relative, frozen.get("guards", "(未注明)")))


def test_the_freeze_file_records_when_and_why():
    """冻结必须有时间与理由——否则它就成了"某次快照"，没人能审。"""
    payload = load_freeze()
    assert payload.get("_frozen_at"), "缺少 _frozen_at"
    assert payload.get("_reason"), "缺少 _reason"
    for name, entry in payload["instruments"].items():
        assert len(entry.get("sha256", "")) == 64, name
        assert entry.get("guards"), name


def test_the_guard_has_teeth_a_synthetic_change_turns_it_red(tmp_path):
    """反面控制：把副本改一个字节 ⇒ 哈希必须变（证明这条断言不是恒真式）。"""
    sample = tmp_path / "instrument.py"
    sample.write_bytes(b"x = 1\n")
    before = hashlib.sha256(sample.read_bytes()).hexdigest()
    sample.write_bytes(b"x = 2\n")
    after = hashlib.sha256(sample.read_bytes()).hexdigest()
    assert before != after
