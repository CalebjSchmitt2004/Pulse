#!/usr/bin/env python3
import sqlite3
import os

DB_FILE = '/app/instance/ipam_uptime.db'

def migrate():
    if not os.path.exists(DB_FILE):
        print("No existing database found. Fresh tables will be created on app start.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    def has_col(table, col):
        cursor.execute(f"PRAGMA table_info({table})")
        return any(row[1] == col for row in cursor.fetchall())

    changes = []

    if not has_col('monitor_group', 'sort_order'):
        cursor.execute("ALTER TABLE monitor_group ADD COLUMN sort_order INTEGER DEFAULT 0")
        cursor.execute("UPDATE monitor_group SET sort_order = id")
        changes.append("Added monitor_group.sort_order")

    if not has_col('monitor', 'sort_order'):
        cursor.execute("ALTER TABLE monitor ADD COLUMN sort_order INTEGER DEFAULT 0")
        cursor.execute("UPDATE monitor SET sort_order = id")
        changes.append("Added monitor.sort_order")

    if not has_col('webhook', 'is_default'):
        cursor.execute("ALTER TABLE webhook ADD COLUMN is_default INTEGER DEFAULT 0")
        changes.append("Added webhook.is_default")

    if not has_col('monitor', 'retry_count'):
        cursor.execute("ALTER TABLE monitor ADD COLUMN retry_count INTEGER DEFAULT 0")
        changes.append("Added monitor.retry_count")

    if not has_col('monitor', 'last_cert_check'):
        cursor.execute("ALTER TABLE monitor ADD COLUMN last_cert_check TIMESTAMP")
        changes.append("Added monitor.last_cert_check")

    if not has_col('monitor', 'last_domain_check'):
        cursor.execute("ALTER TABLE monitor ADD COLUMN last_domain_check TIMESTAMP")
        changes.append("Added monitor.last_domain_check")

    if not has_col('ip_address', 'missed_scans'):
        cursor.execute("ALTER TABLE ip_address ADD COLUMN missed_scans INTEGER DEFAULT 0")
        changes.append("Added ip_address.missed_scans")

    if not has_col('monitor_group', 'color'):
        cursor.execute("ALTER TABLE monitor_group ADD COLUMN color VARCHAR(32) DEFAULT '#3b82f6'")
        changes.append("Added monitor_group.color")

    conn.commit()
    conn.close()

    if changes:
        print("Database migrated successfully:")
        for c in changes:
            print(f"  - {c}")
    else:
        print("Database is already up to date.")

if __name__ == '__main__':
    migrate()