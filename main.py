import os
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

# --- PDF Class ---
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
    safe_text = text_content.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 10, text=safe_text)
    return pdf.output()

# --- NEW: Dynamic Model Finder ---
def find_best_model():
    """
    Asks Google API: 'What models can I use?'
    Returns the full name of the best available model (e.g., 'models/gemini-1.5-flash-001')
    """
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}"
    print("--- Discovery: Finding available models... ---")
    
    try:
        response = requests.get(list_url, timeout=10)
        if response.status_code != 200:
            print(f"Discovery Failed: {response.text}")
            return None
            
        data = response.json()
        models = data.get('models', [])
        
        # We only want models that can 'generateContent'
        usable_models = [m for m in models if 'generateContent' in m.get('supportedGenerationMethods', [])]
        
        if not usable_models:
            print("No usable models found.")
            return None

        print(f"Found {len(usable_models)} models. Selecting best one...")
        
        # Priority Logic: Flash -> 1.5 Pro -> Any Pro
        for m in usable_models:
            if "flash" in m['name']: return m['name']
        for m in usable_models:
            if "1.5-pro" in m['name']: return m['name']
        
        # Fallback: Just take the first one
        return usable_models[0]['name']

    except Exception as e:
        print(f"Discovery Error: {e}")
        return None

# --- Main Generation Logic ---
def call_gemini_dynamic(prompt: str):
    
    # 1. Find the model dynamically
    model_name = find_best_model()
    
    if not model_name:
        # Emergency Fallback if discovery fails
        model_name = "models/gemini-1.5-flash"
        print("Discovery failed. Forcing fallback to gemini-1.5-flash")

    print(f"--- Generating using model: {model_name} ---")

    # 2. Construct URL (model_name already includes 'models/')
    # If the discovered name is "models/gemini-1.5-flash", URL becomes:
    # https://.../v1beta/models/gemini-1.5-flash:generateContent
    url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={API_KEY}"
    
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        
        if response.status_code == 200:
            data = response.json()
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except Exception:
                raise Exception(f"Empty/Blocked Response: {data}")
        else:
            raise Exception(f"Gemini Error ({response.status_code}): {response.text}")

    except Exception as e:
        raise Exception(f"Connection Failed: {str(e)}")

@app.post("/generate-proposal/")
def generate_proposal(report_text: str = None, file: UploadFile = File(None)):
    
    # 1. Extract Content
    content = ""
    try:
        if file:
            content_bytes = file.file.read()
            content = content_bytes.decode("utf-8")
        elif report_text:
            content = report_text
        else:
            raise HTTPException(status_code=400, detail="Please provide report_text or upload a file.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading file: {str(e)}")

    # 2. Call Gemini
    prompt = f"""
    You are a professional grant writer. 
    Take the following feasibility report and rewrite it into a formal Funding Proposal.
    Keep it strictly text-based for PDF compatibility.
    
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

    try:
        proposal_text = call_gemini_dynamic(prompt)
    except Exception as e:
        # Return exact error for debugging
        raise HTTPException(status_code=500, detail=f"AI Error: {str(e)}")

    # 3. Generate PDF
    try:
        pdf_bytes = generate_pdf_from_text(proposal_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF Error: {str(e)}")

    return Response(
        content=bytes(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=funding_proposal.pdf"}
    )

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))