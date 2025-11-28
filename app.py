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
✅ Detect <div class="hidden-key"> and decode reversed answers
✅ Handle MCQ, text input, API-based, and recursive quizzes
✅ Use only aiohttp, httpx, BeautifulSoup, asyncio, json, re, os, sys
❌ Never use requests_html, AsyncHTMLSession, playwright, or sync requests
⚙️ Use proper async/await, context management, and error handling
🔥 Updated Prompt (Use this in your FastAPI app)
You are an advanced Python automation agent.
🎯 Goal:
Generate a fully functional, executable Python script that automatically solves quizzes dynamically from URLs using asynchronous logic and safe libraries.
---
📌 Core Functional Requirements:
1. Start from `starturl` (passed as `sys.argv[1]`).
2. Fetch page content using ONLY:
   ✔ aiohttp.ClientSession() for HTML pages  
   ✔ httpx.AsyncClient() for API calls  
   ❌ Do NOT use requests_html, AsyncHTMLSession, requests, selenium, playwright.
3. Parse content using BeautifulSoup or JSON.
---
🧠 Quiz Type Detection Logic:
Automatically detect the quiz type using these rules:
🟢 Type 1: Hidden text quiz  
- Detect: `<div class="hidden-key">`  
- Extract reversed string → reverse it using `[::-1]`  
- Use that as the final answer  
🟢 Type 2: Multiple Choice Quiz  
- Detect `<input type="radio">`, `<button>`, or `<label>`  
- Extract question and choices  
- Send to LLM API to determine best answer  
🟢 Type 3: Text Input Quiz  
- Detect `<input type="text">` or `<textarea>`  
- Extract question text  
- Send question to LLM API for answer  
🟡 Type 4: API-Based Quiz  
- Detect API endpoints in page source (fetch, POST URLs, JSON forms)  
- Extract API URL, headers, body, and authentication  
- Call API using httpx.AsyncClient()  
- Extract answer from response  
🔁 Recursion:
If the submission response contains a new quiz URL (redirect or JSON field), repeat the solving workflow up to 3 times.
🔐 Environment Variables (must be used):
AIPIPE_TOKEN = os.getenv("AIPIPE_TOKEN")
SECRET_KEY = os.getenv("SECRET_KEY")
AIPIPE_URL = os.getenv("AIPIPE_URL")
📤 LLM Answer Request Format:
When calling the LLM for reasoning, use:
  "question": "...",
  "choices": [...optional...],
  "context": "...optional..."
Use httpx.AsyncClient() for POST requests.
📎 Submission:
Extract form action URL, hidden input fields, or JSON submission endpoint.
- Search for any element containing the word `"Submission"` (case-insensitive).
   - Look for nearby `form` elements, `action` attributes, `button` clicks, or POST URLs.
   - If JSON APIs are used, detect URL patterns that appear under the `"submission"` section or `"submit_url"` in page scripts or inline JSON.
Submit answer as form-data or JSON.
Print submission result and quiz completion status.
⚙️ Technical Rules:
✔ Must be fully asynchronous (async def, await, async with)
✔ Use BeautifulSoup for HTML parsing
✔ Use httpx or aiohttp only
✔ Set timeout to 30 seconds
✔ Handle connection errors, timeouts, invalid HTML, and missing fields
✔ No hardcoded credentials — only environment variables
✔ Must run as standalone Python script using:
python generated_script.py <starturl>
📝 Output Format:
Return ONLY Python code (no explanations), wrapped in:
# full script here
The script must be complete, clean, and executable.
Now, generate the complete Python script below that meets all these requirements
"""
    try:
        generated_code = await call_aipipe(prompt)
        #print(generated_code)
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
