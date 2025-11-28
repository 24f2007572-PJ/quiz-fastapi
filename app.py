import asyncio
import httpx
import os
import sys
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv
import re
import ast
from functools import lru_cache

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

# ------------------------
# Utility functions
# ------------------------

def validate_python(code: str):
    """Return True if code is syntactically valid Python."""
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False

def extract_valid_code_blocks(response_text: str):
    """Extract Python code blocks from markdown and validate."""
    blocks = re.findall(r"```(?:python)?\s*(.*?)\s*```", response_text, re.DOTALL | re.IGNORECASE)
    valid_codes = [block.strip() for block in blocks if validate_python(block.strip())]
    if not valid_codes and validate_python(response_text):
        valid_codes = [response_text]
    return valid_codes

@lru_cache(maxsize=32)
async def cached_call_aipipe(prompt: str):
    """Cache AI responses to reduce repeated API calls."""
    return await call_aipipe(prompt)

async def execute_code_async(code: str, globals_dict=None):
    """Execute Python code in memory asynchronously."""
    if globals_dict is None:
        globals_dict = {}
    wrapper = "async def __tmp_func():\n"
    for line in code.splitlines():
        wrapper += "    " + line + "\n"
    exec(wrapper, globals_dict)
    return await globals_dict["__tmp_func"]()

# ------------------------
# AI API call
# ------------------------

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
        try:
            return data['choices'][0]['message']['content']
        except (KeyError, IndexError):
            return str(data)

# ------------------------
# Optimized request processing
# ------------------------

async def process_request(data: dict):
    email = data.get("email")
    starturl = data.get("url")
    print(f"[INFO] Processing request for: {email}")

    prompt = f"""
    ✅ Detect <div class="hidden-key"> and decode reversed answers
    ✅ Handle MCQ, text input, API-based, and recursive quizzes
    ✅ Use only aiohttp, httpx, BeautifulSoup, asyncio, json, re, os, sys
    ❌ Never use requests_html, AsyncHTMLSession, playwright, or sync requests
    ⚙️ Use proper async/await, context management, and error handling
    🔥 Updated Prompt (Use this in your FastAPI app)
    You are an advanced Python automation agent.
    ...
    (starturl = {starturl})
    ...
    Return ONLY Python code (no explanations), wrapped in triple backticks.
    """

    try:
        generated_code = await cached_call_aipipe(prompt)
    except Exception as e:
        print(f"[ERROR] LLM call failed: {e}")
        return

    valid_codes = extract_valid_code_blocks(generated_code)
    if not valid_codes:
        print("[ERROR] No valid Python code extracted from AI response.")
        return

    globals_dict = {"__name__": "__main__", "starturl": starturl}

    for idx, code in enumerate(valid_codes):
        try:
            print(f"[INFO] Executing code block {idx+1}/{len(valid_codes)}")

            # 🚫 Block asyncio.run() — replace with await
            if "asyncio.run(" in code:
                print("[WARNING] asyncio.run() detected — converting to await.")
                code = re.sub(r"asyncio\.run\((.*?)\)", r"await \1", code)

            # 🚫 Convert time.sleep() → await asyncio.sleep()
            if "time.sleep(" in code:
                print("[WARNING] time.sleep() detected — converting to await asyncio.sleep().")
                code = re.sub(r"time\.sleep\((.*?)\)", r"await asyncio.sleep(\1)", code)

            # 🚫 Prevent use of blocking requests library
            if "requests." in code:
                print("[ERROR] Blocking requests library detected. Rejecting code block.")
                continue

            #  Wrap into async function
            wrapper = "async def __tmp_func():\n"
            for line in code.splitlines():
                wrapper += "    " + line + "\n"
            # 🚫 Fix incorrect use of `async with client.get(...)`
            if re.search(r"async with\s+[\w\.]+\.get", code):
                print("[WARNING] Incorrect async with client.get() usage detected — fixing.")
                code = re.sub(
                    r"async with\s+([\w\.]+)\.get\((.*?)\)\s+as\s+(\w+):",
                    r"\1_response = await \1.get(\2)\n    \3 = \1_response",
                code
                )

            # 🚫 Fix missing 'await' before client.get(...)
            code = re.sub(r"(\s)([\w\.]+)\.get\(", r"\1await \2.get(", code)

            exec(wrapper, globals_dict)

            # Await safely inside current event loop
            coro = globals_dict["__tmp_func"]()
            await coro  # (Never use asyncio.run)

        except Exception as e:
            print(f"[ERROR] Execution failed in block {idx+1}: {e}")

    print("[INFO] All code blocks executed successfully")
# API Endpoint
# ------------------------

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

# ------------------------
# Run the server
# ------------------------
