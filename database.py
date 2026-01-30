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

        # Time series table for sensor data (temperature, humidity, CO2)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sensor_timeseries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                device_name TEXT,
                recorded_at TEXT NOT NULL,
                temperature REAL,
                humidity REAL,
                co2 INTEGER,
                battery INTEGER
            )
        ''')

        # Index for time series queries
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_timeseries_device_date
            ON sensor_timeseries(device_id, recorded_at)
        ''')

        # Netatmo time series table (includes pressure and noise)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS netatmo_timeseries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                device_name TEXT,
                station_name TEXT,
                module_type TEXT,
                is_outdoor INTEGER DEFAULT 0,
                recorded_at TEXT NOT NULL,
                temperature REAL,
                humidity REAL,
                co2 INTEGER,
                pressure REAL,
                noise INTEGER,
                battery_percent INTEGER
            )
        ''')

        # Index for Netatmo time series queries
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_netatmo_timeseries_device_date
            ON netatmo_timeseries(device_id, recorded_at)
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

    # ========== Sensor Time Series Methods ==========

    def save_sensor_data(self, device_id, device_name, status):
        """
        Save sensor time series data (temperature, humidity, CO2).

        Args:
            device_id: Device ID
            device_name: Device name
            status: Status dict from API

        Returns:
            bool: True if data was saved
        """
        # Extract sensor values
        temperature = status.get('temperature')
        humidity = status.get('humidity')
        co2 = status.get('CO2')
        battery = status.get('battery')

        # Only save if there's sensor data
        if temperature is None and humidity is None and co2 is None:
            return False

        now = datetime.utcnow().isoformat()

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO sensor_timeseries
            (device_id, device_name, recorded_at, temperature, humidity, co2, battery)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (device_id, device_name, now, temperature, humidity, co2, battery))

        conn.commit()
        conn.close()

        return True

    def get_sensor_data_for_date(self, device_id, date_str=None):
        """
        Get sensor data for a specific date.

        Args:
            device_id: Device ID
            date_str: Date string (YYYY-MM-DD), defaults to today

        Returns:
            list: List of sensor readings for the day
        """
        if date_str is None:
            date_str = datetime.utcnow().strftime('%Y-%m-%d')

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM sensor_timeseries
            WHERE device_id = ?
            AND date(recorded_at) = date(?)
            ORDER BY recorded_at ASC
        ''', (device_id, date_str))

        rows = cursor.fetchall()
        conn.close()

        return [
            {
                'device_id': row['device_id'],
                'device_name': row['device_name'],
                'recorded_at': row['recorded_at'],
                'temperature': row['temperature'],
                'humidity': row['humidity'],
                'co2': row['co2'],
                'battery': row['battery']
            }
            for row in rows
        ]

    def get_sensor_data_range(self, device_id, start_date, end_date):
        """
        Get sensor data for a date range.

        Args:
            device_id: Device ID
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            list: List of sensor readings
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM sensor_timeseries
            WHERE device_id = ?
            AND date(recorded_at) >= date(?)
            AND date(recorded_at) <= date(?)
            ORDER BY recorded_at ASC
        ''', (device_id, start_date, end_date))

        rows = cursor.fetchall()
        conn.close()

        return [
            {
                'device_id': row['device_id'],
                'device_name': row['device_name'],
                'recorded_at': row['recorded_at'],
                'temperature': row['temperature'],
                'humidity': row['humidity'],
                'co2': row['co2'],
                'battery': row['battery']
            }
            for row in rows
        ]

    def get_all_sensor_devices(self):
        """
        Get list of devices with sensor data.

        Returns:
            list: List of device info dicts
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT DISTINCT device_id, device_name
            FROM sensor_timeseries
            ORDER BY device_name
        ''')

        rows = cursor.fetchall()
        conn.close()

        return [
            {'device_id': row['device_id'], 'device_name': row['device_name']}
            for row in rows
        ]

    def get_daily_summary(self, device_id, date_str=None):
        """
        Get daily summary statistics for a device.

        Args:
            device_id: Device ID
            date_str: Date string (YYYY-MM-DD), defaults to today

        Returns:
            dict: Summary with min/max/avg for each metric
        """
        if date_str is None:
            date_str = datetime.utcnow().strftime('%Y-%m-%d')

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT
                COUNT(*) as count,
                MIN(temperature) as temp_min,
                MAX(temperature) as temp_max,
                AVG(temperature) as temp_avg,
                MIN(humidity) as humidity_min,
                MAX(humidity) as humidity_max,
                AVG(humidity) as humidity_avg,
                MIN(co2) as co2_min,
                MAX(co2) as co2_max,
                AVG(co2) as co2_avg
            FROM sensor_timeseries
            WHERE device_id = ?
            AND date(recorded_at) = date(?)
        ''', (device_id, date_str))

        row = cursor.fetchone()
        conn.close()

        if row and row['count'] > 0:
            return {
                'date': date_str,
                'count': row['count'],
                'temperature': {
                    'min': row['temp_min'],
                    'max': row['temp_max'],
                    'avg': round(row['temp_avg'], 1) if row['temp_avg'] else None
                },
                'humidity': {
                    'min': row['humidity_min'],
                    'max': row['humidity_max'],
                    'avg': round(row['humidity_avg'], 1) if row['humidity_avg'] else None
                },
                'co2': {
                    'min': row['co2_min'],
                    'max': row['co2_max'],
                    'avg': round(row['co2_avg']) if row['co2_avg'] else None
                }
            }
        return None

    def cleanup_old_sensor_data(self, days=7):
        """
        Remove sensor time series data older than specified days.

        Args:
            days: Number of days to keep

        Returns:
            int: Number of deleted records
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            DELETE FROM sensor_timeseries
            WHERE recorded_at < datetime('now', '-{} days')
        '''.format(int(days)))

        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        return deleted

    # ========== Netatmo Time Series Methods ==========

    def save_netatmo_data(self, device_id, device_name, station_name, module_type,
                          is_outdoor, temperature=None, humidity=None, co2=None,
                          pressure=None, noise=None, battery_percent=None):
        """
        Save Netatmo sensor time series data.

        Args:
            device_id: Netatmo device/module ID (MAC address)
            device_name: Device/module name
            station_name: Station name
            module_type: Module type (NAMain, NAModule1, etc.)
            is_outdoor: Whether this is an outdoor module
            temperature: Temperature in Celsius
            humidity: Humidity percentage
            co2: CO2 in ppm
            pressure: Pressure in mbar
            noise: Noise level in dB
            battery_percent: Battery percentage

        Returns:
            bool: True if data was saved
        """
        # Only save if there's any sensor data
        if temperature is None and humidity is None and co2 is None and pressure is None and noise is None:
            return False

        now = datetime.utcnow().isoformat()

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO netatmo_timeseries
            (device_id, device_name, station_name, module_type, is_outdoor,
             recorded_at, temperature, humidity, co2, pressure, noise, battery_percent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (device_id, device_name, station_name, module_type, 1 if is_outdoor else 0,
              now, temperature, humidity, co2, pressure, noise, battery_percent))

        conn.commit()
        conn.close()

        return True

    def get_netatmo_data_for_date(self, device_id, date_str=None):
        """
        Get Netatmo sensor data for a specific date.

        Args:
            device_id: Device ID
            date_str: Date string (YYYY-MM-DD), defaults to today

        Returns:
            list: List of sensor readings for the day
        """
        if date_str is None:
            date_str = datetime.utcnow().strftime('%Y-%m-%d')

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM netatmo_timeseries
            WHERE device_id = ?
            AND date(recorded_at) = date(?)
            ORDER BY recorded_at ASC
        ''', (device_id, date_str))

        rows = cursor.fetchall()
        conn.close()

        return [
            {
                'device_id': row['device_id'],
                'device_name': row['device_name'],
                'station_name': row['station_name'],
                'module_type': row['module_type'],
                'is_outdoor': bool(row['is_outdoor']),
                'recorded_at': row['recorded_at'],
                'temperature': row['temperature'],
                'humidity': row['humidity'],
                'co2': row['co2'],
                'pressure': row['pressure'],
                'noise': row['noise'],
                'battery_percent': row['battery_percent']
            }
            for row in rows
        ]

    def get_all_netatmo_devices(self):
        """
        Get list of Netatmo devices with sensor data.

        Returns:
            list: List of device info dicts
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT DISTINCT device_id, device_name, station_name, module_type, is_outdoor
            FROM netatmo_timeseries
            ORDER BY station_name, device_name
        ''')

        rows = cursor.fetchall()
        conn.close()

        return [
            {
                'device_id': row['device_id'],
                'device_name': row['device_name'],
                'station_name': row['station_name'],
                'module_type': row['module_type'],
                'is_outdoor': bool(row['is_outdoor'])
            }
            for row in rows
        ]

    def cleanup_old_netatmo_data(self, days=7):
        """
        Remove Netatmo time series data older than specified days.

        Args:
            days: Number of days to keep

        Returns:
            int: Number of deleted records
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            DELETE FROM netatmo_timeseries
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
