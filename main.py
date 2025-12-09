import os
import time
import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response
import google.generativeai as genai  # CHANGED: Standard library
from fpdf import FPDF
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI(title="Gemini Funding Proposal Generator")

# Configure Gemini (Standard Method)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

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
    
    # fpdf2 handles unicode cleanup
    safe_text = text_content.encode('latin-1', 'replace').decode('latin-1')
    
    pdf.multi_cell(0, 10, text=safe_text)
    return pdf.output()

@app.post("/generate-proposal/")
async def generate_proposal(report_text: str = None, file: UploadFile = File(None)):
    """
    Send raw text OR upload a text/markdown file.
    """
    
    # 1. Extract Content
    content = ""
    if file:
        content_bytes = await file.read()
        content = content_bytes.decode("utf-8")
    elif report_text:
        content = report_text
    else:
        raise HTTPException(status_code=400, detail="Please provide report_text or upload a file.")

    # 2. Call Gemini API (Updated for google-generativeai)
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
    base_delay = 5
    
    # Initialize the model - 1.5-flash is stable here
    model = genai.GenerativeModel("gemini-1.5-flash") 

    proposal_text = ""
    
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            proposal_text = response.text
            break
        except Exception as e:
            error_str = str(e)
            # Check for Rate Limits (429)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                if attempt < max_retries - 1:
                    wait_time = base_delay * (2 ** attempt)
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