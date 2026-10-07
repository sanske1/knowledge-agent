# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, ".")
from AIchat.deal_files.storage import Storage

storage = Storage()
try:
    projects = storage.index.list_projects()
    deleted = []
    for p in projects:
        files = storage.index.get_files_by_project(p.project_id)
        if len(files) == 0:
            # 空项目：删除项目及其残留分片
            print(f"删除空项目: '{p.name}' (id={p.project_id})")
            storage.index.delete_project(p.project_id)
            # 清理 Redis 向量索引
            try:
                vs = storage.get_vector_store(p.project_id)
                # 尝试删除整个索引
                try:
                    vs._index.delete(vs._index.name)
                except Exception:
                    pass
            except Exception:
                pass
            deleted.append(p.name)

    print(f"\n已删除 {len(deleted)} 个空项目:")
    for name in deleted:
        print(f"  - {name}")

    # 验证清理后状态
    print("\n=== 清理后项目列表 ===")
    projects = storage.index.list_projects()
    name_count = {}
    for p in projects:
        files = storage.index.get_files_by_project(p.project_id)
        name_count[p.name] = name_count.get(p.name, 0) + 1
        print(f"  {p.name} (id={p.project_id[:8]}..., 文件={len(files)})")

    dupes = {n: c for n, c in name_count.items() if c > 1}
    if dupes:
        print(f"\n仍有重复项目: {dupes}")
    else:
        print("\n✅ 无重复项目")

finally:
    storage.close()
