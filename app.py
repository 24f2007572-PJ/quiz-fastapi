import asyncio
import httpx
import os
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv
import re
import ast
from functools import lru_cache
from bs4 import BeautifulSoup


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
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def extract_valid_code_blocks(response_text: str):
    blocks = re.findall(r"```(?:python)?\s*(.*?)\s*```", response_text, re.DOTALL | re.IGNORECASE)
    valid_codes = [block.strip() for block in blocks if validate_python(block.strip())]
    if not valid_codes and validate_python(response_text):
        valid_codes = [response_text]
    return valid_codes


@lru_cache(maxsize=32)
async def cached_call_aipipe(prompt: str):
    return await call_aipipe(prompt)


async def execute_code_async(code: str, globals_dict=None):
    if globals_dict is None:
        globals_dict = {}
    wrapper = "async def __tmp_func():\n"
    for line in code.splitlines():
        wrapper += "    " + line + "\n"
    exec(wrapper, globals_dict)
    return await globals_dict["__tmp_func"]()

# ------------------------
# Fault-Tolerant Code Execution Helpers
# ------------------------

def repair_code(code: str, starturl: str):
    code = code.replace("```python", "").replace("```", "").strip()
    code = code.replace("await await ", "await ").replace("await  await", "await ")
    code = re.sub(r"(\s)([\w\.]+)\.get\(", r"\1await \2.get(", code)
    code = re.sub(r"async with\s+([\w\.]+)\.get\((.*?)\)\s+as\s+(\w+):",
                  r"\1_response = await \1.get(\2)\n    \3 = \1_response",
                  code)
    # Replace placeholder URLs
    placeholders = [
        "<the quiz URL>", "<the quiz URL you fetched>",
        "<quiz url>", "<quiz_url>", "YOUR_START_URL_HERE","https://example.com/quiz"
    ]
    for ph in placeholders:
        code = code.replace(ph, starturl)
    code = code.replace("<the quiz URL>", starturl)
    code = code.replace("<the quiz URL you fetched>", starturl)
    code = code.replace("<quiz url>", starturl)
    code = code.replace("<quiz_url>", starturl)
    code = code.replace("<submit url>", "")
    code = code.replace("<the quiz submission URL>", "")
    
    if "import httpx" not in code:
        code = "import httpx\n" + code
    if "import re" not in code:
        code = "import re\n" + code
    if "async def main" not in code:
        code += "\n\nasync def main():\n    pass\n"
    fixed_lines = [line.replace("\t", "    ") for line in code.splitlines()]
    return "\n".join(fixed_lines).strip()


async def run_code_safely(code: str, starturl: str):
    """
    Executes LLM-generated Python code safely.
    Automatically fixes:
    - double 'await await'
    - placeholder URLs
    - missing imports
    """
    # -------------------
    # Repair the code
    # -------------------
    code = code.replace("```python", "").replace("```", "").strip()
    code = code.replace("await await ", "await ").replace("await  await", "await ")
    
    # Fix missing await before client.get(...)
    code = re.sub(r"(\s)([\w\.]+)\.get\(", r"\1await \2.get(", code)
    
    # Fix incorrect async with client.get usage
    code = re.sub(
        r"async with\s+([\w\.]+)\.get\((.*?)\)\s+as\s+(\w+):",
        r"\1_response = await \1.get(\2)\n    \3 = \1_response",
        code
    )
    
    # Replace placeholders with the actual starturl
    placeholders = [
        "<the quiz URL>", "<the quiz URL you fetched>",
        "<quiz url>", "<quiz_url>", "YOUR_START_URL_HERE"
    ]
    for ph in placeholders:
        code = code.replace(ph, starturl)
    
    # Remove placeholder submit URLs
    code = code.replace("<submit url>", "")
    code = code.replace("<the quiz submission URL>", "")
    
    # Ensure essential imports exist
    if "import httpx" not in code:
        code = "import httpx\n" + code
    if "import re" not in code:
        code = "import re\n" + code
    
    # Ensure async main exists
    if "async def main" not in code:
        code += "\n\nasync def main():\n    pass\n"
    
    # Normalize indentation
    fixed_lines = [line.replace("\t", "    ") for line in code.splitlines()]
    repaired_code = "\n".join(fixed_lines).strip()
    
    # -------------------
    # Wrap and execute
    # -------------------
    print("\n================== REPAIRED CODE ==================")
    print(repaired_code)
    print("===================================================\n")
    
    wrapper = "async def __tmp_func():\n"
    for line in repaired_code.splitlines():
        wrapper += "    " + line + "\n"
    
    env = {"__name__": "__main__", "starturl": starturl, "asyncio": asyncio}
    print("Run")
    exec(wrapper, env)
    print("After exec")
    # Execute safely
    await env["__tmp_func"]()

