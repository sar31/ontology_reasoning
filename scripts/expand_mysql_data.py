"""MySQL data expansion script with realistic world data."""
import os
import random
import datetime
import pymysql
import pymysql.cursors

DB_CFG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "benti"),
    "charset": "utf8mb4",
}
random.seed(42)

# Realistic data pools
COUNTRIES = list(range(1, 37))

REAL_PERSONS = [
    ("安东诺夫·谢尔盖", "Antonov Sergey", 2, "military_commander", "上将"),
    ("约翰逊·马修", "Johnson Matthew", 1, "intelligence_officer", "中将"),
    ("陈卫国", "Chen Weiguo", 3, "military_commander", "少将"),
    ("阿里·哈桑", "Ali Hassan", 4, "political_leader", None),
    ("让·皮埃尔", "Jean Pierre", 5, "diplomat", "大使"),
    ("汉斯·穆勒", "Hans Mueller", 6, "military_commander", "准将"),
    ("佐藤健一", "Sato Kenichi", 7, "intelligence_officer", "上校"),
    ("拉吉夫·库马尔", "Rajiv Kumar", 8, "military_commander", "少将"),
    ("朴正熙", "Park Junghee", 9, "political_leader", None),
    ("阮文雄", "Nguyen Van Hung", 10, "military_commander", "上校"),
]

REAL_ORGS = [
    ("美国国防部", "Department of Defense", 1, "government", "DoD"),
    ("俄罗斯联邦武装力量", "Russian Armed Forces", 2, "military", "RAF"),
    ("中国人民解放军", "PLA", 3, "military", "PLA"),
    ("英国军情六处", "MI6", 4, "intelligence", "MI6"),
    ("法国对外安全总局", "DGSE", 5, "intelligence", "DGSE"),
    ("德国联邦情报局", "BND", 6, "intelligence", "BND"),
    ("以色列摩萨德", "Mossad", 11, "intelligence", "Mossad"),
    ("伊朗革命卫队", "IRGC", 12, "military", "IRGC"),
    ("朝鲜人民军", "KPA", 9, "military", "KPA"),
    ("印度陆军", "Indian Army", 8, "military", "IA"),
]

REAL_EQUIPMENT = [
    ("F-35A Lightning II", "aircraft", "fighter", 1),
    ("Su-57 Felon", "aircraft", "fighter", 2),
    ("歼-20 威龙", "aircraft", "fighter", 3),
    ("台风 FGR4", "aircraft", "fighter", 4),
    ("阵风 B", "aircraft", "fighter", 5),
    ("B-2 Spirit", "aircraft", "bomber", 1),
    ("图-160 海盗旗", "aircraft", "bomber", 2),
    ("轰-6K", "aircraft", "bomber", 3),
    ("E-3 哨兵", "aircraft", "awacs", 1),
    ("空警-500", "aircraft", "awacs", 3),
    ("MQ-9 Reaper", "drone", "ucav", 1),
    ("翼龙-2", "drone", "ucav", 3),
    ("福特级航母", "naval_vessel", "carrier", 1),
    ("库兹涅佐夫号", "naval_vessel", "carrier", 2),
    ("福建舰", "naval_vessel", "carrier", 3),
    ("阿利伯克级", "naval_vessel", "destroyer", 1),
    ("055型驱逐舰", "naval_vessel", "destroyer", 3),
    ("弗吉尼亚级", "naval_vessel", "submarine", 1),
    ("北风之神级", "naval_vessel", "submarine", 2),
    ("094型核潜艇", "naval_vessel", "submarine", 3),
    ("M1A2 SEPv3", "ground_vehicle", "tank", 1),
    ("T-90M", "ground_vehicle", "tank", 2),
    ("99A主战坦克", "ground_vehicle", "tank", 3),
    ("豹2A7", "ground_vehicle", "tank", 6),
    ("海马斯火箭炮", "artillery", "mlrs", 1),
    ("PHL-191", "artillery", "mlrs", 3),
    ("东风-21D", "missile", "ballistic", 3),
    ("东风-26", "missile", "ballistic", 3),
    ("匕首导弹", "missile", "hypersonic", 2),
    ("锆石导弹", "missile", "hypersonic", 2),
    ("战斧Block V", "missile", "cruise", 1),
    ("口径导弹", "missile", "cruise", 2),
    ("S-400防空系统", "missile", "defense", 2),
    ("萨德THAAD", "missile", "defense", 1),
    ("红旗-9B", "missile", "defense", 3),
    ("爱国者PAC-3", "missile", "defense", 1),
]

