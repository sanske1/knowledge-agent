"""
双文件夹归档全链路测试
"""
import os
import sys
import json
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest.mock import patch, MagicMock
from AIchat.deal_files import (
    process_inbox, rebuild_index, validate_index, list_failed,
)
from AIchat.deal_files.config import INBOX_DIR, ARCHIVED_DIR, FAILED_DIR
from AIchat.deal_files.storage import Storage


def _mock_llm_invoke(messages):
    """Mock LLM：根据 prompt 内容返回合理的 JSON"""
    content = messages[0]["content"]
    # AI 文件摘要
    if "摘要" in content and "keywords" in content and "项目" not in content[:50]:
        return type("R", (), {"content": json.dumps({
            "summary": "这是一份测试文档的摘要。",
            "keywords": ["测试", "文档"],
            "content_type": "测试文档",
        })})()
    # 项目摘要
    if "项目" in content and "themes" in content:
        return type("R", (), {"content": json.dumps({
            "summary": "项目总览：包含若干测试文档。",
            "themes": ["测试", "文档"],
            "doc_list": ["doc1"],
        })})()
    # AI 聚类
    if "聚类" in content:
        return type("R", (), {"content": json.dumps({"零散测试": [0, 1]})})()
    return type("R", (), {"content": "{}"})()


def _make_mock_llm():
    mock = MagicMock()
    mock.invoke.side_effect = _mock_llm_invoke
    return mock


def setup_test_files():
    """准备测试文件"""
    # 清理旧数据
    for d in [INBOX_DIR, ARCHIVED_DIR]:
        if os.path.exists(d):
            shutil.rmtree(d)
    # 清空 MySQL 主存
    from AIchat.deal_files.storage import Storage
    s = Storage()
    s.index.clear_all()
    s.close()

    # 创建项目文件夹 + 文件
    proj_dir = os.path.join(INBOX_DIR, "项目方案")
    os.makedirs(proj_dir, exist_ok=True)
    with open(os.path.join(proj_dir, "需求文档.txt"), "w", encoding="utf-8") as f:
        f.write("这是项目方案中的需求文档内容。\n包含多个段落用于测试分片功能。\n" * 20)

    # 根目录零散文件
    with open(os.path.join(INBOX_DIR, "员工手册.txt"), "w", encoding="utf-8") as f:
        f.write("员工手册内容：公司规章制度、考勤制度、福利待遇等。\n" * 10)
    with open(os.path.join(INBOX_DIR, "财务报表.txt"), "w", encoding="utf-8") as f:
        f.write("财务报表内容：资产负债表、利润表、现金流量表等。\n" * 10)

    print(f"[setup] 测试文件已创建:")
    print(f"  未处理/项目方案/需求文档.txt")
    print(f"  未处理/员工手册.txt")
    print(f"  未处理/财务报表.txt")


