import os
import re
import time
import base64
import datetime
from pathlib import Path
from google import genai
from app.core.pdf_generator import generate_pdf_from_html

def generate_declaration_for_requirement(
    description: str,
    user_custom_text: str,
    company_name: str,
    tender_no: str,
    user_inputs: dict,
    output_pdf_path: Path
) -> Path:
    """
    Generates a formal legal declaration PDF for an IREPS tender requirement,
    incorporating the requirement description and any custom user input,
    with company signatory details and Place as Ahmedabad.
    """
    from app.internal.intake.intake import load_company_data, get_signature_path
    
    company_data = load_company_data(company_name)
    company = company_data.get("company", {})
    signatory = company_data.get("signatory", {})
    
    c_lower = str(company_name).lower()
    if "arkon" in c_lower:
        company_display = user_inputs.get("company_name") or company.get("legal_name") or "ARKONIK FIBERTECH INDIA PRIVATE LIMITED"
        sig_name = user_inputs.get("signatory_name") or signatory.get("name") or "DHARAMRAJSINH NARENDRASINH VAGHELA"
        sig_desig = user_inputs.get("signatory_designation") or signatory.get("designation") or "Managing Director"
    else:
        company_display = user_inputs.get("company_name") or company.get("legal_name") or "AQUINT INFRATELE INDIA PRIVATE LIMITED"
        sig_name = user_inputs.get("signatory_name") or signatory.get("name") or "BHARGAV NARENDRABHAI PRAJAPATI"
        sig_desig = user_inputs.get("signatory_designation") or signatory.get("designation") or "Director"

    date_val = user_inputs.get("closing_date") or user_inputs.get("date") or datetime.date.today().strftime('%d/%m/%Y')
    place_val = "Ahmedabad"
    
    sig_path = get_signature_path(company_name, sig_name)
    img_src = ""
    if sig_path and Path(sig_path).exists():
        try:
            b64_sig = base64.b64encode(Path(sig_path).read_bytes()).decode('utf-8')
            img_src = f"data:image/jpeg;base64,{b64_sig}"
        except Exception:
            pass
            
    issuing_auth = user_inputs.get("issuing_authority") or user_inputs.get("railway", "")
    railway_val = user_inputs.get("railway") or issuing_auth
    t_name = user_inputs.get("tender_name", "")
    
    user_custom_clean = (user_custom_text or "").strip()
    if user_custom_clean:
        instruction_mode = f"""
    USER-SPECIFIED DECLARATION CONTENT / SPECIAL INSTRUCTIONS:
    The bidder has provided the following specific text, clauses, or instructions for this declaration:
    \"\"\"{user_custom_clean}\"\"\"
    
    CRITICAL INSTRUCTION FOR USER CONTENT:
    - You MUST integrate, reflect, and weave the user's specific written content, clauses, and statements directly into the declaration.
    - Ensure all key points mentioned by the user are fully articulated in formal, professional legal drafting alongside the requirement fulfillment.
        """
    else:
        instruction_mode = """
    NO CUSTOM TEXT WRITTEN BY USER:
    The user has selected Declaration for this requirement without providing additional custom text.
    
    CRITICAL INSTRUCTION:
    - Draft a complete, formal, affirmative declaration / undertaking in a proper, positive, and unconditional tone that 100% fulfills and satisfies the requirement.
    - Frame the declaration affirmatively: "We hereby solemnly declare, undertake, and confirm that [Company Name] unconditionally affirms and undertakes that..."
    - Adopt the exact subject matter of the requirement in a positive, proactive legal commitment (e.g., confirming due and faithful performance, confirming no addition/deletion, confirming non-blacklisting, certifying non-relation, confirming compliance, etc.).
    - Do NOT leave any fill-in blanks, underscores (like '_____', '......', or '[Insert ...]'), or placeholders.
        """

    prompt = f"""
    You are an expert procurement attorney drafting a formal, legally binding Declaration / Undertaking document on behalf of the bidder for a public procurement tender.
    
    Tender Number: {tender_no}
    Tender Name / Work: {t_name}
    Issuing Authority / Client: {issuing_auth}
    Bidder Company: {company_display}
    Registered Address: {company.get("registered_address", "Ahmedabad, Gujarat, India")}
    Authorized Signatory: {sig_name} ({sig_desig})
    Date: {date_val}
    Place: {place_val}
    
    MANDATORY REQUIREMENT TO SATISFY:
    "{description}"
    
    {instruction_mode}
    
    DRAFTING INSTRUCTIONS:
    1. Title: Create a bold, professional, centered title (e.g. "DECLARATION / UNDERTAKING", "UNDERTAKING FOR DUE PERFORMANCE OF CONTRACT", "DECLARATION REGARDING ...", "COMPLIANCE UNDERTAKING").
    2. Addressee: Address formally To: The Competent Authority, {issuing_auth}.
    3. Subject Line: Reference Tender No. {tender_no} and Tender Name.
    4. Positive Legal Tone:
       - State clearly and affirmatively that the bidder solemnly undertakes, declares, affirms, and commits in full compliance with the requirement.
       - The tone must be affirmative, confident, professional, and legally binding.
    5. NO BLANKS OR PLACEHOLDERS:
       - NEVER use blank fill-in lines like '_____', '......', or '[Insert date]'. All necessary details (Company Name, Signatory, Tender Number, Authority, Date, Place) are provided above. Use them directly.
    6. Output format: Pure HTML only. Do NOT include ```html markdown fences.
    7. Typography: Clean modern styling, Arial/sans-serif, font-size 13px, line-height 1.6, clean paragraphs with text-align: justify.
    8. CRITICAL: Do NOT include a closing signature box at the bottom (Authorized Signatory / Date / Place). That will be appended programmatically at the bottom.
    9. CRITICAL: Do NOT use <hr> tags or web borders. Make it look like a formal typed legal declaration ready for official submission.
    """

    import app.core.config as config
    api_key = config.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")
    body_html = ""
    if api_key:
        client = genai.Client(api_key=api_key)
        models = ['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite', 'gemini-3.6-flash', 'gemini-3.5-flash']
        for model_name in models:
            try:
                resp = client.models.generate_content(model=model_name, contents=prompt)
                if resp and resp.text:
                    body_html = resp.text.strip()
                    if body_html:
                        break
            except Exception:
                time.sleep(1)
            
    if not body_html:
        # Fallback template if Gemini unavailable
        custom_p = f"<p style='margin-top:14px; background:#f8fafc; padding:10px; border-left:3px solid #2563eb;'><b>Specific Bidder Undertaking / Statement:</b><br>{user_custom_clean}</p>" if user_custom_clean else ""
        body_html = f"""
        <div style="text-align: center; font-weight: bold; font-size: 16px; margin-bottom: 25px; text-decoration: underline;">
            DECLARATION AND COMPLIANCE UNDERTAKING
        </div>
        <p>To,</p>
        <p><b>The Competent Authority,</b><br>{issuing_auth}</p>
        <p style="margin-top: 15px;"><b>Sub:</b> Declaration and Compliance Undertaking with respect to Tender No. <b>{tender_no}</b> - {t_name}.</p>
        <p style="margin-top: 15px;"><b>Requirement:</b> {description}</p>
        <p style="margin-top: 15px;">
            We, <b>{company_display}</b>, having our registered office at {company.get("registered_address", "Ahmedabad, Gujarat")}, 
            do hereby solemnly affirm, declare, and undertake that we fully, strictly, and unconditionally agree to and comply with the aforesaid requirement in all respects.
        </p>
        {custom_p}
        <p style="margin-top: 15px;">
            We confirm that the statements, undertakings, and declarations furnished herein are true, correct, positive, and legally binding upon our company, its directors, and successors.
        </p>
        """

    if body_html.startswith("```html"):
        body_html = body_html[7:]
    if body_html.startswith("```"):
        body_html = body_html[3:]
    if body_html.endswith("```"):
        body_html = body_html[:-3]

    # Programmatic Signature and Date/Place Block (Place is ALWAYS Ahmedabad)
    sig_img_html = f'<img src="{img_src}" width="130" style="margin: 6px 0; display: block;" />' if img_src else '<div style="height: 45px;"></div>'
    
    full_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        @page {{
            size: A4;
            margin: 25mm 20mm 25mm 20mm;
        }}
        body {{
            font-family: Arial, Helvetica, sans-serif;
            font-size: 13px;
            color: #111;
            line-height: 1.6;
            margin: 0;
            padding: 0;
        }}
        p {{
            margin: 0 0 12px 0;
            text-align: justify;
        }}
        b, strong {{
            color: #000;
        }}
    </style>
</head>
<body>
    <div style="min-height: 650px;">
        {body_html}
    </div>
    <div style="margin-top: 30px; display: table; width: 100%; font-size: 13px; page-break-inside: avoid;">
        <div style="display: table-cell; width: 50%; vertical-align: top; text-align: left;">
            <b>Date:</b> {date_val}<br>
            <b>Place:</b> {place_val}
        </div>
        <div style="display: table-cell; width: 50%; vertical-align: top; text-align: right;">
            <div style="display: inline-block; text-align: left;">
                <b>For and on behalf of:</b><br>
                <b>{company_display}</b><br>
                {sig_img_html}
                <b>Authorized Signatory:</b> {sig_name}<br>
                <b>Designation:</b> {sig_desig}
            </div>
        </div>
    </div>
</body>
</html>"""

    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    generate_pdf_from_html(full_html, str(output_pdf_path))
    return output_pdf_path