REAL_FACILITIES = [
    ("关塔那摩湾海军基地", "naval_base", 1, 19.9, -75.2),
    ("塞瓦斯托波尔海军基地", "naval_base", 2, 44.6, 33.5),
    ("青岛核潜艇基地", "naval_base", 3, 36.0, 120.3),
    ("诺福克海军基地", "naval_base", 1, 36.9, -76.3),
    ("安德森空军基地", "air_base", 1, 13.5, 144.9),
    ("嘉手纳空军基地", "air_base", 7, 26.3, 127.7),
    ("乌山空军基地", "air_base", 9, 37.0, 127.0),
    ("关岛海军基地", "naval_base", 1, 13.4, 144.8),
    ("迪戈加西亚基地", "naval_base", 4, -7.3, 72.4),
    ("苏比克湾海军基地", "naval_base", 10, 14.8, 120.2),
    ("横须贺海军基地", "naval_base", 7, 35.2, 139.6),
    ("佐世保海军基地", "naval_base", 7, 33.1, 129.7),
    ("樟宜海军基地", "naval_base", 28, 1.3, 103.9),
    ("达尔文港军事基地", "naval_base", 26, -12.4, 130.8),
    ("金兰湾军事基地", "naval_base", 10, 12.0, 109.2),
]


def get_conn():
    return pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB_CFG)


