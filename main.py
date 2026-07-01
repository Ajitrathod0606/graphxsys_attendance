# src/main.py
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_loaded import DataLoader
from src.ai_insights import generate_insights
from tabulate import tabulate

def main():
    loader = DataLoader()

    # Load data for a date range (Type=1 for daily attendance)
    df = loader.fetch_attendance_dataframe(
        type_val=1,
        user_id=16199,
        clid=9,
        fdate='2026/06/01',
        tdate='2026/06/30'
    )

    if df.empty:
        print("No data returned.")
        return

    print(f"✅ Total rows: {len(df)}")
    print("\n📊 Data preview (first 10 rows):\n")
    print(tabulate(df.head(10), headers='keys', tablefmt='psql', showindex=False))

    # Generate AI insights
    print("\n🤖 Generating AI Insights...\n")
    insights = generate_insights(df)
    print("=" * 80)
    print("AI INSIGHTS")
    print("=" * 80)
    print(insights)
    print("=" * 80)

if __name__ == "__main__":
    main()