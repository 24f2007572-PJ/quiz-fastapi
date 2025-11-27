import asyncio
import httpx
import os
import sys
import subprocess
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY")
AIPIPE_TOKEN = os.getenv("AIPIPE_TOKEN")
AIPIPE_URL = "https://aipipe.org/openrouter/v1/chat/completions"

app = FastAPI()
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("quiz.html", {"request": request})


class IncomingRequest(BaseModel):
    email: str
    secret: str
    url: str


'''def extract_code_from_response(response_text: str) -> str:
        import re
        code_blocks = re.findall(r"```python(.*?)```", response_text, re.DOTALL)
        return "\n".join(code_blocks).strip() if code_blocks else response_text.strip()
'''
import re
import ast

import re
import ast

import re
import ast

import re

def extract_and_validate_python_blocks(response_text: str):
    """
    Extract each Python code block from markdown and validate syntax individually.
    Returns a list of tuples: (clean_code, is_valid_syntax, error_message)
    """
    import ast

    blocks = re.findall(r"```(?:python)?\s*(.*?)\s*```", response_text, re.DOTALL | re.IGNORECASE)
    results = []

    for block in blocks:
        code = block.strip()

        try:
            # Use compile to catch syntax errors (works for async code too)
            compile(code, "<string>", "exec")
            results.append((code, True, None))
        except SyntaxError as e:
            results.append((code, False, f"{e.msg} at line {e.lineno}"))

    return results




'''def extract_code_from_response(response_text: str) -> str:
    import re
    # This pattern matches ```python\n ...code... \n``` and captures only the code part.
    code_blocks = re.findall(r"```(?:python)?\s*(.*?)```", response_text, re.DOTALL)
    return "\n".join(code_blocks).strip() if code_blocks else response_text.strip()
'''

async def call_aipipe(prompt: str) -> str:
    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "authorization": f"Bearer {AIPIPE_TOKEN}",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            AIPIPE_URL,
            headers=headers,
            json={
                "model": "openai/gpt-4.1-nano",
                "max_tokens": 2000,
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant that generates workable python scripts."},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
        # Extract content safely
        try:
            return data['choices'][0]['message']['content']
        except (KeyError, IndexError):
            return str(data)


async def process_request(data: dict):
    email = data.get("email")
    starturl = data.get("url")
    print(f"[INFO] Processing request for: {email}")

    prompt = prompt = f"""
        You are an advanced Python automation agent.
        Your task:
        Generate a fully functional Python script that **automates solving quizzes dynamically from URLs**.
        ### Core Requirements:
        1. **Visit the given quiz URL** from starturl using `httpx` or `requests_html` if JavaScript is needed.
        2. Read the page and **Scrape quiz question - Question and possible answers** from the HTML or API response.
        - Read the POST/Submitendpoint/url from the quiz page (Post your JSON answer to ) and save it to SUBMIT_URL variable
        3. If the quiz requires API calls (headers/token will be provided), make the request properly and extract required data.
        4. Use an **LLM API (AIPIPE_URL)** to generate the best answer using the scraped question and choices.
        5. Submit the answer to the **submission endpoint on the same page** (usually in a form tag, hidden input, or API POST URL).
        6. **If submission response returns another quiz URL**, repeat the entire process recursively until:
        - No new URL is returned → quiz completed.
        - or maximum retries reached (3 attempts).
        7. If incorrect, resubmit ONCE after improving response.
        8. All **tokens, API keys, and secrets must come from environment variables**, NOT hardcoded.
        ### Types of quiz problems you must handle:
        - ✔ HTML quizzes (MCQ, text input, forms)
        - ✔ API-based quizzes (REST/GraphQL/JSON)
        - ✔ Data extraction (PDF, text, tables, images)
        - ✔ Data cleaning / processing (text, pandas, NLP)
        - ✔ Math, statistics, ML inference
        - ✔ Geospatial or network analysis
        - ✔ Generate visualizations (images or JSON data for charts)
        - ✔ JavaScript-rendered content (use requests_html or pyppeteer)
        ### Script Requirements:
        - Use: `httpx`, `BeautifulSoup`, `requests_html`, `re`, `json`, `pandas` when needed
        - Use **async** when beneficial
        - Handle:
        - 
        - Missing fields
        - HTTP failures
        - JSON parsing
        - Form submission
        - Timeout and retries 
        - import nest_asyncio
            nest_asyncio.apply()
            # then run the generated script as usual
            import generated_script

        ### Output Format:
        Return **only Python code**, properly indented, inside triple backticks.
        The Python script must:
        - Be standalone and executable
        - Set session timeout to 30 seconds.
        - Use environment variables like:
            AIPIPE_TOKEN = os.getenv("AIPIPE_TOKEN")
            SECRET_KEY = os.getenv("SECRET_KEY")
            AIPIPE_URL = os.getenv("AIPIPE_URL")
        - starturl is passed as command line argument sys.argv[1]
        Use best logic to repeatedly extract and solve until completion.
        Now, generate the full Python script below.
        """
    try:
        generated_code = await call_aipipe(prompt)
    except Exception as e:
        print(f"[ERROR] LLM call failed: {e}")
        return

    blocks = extract_and_validate_python_blocks(generated_code)
    script_path = os.path.join(os.getcwd(), "generated_script.py")
    with open(script_path, "w" , encoding="utf-8") as f:
         for code, valid, _ in blocks:
            if valid:
                f.write(code + "\n\n")
    try:
        completed = subprocess.run(
            [sys.executable, script_path, starturl],
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            timeout=300,
        )
        print(f"[INFO] Script executed with return code {completed.returncode}")
        print(f"[STDOUT] {completed.stdout}")
        print(f"[STDERR] {completed.stderr}")
    except subprocess.TimeoutExpired:
        print("[ERROR] Script execution timed out")
    except Exception as e:
        print(f"[ERROR] Script execution failed: {e}")


@app.post("/receive_request")
async def receive_request(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    if data.get("secret") != SECRET_KEY:
        return JSONResponse(status_code=403, content={"message": "Forbidden"})
    background_tasks.add_task(process_request, data)
    return JSONResponse(
        status_code=200,
        content={"message": "Request received successfully", "email": data.get("email")},
    )