def main():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            tables = ["persons", "organizations", "equipments", "facilities", "events"]
            counts = {t: 0 for t in tables}
            max_ids = {t: 0 for t in tables}
            for t in tables:
                cur.execute(f"SELECT COUNT(*) AS c, COALESCE(MAX(id),0) AS m FROM `{t}`")
                r = cur.fetchone()
                counts[t] = r["c"]
                max_ids[t] = r["m"]
            print("Current counts:", counts)
            print("Current max IDs:", max_ids)

            targets = {"persons": 300, "organizations": 300, "equipments": 200, "facilities": 200, "events": 500}

            # Persons
            if counts["persons"] < targets["persons"]:
                start = max_ids["persons"] + 1
                to_make = targets["persons"] - counts["persons"]
                roles = ["political_leader", "military_commander", "intelligence_officer", "terrorist", "diplomat", "journalist", "business_leader", "other"]
                ranks = ["上将", "中将", "少将", "准将", "上校", "中校", "少校", "上尉", None]
                for i in range(to_make):
                    base = REAL_PERSONS[i % len(REAL_PERSONS)]
                    idx = start + i
                    name = f"{base[0]}-{idx}"
                    name_en = f"{base[1]} {idx}"
                    cur.execute("""
                        INSERT INTO persons (id,full_name,name_en,nationality_id,role,rank_title,
                        current_status,threat_level,is_key_figure,birth_date,created_at,updated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
                    """, (idx, name, name_en, base[2], random.choice(roles), random.choice(ranks),
                          random.choice(["active", "detained", "deceased", "missing", "retired"]),
                          random.choice(["low", "medium", "high", "critical"]),
                          1 if random.random() < 0.2 else 0,
                          datetime.date(random.randint(1950, 1995), random.randint(1, 12), random.randint(1, 28))))
                print(f"Inserted persons: {to_make}")

            # Organizations
            if counts["organizations"] < targets["organizations"]:
                start = max_ids["organizations"] + 1
                to_make = targets["organizations"] - counts["organizations"]
                for i in range(to_make):
                    base = REAL_ORGS[i % len(REAL_ORGS)]
                    idx = start + i
                    name = f"{base[0]}-{idx}"
                    name_en = f"{base[1]} {idx}"
                    cur.execute("""
                        INSERT INTO organizations (id,name,name_en,abbreviation,org_type,country_id,
                        threat_level,is_active,established_date,created_at,updated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
                    """, (idx, name, name_en, f"ORG-{idx:04d}", base[3], base[2],
                          random.choice(["low", "medium", "high", "critical"]), 1,
                          datetime.date(random.randint(1945, 2020), random.randint(1, 12), random.randint(1, 28))))
                print(f"Inserted organizations: {to_make}")

            # Equipments
            if counts["equipments"] < targets["equipments"]:
                start = max_ids["equipments"] + 1
                to_make = targets["equipments"] - counts["equipments"]
                for i in range(to_make):
                    base = REAL_EQUIPMENT[i % len(REAL_EQUIPMENT)]
                    idx = start + i
                    name = f"{base[0]}-{idx}"
                    specs = str({"range": f"{random.randint(500, 5000)}km", "speed": f"{random.uniform(0.8, 3.0):.1f}Mach"}).replace("'", '"')
                    cur.execute("""
                        INSERT INTO equipments (id,name,name_en,equipment_type,sub_type,manufacturer,
                        origin_country_id,operator_country_id,status,quantity,technical_specs,
                        threat_level,created_at,updated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
                    """, (idx, name, name, base[1], base[2], f"Maker-{random.randint(1, 20)}",
                          base[3], random.choice(COUNTRIES), random.choice(["active", "retired", "destroyed", "under_development"]),
                          random.randint(1, 500), specs, random.choice(["low", "medium", "high", "critical"])))
                print(f"Inserted equipments: {to_make}")

            # Facilities
            if counts["facilities"] < targets["facilities"]:
                start = max_ids["facilities"] + 1
                to_make = targets["facilities"] - counts["facilities"]
                for i in range(to_make):
                    base = REAL_FACILITIES[i % len(REAL_FACILITIES)]
                    idx = start + i
                    name = f"{base[0]}-{idx}"
                    cur.execute("""
                        INSERT INTO facilities (id,name,name_en,facility_type,country_id,
                        latitude,longitude,strategic_importance,security_level,status,
                        established_date,created_at,updated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
                    """, (idx, name, name, base[1], base[2], base[3] + random.uniform(-0.5, 0.5),
                          base[4] + random.uniform(-0.5, 0.5), random.choice(["low", "medium", "high", "critical"]),
                          random.choice(["public", "restricted", "secret", "top_secret"]),
                          random.choice(["operational", "non_operational", "destroyed", "under_construction"]),
                          datetime.date(random.randint(1950, 2020), random.randint(1, 12), random.randint(1, 28))))
                print(f"Inserted facilities: {to_make}")

            # Fetch IDs for events
            cur.execute("SELECT id FROM persons")
            all_p = [r["id"] for r in cur.fetchall()]
            cur.execute("SELECT id FROM organizations")
            all_o = [r["id"] for r in cur.fetchall()]
            cur.execute("SELECT id FROM equipments")
            all_e = [r["id"] for r in cur.fetchall()]
            cur.execute("SELECT id FROM facilities")
            all_f = [r["id"] for r in cur.fetchall()]

            # Events & relations
            if counts["events"] < targets["events"]:
                start = max_ids["events"] + 1
                to_make = targets["events"] - counts["events"]
                event_titles = [
                    "{actor}在{loc}发动大规模空袭",
                    "{actor}与{target}在{loc}发生边境冲突",
                    "{actor}海军在{loc}举行联合演习",
                    "{actor}在{loc}试射新型导弹",
                    "{loc}遭到网络攻击，疑似{actor}所为",
                    "{actor}特种部队在{loc}展开反恐行动",
                    "{actor}宣布对{target}实施经济制裁",
                    "{actor}情报机构被曝在{loc}从事间谍活动",
                    "{actor}向{loc}派遣维和部队",
                    "{actor}航母战斗群进入{loc}",
                    "{actor}与{target}在{loc}发生海上对峙",
                    "{actor}在{loc}建立新的军事基地",
                    "{loc}发生军事政变，{actor}介入",
                    "{actor}在{loc}部署新型防空系统",
                    "{actor}无人机在{loc}执行侦察任务时被击落",
                    "{actor}宣布退出{loc}国际条约",
                    "{actor}与{target}签署{loc}停火协议",
                    "{actor}核潜艇在{loc}附近浮出水面",
                    "{loc}核电站遭到{actor}网络攻击",
                    "{actor}在{loc}进行网络战演习",
                ]
                actors = [
                    "美国", "俄罗斯", "中国", "伊朗", "以色列", "朝鲜", "英国", "法国", "德国", "印度",
                    "日本", "韩国", "土耳其", "沙特阿拉伯", "阿联酋", "巴基斯坦", "澳大利亚", "加拿大",
                    "意大利", "西班牙", "埃及", "叙利亚", "乌克兰", "波兰", "越南", "泰国",
                    "新加坡", "马来西亚", "印度尼西亚", "菲律宾", "巴西", "墨西哥", "阿根廷",
                    "南非", "尼日利亚", "肯尼亚",
                ]
                targets = actors[:]
                locs = [
                    "南海", "台海", "东海", "黄海", "渤海", "地中海", "黑海", "红海", "波斯湾", "阿拉伯海",
                    "孟加拉湾", "马六甲海峡", "霍尔木兹海峡", "苏伊士运河", "巴拿马运河", "白令海峡",
                    "北极圈", "巴尔干半岛", "朝鲜半岛", "中东", "东欧", "北非", "东南亚", "南亚", "东亚", "拉美",
                    "太平洋", "大西洋", "印度洋", "北冰洋", "北京", "上海", "莫斯科", "华盛顿", "伦敦",
                    "巴黎", "柏林", "东京", "首尔", "新德里", "德黑兰", "巴格达", "大马士革", "耶路撒冷",
                    "开罗", "伊斯坦布尔", "基辅", "华沙", "曼谷", "新加坡", "河内", "堪培拉", "渥太华",
                ]
                start_d = datetime.date(2023, 1, 1)
                for i in range(to_make):
                    idx = start + i
                    tpl = random.choice(event_titles)
                    a, t, l = random.choice(actors), random.choice(targets), random.choice(locs)
                    title = tpl.format(actor=a, target=t, loc=l)
                    code = f"EVT-{random.randint(2023, 2025)}-{idx:04d}"
                    offset = random.randint(0, (datetime.date(2025, 12, 31) - start_d).days)
                    evt_start = datetime.datetime.combine(start_d + datetime.timedelta(days=offset), datetime.time(random.randint(0, 23), random.randint(0, 59)))
                    evt_end = evt_start + datetime.timedelta(days=random.randint(0, 14)) if random.random() < 0.3 else None
                    killed = random.randint(0, 500) if random.random() < 0.7 else 0
                    injured = random.randint(0, 2000) if random.random() < 0.6 else 0
                    missing = random.randint(0, 100) if random.random() < 0.3 else 0
                    cur.execute("""
                        INSERT INTO events (id,title,event_code,event_type,sub_type,severity,status,
                        start_time,end_time,primary_location,country_id,latitude,longitude,
                        casualties_killed,casualties_injured,casualties_missing,reliability,summary,
                        detailed_description,created_at,updated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
                    """, (idx, title, code,
                          random.choice(["military_conflict", "terrorist_attack", "cyber_attack", "military_exercise", "weapon_test", "border_incident", "sanctions", "diplomatic_tension", "intelligence_operation", "political_crisis"]),
                          random.choice(["airstrike", "ground_battle", "naval_exercise", "missile_test", "skirmish", "espionage", "counter_terrorism", "economic_sanctions"]),
                          random.choice(["low", "medium", "high", "critical"]), random.choice(["ongoing", "concluded", "investigating", "unconfirmed"]),
                          evt_start, evt_end, l, random.choice(COUNTRIES), random.uniform(-60, 70), random.uniform(-180, 180),
                          killed, injured, missing, random.choice(["confirmed", "likely", "possible"]),
                          f"{title}发生于{l}", f"{evt_start}，{title}。据当地媒体报道，冲突造成{killed}人死亡、{injured}人受伤。"))

                    for pid in random.sample(all_p, min(random.randint(1, 5), len(all_p))):
                        cur.execute("INSERT INTO event_persons (event_id,person_id,role,involvement_description,created_at) VALUES (%s,%s,%s,%s,NOW())",
                                    (idx, pid, random.choice(["commander", "perpetrator", "victim", "negotiator", "witness", "target", "other"]), "参与事件"))
                    for oid in random.sample(all_o, min(random.randint(1, 4), len(all_o))):
                        cur.execute("INSERT INTO event_organizations (event_id,organization_id,role,involvement_description,created_at) VALUES (%s,%s,%s,%s,NOW())",
                                    (idx, oid, random.choice(["attacker", "defender", "victim", "mediator", "supporter", "observer", "other"]), "参与事件"))
                    if random.random() < 0.7:
                        for eid in random.sample(all_e, min(random.randint(1, 4), len(all_e))):
                            cur.execute("INSERT INTO event_equipments (event_id,equipment_id,usage_type,quantity,notes,created_at) VALUES (%s,%s,%s,%s,%s,NOW())",
                                        (idx, eid, random.choice(["used_by_attacker", "used_by_defender", "destroyed", "captured", "observed"]), random.randint(1, 50), "装备使用情况"))
                    if random.random() < 0.5:
                        for fid in random.sample(all_f, min(random.randint(1, 2), len(all_f))):
                            cur.execute("INSERT INTO event_facilities (event_id,facility_id,impact_type,damage_assessment,created_at) VALUES (%s,%s,%s,%s,NOW())",
                                        (idx, fid, random.choice(["attacked", "defended", "damaged", "destroyed", "captured", "used_as_base", "target"]), "设施受影响"))
                print(f"Inserted events: {to_make}")

            conn.commit()
            print("\n=== Final counts ===")
            total = 0
            for t in ["countries_regions", "persons", "organizations", "equipments", "facilities", "events", "event_persons", "event_organizations", "event_equipments", "event_facilities", "text_sources"]:
                cur.execute(f"SELECT COUNT(*) AS c FROM `{t}`")
                c = cur.fetchone()["c"]
                total += c
                print(f"  {t:<25} {c:>5}")
            print(f"\nTotal: {total}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
