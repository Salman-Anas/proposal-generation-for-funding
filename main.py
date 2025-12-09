import os
import time
import requests
import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response
from fpdf import FPDF
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI(title="Gemini Funding Proposal Generator")

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("GEMINI_API_KEY is missing in environment variables")

class ProposalPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 15)
        self.cell(0, 10, "Project Funding Proposal", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

def generate_pdf_from_text(text_content: str) -> bytes:
    pdf = ProposalPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    # Sanitize text for PDF (replace unsupported characters)
    safe_text = text_content.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 10, text=safe_text)
    return pdf.output()

def call_gemini_direct(prompt: str):
    """
    Calls Gemini API directly via HTTP, bypassing the Python SDK.
    Tries multiple model versions to ensure success.
    """
    
    # We try these models in order. 
    # 'gemini-1.5-flash' is the standard fast model.
    # 'gemini-1.5-pro' is the smart backup.
    # 'gemini-pro' is the legacy backup.
    models = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro"]
    
    last_error = ""

    for model in models:
        print(f"--- Trying Direct API: {model} ---")
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={API_KEY}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            
            # Check for HTTP 200 OK
            if response.status_code == 200:
                data = response.json()
                try:
                    # Extract text from JSON response
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError):
                    # Sometimes response is 200 but content is blocked/empty
                    print(f"Model {model} returned 200 but no text. JSON: {data}")
                    last_error = f"Model {model} returned empty response."
                    continue

            # Handle 429 (Rate Limit) explicitly
            elif response.status_code == 429:
                print(f"Model {model} is Busy (429). Switching...")
                last_error = "Rate Limit Exceeded"
                time.sleep(1) # Short breath
                continue
                
            # Handle 404 (Model not found for this key)
            elif response.status_code == 404:
                print(f"Model {model} not found (404). Switching...")
                last_error = f"Model {model} not found"
                continue
            
            else:
                # Other errors (500, 400, etc)
                print(f"Model {model} failed with status {response.status_code}: {response.text}")
                last_error = f"HTTP {response.status_code}: {response.text}"
                continue

        except Exception as e:
            print(f"Connection error with {model}: {str(e)}")
            last_error = str(e)
            continue
            
    # If loop finishes without returning, we failed.
    raise Exception(f"All models failed. Last error: {last_error}")

@app.post("/generate-proposal/")
# Note: Removed 'async' to allow synchronous requests library to run smoothly
def generate_proposal(report_text: str = None, file: UploadFile = File(None)):
    
    # 1. Extract Content
    content = ""
    try:
        if file:
            content_bytes = file.file.read() # Synchronous read
            content = content_bytes.decode("utf-8")
        elif report_text:
            content = report_text
        else:
            raise HTTPException(status_code=400, detail="Please provide report_text or upload a file.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading file: {str(e)}")

    # 2. Call Gemini (Direct HTTP Method)
    prompt = f"""
    You are a professional grant writer. 
    Take the following feasibility report and rewrite it into a formal Funding Proposal.
    Keep it strictly text-based (no markdown bold/italic) for PDF compatibility.
    
    Sections:
    1. EXECUTIVE SUMMARY
    2. PROJECT BACKGROUND
    3. OBJECTIVES
    4. METHODOLOGY
    5. BUDGET OVERVIEW
    6. EXPECTED OUTCOMES
    
    REPORT:
    {content[:10000]} 
    """
    # Note: I limited input to 10k chars to prevent token errors

    try:
        proposal_text = call_gemini_direct(prompt)
    except Exception as e:
        # Return the exact error to the user so we can see it
        raise HTTPException(status_code=500, detail=f"AI Generation Failed: {str(e)}")

    # 3. Generate PDF
    try:
        pdf_bytes = generate_pdf_from_text(proposal_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF Generation Error: {str(e)}")

    return Response(
        content=bytes(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=funding_proposal.pdf"}
    )

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))