# src/ai_insights.py
import os
import asyncio
import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

load_dotenv()

AZURE_ENDPOINT = os.getenv('AZURE_OPENAI_ENDPOINT')
AZURE_DEPLOYMENT = os.getenv('AZURE_OPENAI_DEPLOYMENT')
AZURE_KEY = os.getenv('AZURE_OPENAI_KEY')

_azure_client = AsyncOpenAI(base_url=AZURE_ENDPOINT, api_key=AZURE_KEY)
_llm_model = OpenAIChatModel(
    model_name=AZURE_DEPLOYMENT,
    provider=OpenAIProvider(openai_client=_azure_client),
)

class AIInsights:
    def __init__(self, max_sample_rows: int = 100):
        self.max_sample_rows = max_sample_rows
        self.client = _azure_client
        self.model = AZURE_DEPLOYMENT

    def _build_prompt(self, df: pd.DataFrame) -> str:
        if df.empty:
            return "The dataset is empty. No insights to generate."

        # Basic statistics
        total = len(df)
        date_min = df['Date'].min() if 'Date' in df else 'N/A'
        date_max = df['Date'].max() if 'Date' in df else 'N/A'
        locations = df['Location'].nunique() if 'Location' in df else 0
        employees = df['Employee'].nunique() if 'Employee' in df else 0

        # Variance counts
        in_variance = df['Time In Variance'].value_counts().to_dict() if 'Time In Variance' in df else {}
        out_variance = df['Time Out Variance'].value_counts().to_dict() if 'Time Out Variance' in df else {}

        # Sample
        sample = df.head(self.max_sample_rows).to_string(index=False)

        prompt = f"""
You are a senior data analyst. You are given attendance data for a company.
Provide **concise, actionable insights** in **bullet point format** (each point starting with "- ").
Do not write a narrative paragraph. Keep it clear and professional.

Focus on:
1. Overall attendance summary (total records, date range, locations, employees).
2. Check‑in patterns: On‑time, Late, Early counts and percentages.
3. Check‑out patterns: On‑time, Late, Early, Auto‑punchout counts and percentages.
4. Any notable anomalies (e.g., high late rates, frequent auto‑punchouts).
5. Location‑wise performance (if multiple locations, mention which has best/worst punctuality).
6. Employee‑wise outliers (if any employee stands out with excessive lateness).
7. Trends (e.g., if late check‑ins are more common on certain days – but we don't have day of week, so skip).
8. Recommendations for improvement.

Use the following statistics and sample data:

Total records: {total}
Date range: {date_min} to {date_max}
Number of locations: {locations}
Number of employees: {employees}

Check‑in variance distribution: {in_variance}
Check‑out variance distribution: {out_variance}

Sample data (first {self.max_sample_rows} rows):
{sample}

Provide your insights as a bullet list (each line starting with "- ").
"""
        return prompt

    async def generate_insights_async(self, df: pd.DataFrame) -> str:
        if df.empty:
            return "No data available to analyze."

        prompt = self._build_prompt(df)
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert data analyst."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=800,
                temperature=0.7,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"Error generating insights: {str(e)}"

    def generate_insights(self, df: pd.DataFrame) -> str:
        return asyncio.run(self.generate_insights_async(df))

# Convenience function
def generate_insights(df: pd.DataFrame, max_rows: int = 100) -> str:
    ai = AIInsights(max_sample_rows=max_rows)
    return ai.generate_insights(df)