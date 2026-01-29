# -*- coding: utf-8 -*-
"""
SQLite database manager for storing device states.
Python 3.7+ compatible, uses only standard library.
"""
import sqlite3
import json
import os
from datetime import datetime


class DeviceDatabase:
    """SQLite database for tracking SwitchBot device states."""

    def __init__(self, db_path='device_states.db'):
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initialize database tables."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Main table for latest device states
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS device_states (
                device_id TEXT PRIMARY KEY,
                device_name TEXT,
                device_type TEXT,
                status_json TEXT,
                updated_at TEXT
            )
        ''')

        # History table for tracking changes
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS device_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT,
                device_name TEXT,
                device_type TEXT,
                status_json TEXT,
                recorded_at TEXT
            )
        ''')

        # Index for faster history queries
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_history_device_id
            ON device_history(device_id, recorded_at)
        ''')

        conn.commit()
        conn.close()

    def get_device_state(self, device_id):
        """
        Get current stored state for a device.

        Args:
            device_id: Device ID

        Returns:
            dict or None: Device state if exists
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            'SELECT * FROM device_states WHERE device_id = ?',
            (device_id,)
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                'device_id': row['device_id'],
                'device_name': row['device_name'],
                'device_type': row['device_type'],
                'status': json.loads(row['status_json']) if row['status_json'] else None,
                'updated_at': row['updated_at']
            }
        return None

    def save_device_state(self, device_id, device_name, device_type, status):
        """
        Save current device state.

        Args:
            device_id: Device ID
            device_name: Device name
            device_type: Device type
            status: Status dict from API

        Returns:
            bool: True if state changed, False if same
        """
        now = datetime.utcnow().isoformat()
        status_json = json.dumps(status, sort_keys=True, ensure_ascii=False)

        # Get existing state
        existing = self.get_device_state(device_id)

        # Check if state changed
        state_changed = False
        if existing:
            existing_json = json.dumps(existing['status'], sort_keys=True, ensure_ascii=False)
            state_changed = existing_json != status_json
        else:
            state_changed = True  # New device

        conn = self._get_connection()
        cursor = conn.cursor()

        # Upsert current state
        cursor.execute('''
            INSERT OR REPLACE INTO device_states
            (device_id, device_name, device_type, status_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (device_id, device_name, device_type, status_json, now))

        # Record history if changed
        if state_changed:
            cursor.execute('''
                INSERT INTO device_history
                (device_id, device_name, device_type, status_json, recorded_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (device_id, device_name, device_type, status_json, now))

        conn.commit()
        conn.close()

        return state_changed

    def get_changes(self, device_id, old_status, new_status):
        """
        Detect what changed between two status dicts.

        Args:
            device_id: Device ID
            old_status: Previous status dict
            new_status: Current status dict

        Returns:
            list: List of change descriptions
        """
        if old_status is None:
            return [{'field': 'device', 'message': 'New device detected'}]

        changes = []
        all_keys = set(list(old_status.keys()) + list(new_status.keys()))

        # Keys to ignore (they always change)
        ignore_keys = {'deviceId', 'hubDeviceId'}

        for key in all_keys:
            if key in ignore_keys:
                continue

            old_val = old_status.get(key)
            new_val = new_status.get(key)

            if old_val != new_val:
                changes.append({
                    'field': key,
                    'old_value': old_val,
                    'new_value': new_val,
                    'message': '{}: {} -> {}'.format(key, old_val, new_val)
                })

        return changes

    def get_device_history(self, device_id, limit=100):
        """
        Get history of state changes for a device.

        Args:
            device_id: Device ID
            limit: Maximum records to return

        Returns:
            list: List of historical states
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM device_history
            WHERE device_id = ?
            ORDER BY recorded_at DESC
            LIMIT ?
        ''', (device_id, limit))

        rows = cursor.fetchall()
        conn.close()

        return [
            {
                'device_id': row['device_id'],
                'device_name': row['device_name'],
                'device_type': row['device_type'],
                'status': json.loads(row['status_json']) if row['status_json'] else None,
                'recorded_at': row['recorded_at']
            }
            for row in rows
        ]

    def get_all_devices(self):
        """
        Get all tracked devices.

        Returns:
            list: List of all device states
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM device_states ORDER BY device_name')
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                'device_id': row['device_id'],
                'device_name': row['device_name'],
                'device_type': row['device_type'],
                'status': json.loads(row['status_json']) if row['status_json'] else None,
                'updated_at': row['updated_at']
            }
            for row in rows
        ]

    def cleanup_old_history(self, days=30):
        """
        Remove history older than specified days.

        Args:
            days: Number of days to keep
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            DELETE FROM device_history
            WHERE recorded_at < datetime('now', '-{} days')
        '''.format(int(days)))

        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        return deleted


if __name__ == '__main__':
    # Simple test
    db = DeviceDatabase('test_device_states.db')

    # Test save and retrieve
    test_status = {
        'deviceId': 'TEST123',
        'temperature': 25.5,
        'humidity': 60
    }

    changed = db.save_device_state('TEST123', 'Test Device', 'Meter', test_status)
    print("State changed: {}".format(changed))

    state = db.get_device_state('TEST123')
    print("Retrieved state: {}".format(json.dumps(state, indent=2, ensure_ascii=False)))

    # Test change detection
    new_status = {
        'deviceId': 'TEST123',
        'temperature': 26.0,
        'humidity': 58
    }

    changes = db.get_changes('TEST123', test_status, new_status)
    print("Changes detected: {}".format(changes))

    # Cleanup test db
    os.remove('test_device_states.db')
    print("Test completed successfully!")