def test_process_inbox():
    print("\n" + "=" * 60)
    print("测试 1: process_inbox 全流程")
    print("=" * 60)

    with patch("AIchat.deal_files.AIsavefile.llm_model", _make_mock_llm()):
        report = process_inbox()
    print(f"\n处理报告: {report.to_dict()}")

    # 验证：已处理区存在
    assert os.path.exists(ARCHIVED_DIR), "已处理文件夹不存在"

    # 验证：项目方案目录 + 原始文件 + .meta.json
    proj_archived = os.path.join(ARCHIVED_DIR, "项目方案")
    assert os.path.exists(proj_archived), "已处理/项目方案 不存在"
    assert os.path.exists(os.path.join(proj_archived, "需求文档.txt")), "原始文件未归档"
    assert os.path.exists(os.path.join(proj_archived, "需求文档.txt.meta.json")), ".meta.json 未生成"

    # 验证：.meta.json 内容
    with open(os.path.join(proj_archived, "需求文档.txt.meta.json"), "r", encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["filename"] == "需求文档.txt"
    assert meta["summary"]
    assert isinstance(meta["keywords"], list)
    assert isinstance(meta["chunks"], list) and len(meta["chunks"]) > 0
    assert meta["index_version"]
    assert meta["index_pending"] is False
    print("  ✅ .meta.json 内容正确")

    # 验证：未处理区已清理
    inbox_files = []
    for entry in os.listdir(INBOX_DIR):
        full = os.path.join(INBOX_DIR, entry)
        if os.path.isfile(full):
            inbox_files.append(entry)
    assert len(inbox_files) == 0, f"未处理区未清理干净，剩余: {inbox_files}"
    print("  ✅ 未处理区已清理")

    # 验证：索引中有对应文件
    storage = Storage()
    files = storage.index.list_files()
    storage.close()
    filenames = {f.filename for f in files}
    assert "需求文档.txt" in filenames, "索引中缺少需求文档"
    assert "员工手册.txt" in filenames, "索引中缺少员工手册"
    assert "财务报表.txt" in filenames, "索引中缺少财务报表"
    print(f"  ✅ 索引包含 {len(files)} 个文件")

    print("  ✅ process_inbox 测试通过")


def test_rebuild_index():
    print("\n" + "=" * 60)
    print("测试 2: rebuild_index 全量重建")
    print("=" * 60)

    with patch("AIchat.deal_files.AIsavefile.llm_model", _make_mock_llm()):
        result = rebuild_index()
    print(f"重建结果: {result}")

    # 验证索引仍然完整
    storage = Storage()
    files = storage.index.list_files()
    projects = storage.index.list_projects()
    storage.close()

    assert len(files) == 3, f"重建后文件数应为3，实际{len(files)}"
    assert len(projects) >= 1, "重建后项目数应>=1"
    print(f"  ✅ 重建后: {len(projects)} 项目, {len(files)} 文件")

    print("  ✅ rebuild_index 测试通过")


def test_validate_index():
    print("\n" + "=" * 60)
    print("测试 3: validate_index 校验")
    print("=" * 60)

    result = validate_index()
    print(f"校验结果: {result}")
    assert result.get("consistent", False) is True, "索引应与已处理区一致"
    print("  ✅ validate_index 测试通过")


def test_idempotent():
    print("\n" + "=" * 60)
    print("测试 4: 幂等去重（重复文件跳过）")
    print("=" * 60)

    # 从已处理区复制回未处理区（保留 mtime，使 fingerprint 一致）
    proj_dir = os.path.join(INBOX_DIR, "项目方案")
    os.makedirs(proj_dir, exist_ok=True)
    src = os.path.join(ARCHIVED_DIR, "项目方案", "需求文档.txt")
    shutil.copy2(src, os.path.join(proj_dir, "需求文档.txt"))

    with patch("AIchat.deal_files.AIsavefile.llm_model", _make_mock_llm()):
        report = process_inbox()
    print(f"处理报告: {report.to_dict()}")

    assert report.skipped >= 1, "应至少跳过1个重复文件"
    assert report.archived == 0, "重复文件不应归档"
    print("  ✅ 幂等去重测试通过")


def test_failure_handling():
    print("\n" + "=" * 60)
    print("测试 5: 失败处理（无效文件移入 .failed）")
    print("=" * 60)

    # 创建一个无效文件（空内容或无法解析）
    with open(os.path.join(INBOX_DIR, "损坏文件.xyz"), "w", encoding="utf-8") as f:
        f.write("\x00\x01\x02binary garbage")

    with patch("AIchat.deal_files.AIsavefile.llm_model", _make_mock_llm()):
        report = process_inbox()
    print(f"处理报告: {report.to_dict()}")

    # 损坏文件应被移入 .failed
    failed = list_failed()
    failed_names = {f["filename"] for f in failed}
    print(f"  .failed 目录文件: {failed_names}")
    assert "损坏文件.xyz" in failed_names, "损坏文件应移入 .failed"
    print("  ✅ 失败处理测试通过")


if __name__ == "__main__":
    setup_test_files()
    test_process_inbox()
    test_rebuild_index()
    test_validate_index()
    test_idempotent()
    test_failure_handling()
    print("\n" + "=" * 60)
    print("🎉 全部测试通过！")
    print("=" * 60)
