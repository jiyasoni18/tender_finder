import re
from google import genai
from config import GEMINI_API_KEY
from core.models import TenderDoc
from core.logging_setup import get_logger

log = get_logger("summarize")

PROMPT_TEMPLATE = """
You are a Strategic Tender Analyst for Indian Railways / Government tenders.
Read the tender document text below and produce a "STRATEGIC TENDER ANALYSIS & BID ADVISORY REPORT".

Return ONLY valid HTML — no markdown, no code fences, nothing outside the HTML tags.

Use this EXACT HTML structure and section numbering. Use <table> elements for tabular data.
Wrap sections 1-3 inside <div id="short-report-content"> and sections 4-12 inside <div id="long-report-content">.

At the very top (before everything else), include a hidden 2-line scope summary:
<div id="short-summary" style="display:none;">YOUR 2-LINE SCOPE SUMMARY HERE</div>

The 12 sections must be:
1. TENDER OVERVIEW — table with: Tender No, Zone/Division/Department, Name of Work, Tender Type, Bidding Type, Date of Uploading, Bidding Start Date, Closing Date/Time, Pre-Bid Conference, Advertised Value (ECV), EMD, Tender Document Cost, Period of Completion, Validity of Offer, Contract Type, Bidding Style/Unit, JV/Consortium Allowed, Ranking Order for Bids
2. SCOPE OF WORK — exactly 2-3 sentences describing the actual work.
3. FINANCIAL SUMMARY — table with: ECV, EMD, Document Cost, EMD as % of ECV.
4. SCHEDULE OF RATES — ITEM BREAKUP — table with S.No, Item Description, Qty, Unit, Unit Rate (Rs.), Basic Value (Rs.)
5. TECHNICAL SPECIFICATIONS & COMPLIANCE — bullet list of key standards and specs.
6. SPECIAL CONDITIONS & ATTACHMENTS — bullet list of key special conditions.
7. BID ANALYSIS & MARKET INTELLIGENCE — paragraph analysis of market conditions.
8. COMPETITOR INTELLIGENCE — paragraph about likely competitors.
9. BID STRATEGY & RECOMMENDATION — three sub-sections: Aggressive Estimate, Moderate Estimate, Conservative Estimate, then a General Recommendation.
10. RISK ASSESSMENT — three risks: Competition Risk, Execution Risk, Cost Escalation Risk. Each with a Mitigation line.
11. MANDATORY SUBMISSION CHECKLIST — Extract EVERY document explicitly required in the tender text for bid submission. Present as a numbered list. Include document name, format (if specified), and any size/validity requirements. If the PDF lists specific forms, certificates, or declarations by name — list each one exactly as stated. Do NOT use generic placeholders; only list what is actually mentioned in the provided text.
12. HOW & WHERE TO APPLY — Extract from the tender text: the exact portal name and URL where bids must be submitted (e.g. IREPS, GeM, CPP Portal, TenderDetail, etc.), any login/registration steps mentioned, the submission mode (online/offline/both), and any important submission instructions. If a specific URL is mentioned in the text, include it verbatim.

Provide your best professional estimation for sections where the tender text doesn't have explicit data.

Tender metadata:
- ID: {doc_id}
- Source: {source}
- Value: {value}
- Closing Date: {closing_date}
- Detail URL: {detail_url}

Extracted tender text:
-----------------------
{pdf_text}
-----------------------
"""



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

    prompt = PROMPT_TEMPLATE.format(
        doc_id=doc.doc_id,
        source=doc.source,
        value=doc.value,
        closing_date=getattr(doc, 'closing_date', 'N/A'),
        detail_url=getattr(doc, 'detail_url', ''),
        pdf_text=pdf_text[:15000],
    )

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
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
