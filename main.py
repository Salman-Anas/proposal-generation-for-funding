import os
import time 
import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response
from google import genai
from fpdf import FPDF
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI(title="Gemini Funding Proposal Generator")

# Initialize Gemini Client
# Make sure GEMINI_API_KEY is set in your environment
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

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
    
    # fpdf2 handles unicode and wrapping much better than old fpdf
    # We clean the text slightly to ensure compatibility
    safe_text = text_content.encode('latin-1', 'replace').decode('latin-1')
    
    pdf.multi_cell(0, 10, text=safe_text)
    return pdf.output()

@app.post("/generate-proposal/")
async def generate_proposal(report_text: str = None, file: UploadFile = File(None)):
    """
    Send raw text OR upload a text/markdown file.
    Includes retry logic for 429 errors.
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

    # 2. Call Gemini API with Retry Logic
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
    base_delay = 5  # seconds

    proposal_text = ""
    
    for attempt in range(max_retries):
        try:
            # We switched to 1.5-flash here for better availability
            response = client.models.generate_content(
                model="gemini-1.5-flash", 
                contents=prompt
            )
            proposal_text = response.text
            break # Success, exit loop
        except Exception as e:
            # Check if it's a 429 error (Resource Exhausted)
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                if attempt < max_retries - 1:
                    wait_time = base_delay * (2 ** attempt) # Exponential backoff: 5s, 10s, 20s
                    print(f"Rate limit hit. Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    raise HTTPException(status_code=429, detail="Server is busy (Rate Limit Exceeded). Please try again later.")
            else:
                # If it's another error, fail immediately
                raise HTTPException(status_code=500, detail=f"Gemini API Error: {error_str}")

    # 3. Generate PDF
    try:
        pdf_bytes = generate_pdf_from_text(proposal_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF Generation Error: {str(e)}")

    # 4. Return the file
    return Response(
        content=bytes(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=funding_proposal.pdf"}
    )

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))