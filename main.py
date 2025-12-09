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

    # 2. Call Gemini API
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

    # --- UPDATED STRATEGY: HARDCODED SAFE MODELS ---
    # We explicitly list trusted models. 
    # 'flash' is fast and high-quota. 'pro' is smarter but lower quota.
    trusted_models = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-1.0-pro"]
    
    proposal_text = ""
    success = False
    last_error = ""

    for model_name in trusted_models:
        if success: break
        
        print(f"--- Attempting generation with: {model_name} ---")
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            proposal_text = response.text
            success = True
            print(f"Success with {model_name}!")
            
        except Exception as e:
            error_str = str(e)
            last_error = error_str
            print(f"Failed with {model_name}. Error: {error_str}")
            
            # If it's a 429 (Busy) or 404 (Not Found), we continue to the next model.
            # If it is a 400 (Bad Request), we stop because the input is likely wrong.
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                print("Model busy/exhausted. Switching to next model...")
                time.sleep(1) # Brief pause before switching
                continue
            elif "404" in error_str or "NOT_FOUND" in error_str:
                print("Model not found. Switching...")
                continue
            else:
                # Critical error (e.g., API key invalid)
                raise HTTPException(status_code=500, detail=f"Gemini API Error: {error_str}")

    if not success:
        # If we tried all models and failed
        raise HTTPException(
            status_code=429, 
            detail=f"All AI models are currently busy or exhausted. Last error: {last_error}"
        )

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