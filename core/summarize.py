import re
from google import genai
from config import GEMINI_API_KEY
from core.models import TenderDoc
from core.logging_setup import get_logger

log = get_logger("summarize")

def generate_tender_report(doc: TenderDoc, pdf_text: str) -> tuple[str, str]:
    """
    Calls Gemini API to generate a professional HTML report matching the user's required
    format (Strategic Tender Analysis & Bid Advisory), and extracts a 2-3 line summary.
    Returns (summary_text, html_report).
    """
    if not GEMINI_API_KEY:
        log.warning("GEMINI_API_KEY not set. Cannot generate summary.")
        return "", ""

    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
You are a Strategic Tender Analyst. Please read the following tender document text and extract the information required to build a "STRATEGIC TENDER ANALYSIS & BID ADVISORY" report.

Return your response ONLY as valid HTML. The HTML should have a very professional, corporate design with dark blue headers (#1d3a6d), light blue table borders, and striped rows for data. 

The HTML must contain exactly these 11 sections, formatted as clean HTML tables or structured sections. 
CRITICAL: You must wrap Sections 1, 2, and 3 inside `<div id="short-report-content">` and wrap Sections 4 through 11 inside `<div id="long-report-content">`.

<div id="short-report-content">
1. TENDER OVERVIEW (Tender No, Zone / Division / Department, Name of Work, Tender Type, Bidding Type, Date of Uploading, Bidding Start Date, Closing Date / Time, Pre-Bid Conference, Advertised Value (ECV), EMD, Tender Document Cost, Period of Completion, Validity of Offer, Contract Type, Bidding Style / Unit, JV / Consortium Allowed, Ranking Order for Bids)
2. SCOPE OF WORK (Provide a 2-3 line concise summary of the actual work to be done. Make sure this is exactly 2-3 lines.)
3. FINANCIAL SUMMARY (ECV, EMD, Doc Cost, EMD as % of ECV)
</div>

<div id="long-report-content">
4. SCHEDULE OF RATES — ITEM BREAKUP (List the top few important items if the list is huge)
5. TECHNICAL SPECIFICATIONS & COMPLIANCE
6. SPECIAL CONDITIONS & ATTACHMENTS
7. BID ANALYSIS & MARKET INTELLIGENCE (Synthesize from text if available)
8. COMPETITOR INTELLIGENCE (Synthesize from text if available)
9. BID STRATEGY & RECOMMENDATION (Provide aggressive, moderate, conservative estimates)
10. RISK ASSESSMENT (Competition Risk, Execution Risk, Cost Escalation Risk)
11. MANDATORY SUBMISSION CHECKLIST
</div>

Since some of this intelligence (like Competitor Intelligence) might not be explicitly in the tender text, provide your best professional estimation or standard boilerplate tailored to the scope of work.

Finally, at the very beginning of the HTML, wrap the 2-3 line SCOPE OF WORK summary inside a hidden div like this: `<div id="short-summary" style="display:none;">YOUR 2-3 LINE SUMMARY HERE</div>`.

Here are the Tender details from our scraper:
ID: {doc.doc_id}
Source: {doc.source}
Value: {doc.value}
Closing: {doc.closing_date}

Here is the extracted PDF text:
-----------------------
{pdf_text[:30000]}
-----------------------
"""
    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
        )
        html_content = response.text
        
        # Clean up Markdown code blocks if Gemini added them
        html_content = re.sub(r"^```(?:html)?\s*", "", html_content, flags=re.MULTILINE)
        html_content = re.sub(r"```\s*$", "", html_content, flags=re.MULTILINE)
        
        # Extract the short summary
        summary = ""
        match = re.search(r'<div id="short-summary"[^>]*>(.*?)</div>', html_content, re.IGNORECASE | re.DOTALL)
        if match:
            summary = match.group(1).strip()
            
        return summary, html_content
    except Exception as e:
        log.error("Failed to generate report using Gemini: %s", e)
        return "", ""