# ------------------------
# AI API call
# ------------------------

async def call_aipipe(prompt: str) -> str:
    headers = {
        "accept": "*/*",
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
                    {"role": "system", "content": "You are a helpful assistant that generates workable Python scripts."},
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

    prompt = """
You must produce ONLY valid Python3 code inside a single ```python ... ``` block.  
No explanation. No English. No placeholders. No TODOs.

RULES YOU MUST FOLLOW:

2. ALWAYS write syntactically valid Python. Validate the syntax of the generated code before returning.
3. ALWAYS use:
       async with httpx.AsyncClient() as client:
4. To fetch the quiz page, ALWAYS do:
       response = await client.get(starturl)
5. NEVER include placeholder strings like "<quiz url>" or "<submit url>".
6. Extract the submit URL from the quiz page HTML using regex or BeautifulSoup.
7.	The submit URL MUST be derived from the quiz page as follows:
o	The page shows the submit path as /submit
o	The full submit URL is constructed using the origin of response.url
o	You MAY extract /submit from HTML, but you MUST combine it with the inferred origin
8.	You MUST extract the submit URL using regex or BeautifulSoup. (HTML contains: /submit)

8. You MUST compute the correct quiz answer from the quiz page content.
9. Post the answer using:
       await client.post(submit_url, json=payload)
10. Payload MUST be EXACTLY:
   {
       "email": "24f2007572@ds.study.iitm.ac.in",
       "secret": "peacock",
       "url": starturl,
       "answer": <computed answer>
   }
11. The code MUST define an async main() function. Do NOT call main() yourself.
12. The code MUST run without raising syntax errors or NameError.

TASK of the code you generate:
•	The variable starturl is provided to the program.
•	Fetch the quiz page at starturl
•	Extract the question from the page
•	Compute the correct answer
•	Infer the submit URL - steps give above
•	POST the answer using payload format given above
    Wait for the POST response
    Extract the next URL from the response
    Display the next URL
Return ONLY:

```python
# code here
```
"""

    try:
        generated_code = await cached_call_aipipe(prompt)
        globals_dict = {
        "starturl": starturl,          # dynamically passed
        "httpx": httpx,
        "re": re,
        "BeautifulSoup": BeautifulSoup,
        "__name__": "__main__",
        "asyncio": asyncio
    }   
         # Replace placeholder URLs
        placeholders = [
            "<the quiz URL>", "<the quiz URL you fetched>",
             "<quiz url>", "<quiz_url>", "YOUR_START_URL_HERE","https://example.com/quiz","your_quiz_page_url_here"
        ]
        for ph in placeholders:
            generated_code = generated_code.replace(ph, starturl)
   

        print("hi ",generated_code)
    except Exception as e:
        print(f"[ERROR] LLM call failed: {e}")
        return

    #valid_codes = extract_valid_code_blocks(generated_code)
    #if ot valid_codes:
    #   print("[ERROR] No valid Python code extracted from AI response.")
    #   return

        try:
           #print(f"[INFO] Executing code block {idx+1}/{len(generated_code
            await run_code_safely(generated_code, starturl)
        except Exception as e:
            print(f"[ERROR] Execution failed in block {idx+1}: {e}")

    print("[INFO] All code blocks executed successfully")

# ------------------------
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


