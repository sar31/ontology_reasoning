"""Quick MySQL inspection: list tables and their columns / row counts."""
import os

import pymysql

conn = pymysql.connect(
    host=os.getenv("MYSQL_HOST", "localhost"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    user=os.getenv("MYSQL_USER", "root"),
    password=os.getenv("MYSQL_PASSWORD", ""),
    database=os.getenv("MYSQL_DATABASE", "benti"),
    charset="utf8mb4",
)

with conn.cursor() as cur:
    cur.execute("SHOW TABLES")
    tables = [row[0] for row in cur.fetchall()]
    print(f"=== {len(tables)} tables in 'benti' ===")
    for t in tables:
        print(f"\n## {t}")
        cur.execute(f"DESCRIBE `{t}`")
        for col in cur.fetchall():
            print(f"  - {col[0]:<30} {col[1]:<25} null={col[2]} key={col[3]}")
        cur.execute(f"SELECT COUNT(*) FROM `{t}`")
        count = cur.fetchone()[0]
        print(f"  rows: {count}")
        if count > 0:
            cur.execute(f"SELECT * FROM `{t}` LIMIT 3")
            cols = [d[0] for d in cur.description]
            print(f"  sample (cols={cols}):")
            for row in cur.fetchall():
                print(f"    {row}")

conn.close()
