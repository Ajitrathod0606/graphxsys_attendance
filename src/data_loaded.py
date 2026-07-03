# src/data_loaded.py
import os
import json
import pyodbc
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

class DataLoader:
    def __init__(self):
        driver = os.getenv('SQL_DRIVER')
        server = os.getenv('SQL_SERVER')
        database = os.getenv('SQL_NAME')
        username = os.getenv('SQL_USERNAME')
        password = os.getenv('SQL_PASSWORD')
        self.conn_str = (
            f"DRIVER={driver};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"UID={username};"
            f"PWD={password};"
        )

    def get_connection(self):
        return pyodbc.connect(self.conn_str)

    def fetch_attendance_json(
        self,
        type_val=1,
        user_id=0,
        clid=9,
        fdate='2026-06-01',
        tdate='2026-06-30',
        region='',
        district='',
        location='',
        employee=''
    ):
        """
        Execute MM_TS_TimeAttendance_AI_TEST and return the raw JSON string.
        """
        sql = """
            EXEC [dbo].[MM_TS_TimeAttendance_AI_TEST]
                @Type = ?,
                @User_Id = ?,
                @CLID = ?,
                @FDATE = ?,
                @TDATE = ?,
                @REGION = ?,
                @DISTRICT = ?,
                @LOCATION = ?,
                @EMPLOYEE = ?
        """
        with self.get_connection() as conn:
            # Safety net: fail with an error after 3 minutes instead of hanging
            # forever if the proc is given a pathological date range.
            conn.timeout = 180
            cursor = conn.cursor()
            cursor.execute(sql, (
                type_val, user_id, clid, fdate, tdate,
                region, district, location, employee
            ))
            row = cursor.fetchone()
            if row and row[0]:
                return row[0]   # the JSON string
            return '[]'

    def fetch_attendance_dataframe(self, **kwargs):
        """Fetch data and return as pandas DataFrame (convenience)."""
        json_str = self.fetch_attendance_json(**kwargs)
        data = json.loads(json_str)
        if data:
            return pd.DataFrame(data)
        return pd.DataFrame()