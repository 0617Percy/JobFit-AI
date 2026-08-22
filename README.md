# JobFit AI

> AI-powered resume and job-fit analysis assistant for students and early-career candidates. Beta.

JobFit AI reads a resume and a target job description (JD), asks you to confirm key information, then
produces an evidence-grounded job-fit analysis: an application recommendation, resume optimization
suggestions, and interview preparation — all traceable to the facts in your resume.

## What it does

- **Resume + JD in** — paste text or upload PDF / DOCX / TXT
- **Information confirmation** — review and confirm the extracted facts before analysis
- **Job-fit analysis** — requirement-by-requirement evidence matching with a deterministic, reproducible score
- **Application recommendation** — a conservative, explainable recommendation
- **Resume optimization** — grounded rewording suggestions, never fabricated achievements
- **Interview preparation** — tailored questions based on your resume and the JD

## Audience

Students, new graduates, and candidates with 0–2 years of experience.

## Status

**Beta.** JobFit AI is currently a Beta product. Results are intended to support, not replace, personal
career decisions.

## Run locally

Requirements: Python 3.11 or 3.12 (a virtual environment is recommended).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m streamlit run app_v2.py
```

Then open **http://localhost:8501** in your browser.

On macOS / Linux:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -e ".[dev]"
./.venv/bin/python -m streamlit run app_v2.py
```

## DeepSeek BYOK (bring your own key)

JobFit AI does not ship with a model API key. You provide your own DeepSeek API key at runtime:

1. Start the app (`streamlit run app_v2.py`).
2. In the sidebar, set **分析模式** to **DeepSeek BYOK**.
3. Enter your DeepSeek API key in the **DeepSeek API Key** field (kept only in your session; never
   written to disk or version control).
4. Optionally click **验证DeepSeek连接** to check connectivity, then run your analysis.

The app also includes a fully offline demo mode ("Offline Demo / Mock") that needs no API key.

Never commit a real API key. If you keep a local `.env` file, only placeholders belong in version
control (see `.env.example`).

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest          # offline test suite; no real API required
.\.venv\Scripts\python.exe -m ruff check .    # lint
.\.venv\Scripts\python.exe -m pip check       # dependency health
```

## License

See [LICENSE](LICENSE).
