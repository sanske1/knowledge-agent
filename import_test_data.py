# -*- coding: utf-8 -*-
"""
Redis 业务测试数据导入脚本
前置：pip install redis
执行：python import_test_data.py
已适配：flushdb之后全新导入，无残留key
"""
import redis
import json

# ==================== Redis 连接配置 ====================
REDIS_CONFIG = {
    'host': 'localhost',
    'port': 6379,
    'decode_responses': True,
    'db': 0,
}

r = redis.Redis(**REDIS_CONFIG)

# ==================== 业务数据集 ====================
customers = {
    1: {"customer_name": "贵州黔西恒通建材", "contact_phone": "13800138001",
        "city": "毕节黔西", "industry": "建筑材料", "register_date": "2024-01-15", "customer_level": "VIP"},
    2: {"customer_name": "贵阳科创软件有限公司", "contact_phone": "13800138002",
        "city": "贵阳", "industry": "软件IT", "register_date": "2024-02-20", "customer_level": "普通"},
    3: {"customer_name": "毕节民生商贸", "contact_phone": "13800138003",
        "city": "毕节七星关", "industry": "零售商贸", "register_date": "2024-03-10", "customer_level": "VIP"},
    4: {"customer_name": "六盘水鑫源矿业", "contact_phone": "13800138004",
        "city": "六盘水", "industry": "矿产", "register_date": "2024-04-05", "customer_level": "普通"},
    5: {"customer_name": "遵义绿源农业合作社", "contact_phone": "13800138005",
        "city": "遵义", "industry": "农业", "register_date": "2024-05-12", "customer_level": "普通"},
    6: {"customer_name": "黔东南锦绣文旅", "contact_phone": "13800138006",
        "city": "凯里", "industry": "文旅", "register_date": "2024-06-08", "customer_level": "VIP"},
}

orders = {
    1: {"customer_id": "1", "order_amount": "12800.00", "order_time": "2025-08-10 09:20:00",
        "order_status": "已完成", "product_name": "水泥批量供货"},
    2: {"customer_id": "1", "order_amount": "5600.00", "order_time": "2025-09-02 14:10:00",
        "order_status": "待付款", "product_name": "砂石料"},
    3: {"customer_id": "2", "order_amount": "25000.00", "order_time": "2025-07-15 10:30:00",
        "order_status": "已完成", "product_name": "企业ERP软件"},
    4: {"customer_id": "3", "order_amount": "3200.00", "order_time": "2025-09-01 11:00:00",
        "order_status": "已完成", "product_name": "日用商品采购"},
    5: {"customer_id": "4", "order_amount": "45000.00", "order_time": "2025-06-20 16:40:00",
        "order_status": "已完成", "product_name": "矿山设备配件"},
    6: {"customer_id": "5", "order_amount": "8900.00", "order_time": "2025-08-22 08:15:00",
        "order_status": "待发货", "product_name": "有机肥原料"},
    7: {"customer_id": "6", "order_amount": "18600.00", "order_time": "2025-09-05 15:25:00",
        "order_status": "已完成", "product_name": "景区票务系统"},
}

employees = {
    1: {"emp_name": "张三", "department": "销售部", "post": "销售经理", "salary": "9500.00", "entry_date": "2023-05-08"},
    2: {"emp_name": "李四", "department": "技术部", "post": "开发工程师", "salary": "11200.00", "entry_date": "2023-06-12"},
    3: {"emp_name": "王五", "department": "财务部", "post": "会计", "salary": "7800.00", "entry_date": "2023-08-20"},
    4: {"emp_name": "赵六", "department": "销售部", "post": "销售专员", "salary": "6200.00", "entry_date": "2024-01-10"},
    5: {"emp_name": "陈七", "department": "运维部", "post": "运维工程师", "salary": "8600.00", "entry_date": "2024-02-18"},
    6: {"emp_name": "周八", "department": "市场部", "post": "市场专员", "salary": "5800.00", "entry_date": "2024-03-01"},
}


def import_customers():
    """导入客户hash"""
    for cid, fields in customers.items():
        r.hset(f"customer:{cid}", mapping=fields)
        print(f"  ✅ customer:{cid}  {fields['customer_name']}")


def import_orders():
    """导入订单hash"""
    for oid, fields in orders.items():
        r.hset(f"order:{oid}", mapping=fields)
        print(f"  ✅ order:{oid}  {fields['product_name']}")


def import_employees():
    """导入员工hash"""
    for eid, fields in employees.items():
        r.hset(f"emp:{eid}", mapping=fields)
        print(f"  ✅ emp:{eid}  {fields['emp_name']}")


def build_index():
    """建立索引集合set"""
    # 客户城市索引
    city_map = {
        "毕节黔西": [1],
        "贵阳": [2],
        "毕节七星关": [3],
        "六盘水": [4],
        "遵义": [5],
        "凯里": [6],
    }
    for city, ids in city_map.items():
        r.sadd(f"idx:customer:city:{city}", *[str(i) for i in ids])

    # 客户等级索引
    r.sadd("idx:customer:level:VIP", "1", "3", "6")
    r.sadd("idx:customer:level:普通", "2", "4", "5")

    # 员工部门索引
    dept_map = {
        "销售部": [1, 4],
        "技术部": [2],
        "财务部": [3],
        "运维部": [5],
        "市场部": [6],
    }
    for dept, ids in dept_map.items():
        r.sadd(f"idx:emp:department:{dept}", *[str(i) for i in ids])
    print("  ✅ 全部索引集合创建完成")


def verify_data():
    """校验导入结果"""
    print("\n================ 数据校验 ================")
    c_count = len(r.keys("customer:*"))
    o_count = len(r.keys("order:*"))
    e_count = len(r.keys("emp:*"))
    print(f"客户总数: {c_count}")
    print(f"订单总数: {o_count}")
    print(f"员工总数: {e_count}")

    print("\n毕节地区客户校验：")
    ids_qianxi = r.smembers("idx:customer:city:毕节黔西")
    ids_qixingguan = r.smembers("idx:customer:city:毕节七星关")
    all_bj_ids = ids_qianxi.union(ids_qixingguan)
    for cid in sorted(all_bj_ids, key=int):
        data = r.hgetall(f"customer:{cid}")
        print(f"    customer:{cid} | {data['customer_name']}, {data['city']}")


if __name__ == "__main__":
    try:
        r.ping()
        print(f"✅ Redis连接成功 {REDIS_CONFIG['host']}:{REDIS_CONFIG['port']}\n")
    except Exception as err:
        print(f"❌ Redis连接失败：{err}")
        exit(1)

    print("开始导入客户数据：")
    import_customers()
    print("\n开始导入订单数据：")
    import_orders()
    print("\n开始导入员工数据：")
    import_employees()
    print("\n构建索引：")
    build_index()

    verify_data()
    print("\n🎉 数据导入全部完成！")
