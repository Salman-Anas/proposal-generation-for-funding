import os
import time
import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response
import google.generativeai as genai
from fpdf import FPDF
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI(title="Gemini Funding Proposal Generator")

# Configure Gemini
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY is missing in environment variables")
genai.configure(api_key=api_key)

# --- NEW: Dynamic Model Selector ---
def get_working_model():
    """
    Dynamically finds a model that supports generateContent.
    Prioritizes Flash -> Pro -> Any.
    """
    print("Listing available models...")
    try:
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        print(f"Found models: {available_models}")

        # Priority List
        # We strip 'models/' prefix if present for matching, but keep full name for usage
        for model_id in available_models:
            if "gemini-1.5-flash" in model_id:
                return model_id
        for model_id in available_models:
            if "gemini-1.5-pro" in model_id:
                return model_id
        for model_id in available_models:
            if "gemini-pro" in model_id:
                return model_id
                
        # Fallback to the first available one if nothing matches preferences
        if available_models:
            return available_models[0]
            
        raise Exception("No models found that support generateContent.")
        
    except Exception as e:
        print(f"Error listing models: {e}")
        # Ultimate fallback if list_models fails (rare)
        return "models/gemini-1.5-flash"

# Set the model globally on startup
ACTIVE_MODEL_NAME = get_working_model()
print(f"--- SELECTED MODEL: {ACTIVE_MODEL_NAME} ---")

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

@app.post("/generate-proposal/")
async def generate_proposal(report_text: str = None, file: UploadFile = File(None)):
    
    # 1. Extract Content
    content = ""
    if file:
        content_bytes = await file.read()
        content = content_bytes.decode("utf-8")
    elif report_text:
        content = report_text
    else:
        raise HTTPException(status_code=400, detail="Please provide report_text or upload a file.")

    # 2. Call Gemini API using the Auto-Detected Model
    prompt = f"""
    You are a professional grant writer. 
    Take the following feasibility report and rewrite it into a formal, highly professional Funding Proposal.
    
    Structure it clearly with these sections (do not use Markdown formatting like ** or ##, just use plain text with capitalization for headers):
    1. EXECUTIVE SUMMARY
    2. PROJECT BACKGROUND
    3. OBJECTIVES
    4. METHODOLOGY
    5. BUDGET OVERVIEW
    6. EXPECTED OUTCOMES
    
    FEASIBILITY REPORT CONTENT:
    {content}
    """

    max_retries = 3
    base_delay = 100
    
    # Use the globally selected model
    model = genai.GenerativeModel(ACTIVE_MODEL_NAME)

    proposal_text = ""
    
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            proposal_text = response.text
            break
        except Exception as e:
            print(f"printing exception1 {e}")
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                if attempt < max_retries - 1:
                    # New wait times will be: 20s, 40s.
                    wait_time = base_delay * (attempt + 1) 
                    print(f"Rate limit hit. Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    raise HTTPException(status_code=429, detail="Server is busy. Please try again later.")
            else:
                raise HTTPException(status_code=500, detail=f"Gemini API Error: {error_str}")

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