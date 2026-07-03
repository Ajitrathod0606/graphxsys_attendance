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

# timeout/max_retries prevent the client from hanging indefinitely when the
# endpoint is slow, unreachable, or misconfigured.
_azure_client = AsyncOpenAI(base_url=AZURE_ENDPOINT, api_key=AZURE_KEY, timeout=45.0, max_retries=1)
_llm_model = OpenAIChatModel(
    model_name=AZURE_DEPLOYMENT,
    provider=OpenAIProvider(openai_client=_azure_client),
)

class AIInsights:
    def __init__(self, max_sample_rows: int = 100):
        self.max_sample_rows = max_sample_rows
        self.client = _azure_client
        self.model = AZURE_DEPLOYMENT

    def _system_prompt(self) -> str:
        """System role: an advisor writing for store / higher-level management."""
        return (
            "You are a senior workforce-analytics advisor reporting to store managers "
            "and higher-level management (regional and operations leadership). "
            "Your job is to turn raw time-and-attendance data into concise, "
            "decision-ready insights that a busy manager can act on. "
            "Prioritise business impact: punctuality, shift coverage, unclosed shifts "
            "(auto punch-outs), labour discipline, and location performance. "
            "Speak in plain business language, quantify everything with real numbers "
            "and percentages, and be direct about problems and who/where they are. "
            "Do not dump raw data, do not add preamble or closing remarks, and do not "
            "use technical/database jargon."
        )

    def _data_prompt(self, df: pd.DataFrame) -> str:
        """First user message: the data context (stats + sample)."""
        total = len(df)
        date_min = df['Date'].min() if 'Date' in df else 'N/A'
        date_max = df['Date'].max() if 'Date' in df else 'N/A'
        locations = df['Location'].nunique() if 'Location' in df else 0
        employees = df['Employee'].nunique() if 'Employee' in df else 0
        in_variance = df['Time In Variance'].value_counts().to_dict() if 'Time In Variance' in df else {}
        out_variance = df['Time Out Variance'].value_counts().to_dict() if 'Time Out Variance' in df else {}
        sample = df.head(self.max_sample_rows).to_string(index=False)

        return f"""Here is the attendance data for the reporting period.

Total records: {total}
Date range: {date_min} to {date_max}
Locations: {locations}
Employees: {employees}
Check-in variance distribution: {in_variance}
Check-out variance distribution: {out_variance}

Sample rows (first {self.max_sample_rows}):
{sample}"""

    def _task_prompt(self) -> str:
        """Second user message: the specific ask and output format."""
        return (
            "Now write the management briefing for the data above, addressed to a "
            "store manager and higher management who must act this reporting period.\n\n"
            "Structure your answer as EXACTLY these five sections, in this order. Each "
            "section is a markdown H2 heading on its own line (keep the heading text "
            "exactly as shown), followed by 1-4 bullet points that each start with '- ':\n\n"
            "## Punctuality Summary\n"
            "(on-time / late / early %, plus auto punch-outs)\n\n"
            "## Locations to Watch\n"
            "(best and worst performing locations, named, with numbers)\n\n"
            "## People of Concern\n"
            "(named employees with chronic lateness, repeat late check-outs or frequent auto punch-outs)\n\n"
            "## Operational Risk\n"
            "(shift-coverage or unclosed-shift issues implied by the data)\n\n"
            "## Recommended Actions\n"
            "(2-3 concrete, prioritised actions a manager can take)\n\n"
            "Rules: use only these five H2 headings and nothing else outside them. "
            "Every bullet MUST start with '- ' and be quantified with real numbers/"
            "percentages from the data. Name specific locations and employees. "
            "No intro or outro text, no other headings."
        )

    async def generate_insights_async(self, df: pd.DataFrame) -> str:
        if df.empty:
            return "No data available to analyze."

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": self._data_prompt(df)},
                    {"role": "user", "content": self._task_prompt()},
                ],
                max_tokens=900,
                temperature=0.5,
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