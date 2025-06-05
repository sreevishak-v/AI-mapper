import fitz  # PyMuPDF
import re
import json
from typing import Dict, Tuple, List
from collections import defaultdict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def parse_pdf(file_path: str) -> Dict:
    logger.info(f"Parsing PDF: {file_path}")
    doc = fitz.open(file_path)
    data = defaultdict(dict)
    full_text = []
    tables = []
    current_section = None
    current_subsection = None
    current_field = None
    benefits_data = defaultdict(lambda: defaultdict(dict))
    procedure_codes = defaultdict(dict)
    last_key = None
    partial_key = ""
    current_services = ""

    try:
        for page in doc:
            blocks = page.get_text("blocks")
            blocks.sort(key=lambda block: (block[1], block[0]))
            for block in blocks:
                text = block[4].strip()
                if not text:
                    continue
                full_text.append(text)
                logger.debug(f"Processing block: {text}")
                if text.isupper() or any(keyword in text.lower() for keyword in ["patient detail", "plan and network", "plan details", "frequency & limitations", "benefits", "procedure code search"]):
                    current_section = text.strip().title()
                    logger.debug(f"Detected section: {current_section}")
                    if current_section.lower() == "benefits":
                        logger.debug(f"Full text of Benefits section: {text}")
                    current_subsection = None
                    current_field = None
                    partial_key = ""
                    last_key = None
                    current_services = ""
                    continue
                if current_section and current_section.lower() == "benefits":
                    if partial_key and not text.startswith("  ") and not text.lower().startswith("total:") and not re.match(r'^\$\d+[\d,.]*$', text):
                        if last_key:
                            benefits_data[current_subsection or "General"][last_key] = {"Text": partial_key.strip()}
                            logger.debug(f"Completed multi-line key: {last_key} = {partial_key.strip()}")
                        partial_key = ""

                    if text.lower() == "benefit maximums":
                        current_subsection = "Benefit Maximums"
                        current_field = None
                        current_services = ""
                        logger.debug(f"Detected subsection: {current_subsection}")
                        continue
                    elif text.lower() == "orthodontics" and current_subsection == "Benefit Maximums":
                        benefits_data[current_subsection]["Orthodontics"] = {}
                        current_field = None
                        current_services = ""
                        logger.debug(f"Detected Orthodontics under Benefit Maximums")
                        continue

                    service_pattern = r"^(Diagnostic and Preventive|Basic Restorative|Major Restorative|Orthodontics)(?:,\s*(?:Diagnostic and Preventive|Basic Restorative|Major Restorative|Orthodontics))*$"
                    if re.match(service_pattern, text) and not text.lower().startswith("total:"):
                        current_services = text.strip()
                        logger.debug(f"Captured services: {current_services}")
                        continue

                    if "deductible remaining" in text.lower() and current_subsection != "Benefit Maximums":
                        current_subsection = "Deductible"
                        if current_services:
                            benefits_data[current_subsection]["Services"] = current_services
                            logger.debug(f"Inferred Deductible subsection with services: {current_services}")
                        current_services = ""

                    if not text.startswith("  "):
                        remaining_match = re.match(r"^(.*)\s+remaining\s*[:]\s*(\$\d+[\d,.]*)$", text)
                        if remaining_match:
                            current_field = remaining_match.group(1).strip()
                            if current_subsection == "Benefit Maximums" and "Orthodontics" in benefits_data[current_subsection]:
                                benefits_data[current_subsection]["Orthodontics"][current_field] = {
                                    "Remaining": remaining_match.group(2)
                                }
                            else:
                                benefits_data[current_subsection or "General"][current_field] = {
                                    "Remaining": remaining_match.group(2)
                                }
                            last_key = current_field
                            logger.debug(f"Detected benefits field with remaining: {current_field}, Remaining: {remaining_match.group(2)}")
                        elif re.match(r'^\$\d+[\d,.]*$', text):
                            continue
                        else:
                            current_field = text.strip()
                            if not current_field.startswith("Total:"):
                                benefits_data[current_subsection or "General"][current_field] = {}
                                last_key = current_field
                                partial_key = current_field
                                logger.debug(f"Detected benefits field: {current_field}")
                            continue
                    if current_field:
                        if text.startswith("  "):
                            kv = extract_insurance_kv(text.strip())
                            if kv:
                                key, value = kv
                                if current_subsection == "Benefit Maximums" and "Orthodontics" in benefits_data[current_subsection]:
                                    benefits_data[current_subsection]["Orthodontics"][current_field][key] = value
                                else:
                                    benefits_data[current_subsection or "General"][current_field][key] = value
                                logger.debug(f"Extracted subfield for {current_field}: {key} = {value}")
                                continue
                        elif text.lower().startswith("total:"):
                            match = re.match(r"^Total\s*[:]\s*(\$\d+[\d,.]*)$", text)
                            if match:
                                if current_subsection == "Benefit Maximums" and "Orthodontics" in benefits_data[current_subsection]:
                                    benefits_data[current_subsection]["Orthodontics"][current_field]["Total"] = match.group(1)
                                else:
                                    benefits_data[current_subsection or "General"][current_field]["Total"] = match.group(1)
                                logger.debug(f"Extracted Total for {current_field}: {match.group(1)}")
                                current_field = None
                                last_key = None
                        else:
                            partial_key += " " + text.strip()
                            continue
                elif current_section and current_section.lower() == "procedure code search":
                    # Handle CDT codes
                    cdt_match = re.match(r"^(D\d{4})\s*(.*?)(?=\n|$)", text, re.DOTALL)
                    if cdt_match:
                        code = cdt_match.group(1)
                        description = cdt_match.group(2).strip().replace("\n", " ")
                        current_field = f"{code} - {description}"
                        procedure_codes[current_field] = {}
                        last_key = current_field
                        partial_key = ""
                        logger.info(f"Detected CDT code: {current_field}")
                        continue
                    if current_field:
                        kv = extract_insurance_kv(text.strip())
                        if kv:
                            key, value = kv
                            # Combine multi-word keys like "History Not" and "Alternate benefit may"
                            if key in ["History Not", "Alternate benefit may", "Member"]:
                                if key == "History Not":
                                    procedure_codes[current_field]["History"] = f"Not {value}"
                                elif key == "Alternate benefit may":
                                    procedure_codes[current_field]["Note"] = f"Alternate benefit may {value}"
                                elif key == "Member":
                                    procedure_codes[current_field]["Member Responsibility"] = value
                            else:
                                procedure_codes[current_field][key] = value
                            logger.info(f"Extracted CDT subfield for {current_field}: {key} = {value}")
                            continue
                        else:
                            # Handle multi-line keys
                            partial_key += " " + text.strip()
                            continue
                kv = extract_insurance_kv(text)
                if kv:
                    key, value = kv
                    logger.debug(f"Extracted KV: {key} = {value}")
                    if current_section:
                        data[current_section][key] = value
                    else:
                        data[key] = value
            page_tables = extract_page_tables(page)
            tables.extend(page_tables)

        if partial_key and last_key:
            if current_section.lower() == "procedure code search":
                procedure_codes[last_key] = {"Text": partial_key.strip()}
            else:
                benefits_data[current_subsection or "General"][last_key] = {"Text": partial_key.strip()}
        if benefits_data:
            data["Benefits"] = dict(benefits_data)
        if procedure_codes:
            data["Procedure Codes"] = dict(procedure_codes)
            logger.info(f"Procedure Codes extracted: {json.dumps(dict(procedure_codes), indent=2)}")

        processed_data = {
            "patient_info": extract_patient_data(data),
            "plan_info": extract_plan_data(data),
            "benefits": extract_benefits_data(doc, data),
            "last_procedures": extract_procedure_dates(data),
            "procedure_codes": extract_procedure_codes(data),
            "raw_data": dict(data),
            "tables": tables,
            "full_text": "\n".join(full_text)
        }
        logger.debug(f"Raw parsed data: {json.dumps(processed_data, indent=2)}")
        return processed_data
    finally:
        doc.close()

def extract_insurance_kv(text: str) -> Tuple[str, str]:
    patterns = [
        (r"^(Remaining)\s*[:]\s*(\$\d+[\d,.]*)$", 1, 2),
        (r"^(Total)\s*[:]\s*(\$\d+[\d,.]*)$", 1, 2),
        (r"^([A-Z][A-Za-z0-9 \-/():]+)\s*[:]\s*(\$\d+[\d,.]*)\s*/\s*(\$\d+[\d,.]*)$", 1, 2),
        (r"^([A-Z][A-Za-z0-9 \-/():]+)\s*[:]\s*(.+)$", 1, 2),
        (r"^([A-Z][A-Za-z0-9 \-/():]+)\s{2,}(.+)$", 1, 2),
        (r"^(D\d{4})\s+(.+)$", 1, 2),
        (r"^([A-Z][A-Za-z ]+)\s+([\$%\d].*)$", 1, 2),
        (r"^([A-Z][A-Za-z0-9 \-/():]+)\s*[-]\s*(.+)$", 1, 2),
        (r"^\s*([A-Z][A-Za-z0-9 \-/():]+)\s*:\s*([^\n]+)$", 1, 2),
        (r"^(.*)\s+\$([\d,.]+)$", 1, 2),
        (r"^(.*)\s+(\d+%)$", 1, 2),
        (r"^([A-Z][A-Za-z ]+)\s+([A-Za-z0-9 ,/]+)$", 1, 2),
        (r"^(Other Insurance\?)\s+(.+)$", 1, 2),
        (r"^(Pretreatment review.*)$", 0, 1),
        (r"^(Family Max\. Remaining)\s*[:]\s*(\$\d+[\d,.]*)$", 1, 2),
        (r"^(Individual Max\. Remaining)\s*[:]\s*(\$\d+[\d,.]*)$", 1, 2),
        (r"^(Family Deductible Remaining)\s*[:]\s*(\$\d+[\d,.]*)$", 1, 2),
        (r"^(Individual Deductible Remaining)\s*[:]\s*(\$\d+[\d,.]*)$", 1, 2),
        (r"^(Family Maximum)\s*[:]\s*(\$\d+[\d,.]*)$", 1, 2),
        (r"^(Individual Maximum)\s*[:]\s*(\$\d+[\d,.]*)$", 1, 2),
        (r"^(Family Deductible)\s*[:]\s*(\$\d+[\d,.]*)$", 1, 2),
        (r"^(Individual Deductible)\s*[:]\s*(\$\d+[\d,.]*)$", 1, 2),
        (r"^(Family Calendar Year Maximum)\s*[:]\s*(\$\d+[\d,.]*)$", 1, 2),
        (r"^(Individual Calendar Year Maximum)\s*[:]\s*(\$\d+[\d,.]*)$", 1, 2),
        (r"^(Family Calendar Year Deductible)\s*[:]\s*(\$\d+[\d,.]*)$", 1, 2),
        (r"^(Individual Calendar Year Deductible)\s*[:]\s*(\$\d+[\d,.]*)$", 1, 2),
        (r"^(Family Maximum)\s*(\$\d+[\d,.]*)$", 1, 2),
        (r"^(Individual Maximum)\s*(\$\d+[\d,.]*)$", 1, 2),
        (r"^(Family Deductible)\s*(\$\d+[\d,.]*)$", 1, 2),
        (r"^(Individual Deductible)\s*(\$\d+[\d,.]*)$", 1, 2),
    ]
    for pattern, key_group, value_group in patterns:
        match = re.match(pattern, text, re.MULTILINE | re.DOTALL)
        if match:
            key = re.sub(r"\s+", " ", match.group(key_group).strip()) if key_group > 0 else match.group(1).strip()
            value = re.sub(r"\s+", " ", match.group(value_group).strip())
            return key, value
    return None

def extract_page_tables(page) -> List[Dict]:
    tables = []
    text = page.get_text("text")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    current_table = []
    headers = None
    benefits_table = []
    in_benefits_section = False

    for line in lines:
        if "benefits" in line.lower():
            in_benefits_section = True
            headers = ["Field", "Remaining", "Total"]
            logger.debug(f"Started benefits table extraction with headers: {headers}")
            continue
        if in_benefits_section:
            if re.search(r'\$\d+[\d,.]*', line):
                parts = re.split(r'\s{2,}', line.strip())
                if len(parts) >= 2:
                    field = parts[0].strip()
                    remaining = ""
                    total = ""
                    for part in parts[1:]:
                        if re.match(r'^\$\d+[\d,.]*$', part):
                            if not remaining:
                                remaining = part
                            else:
                                total = part
                    if remaining:
                        row = {"Field": field, "Remaining": remaining, "Total": total if total else ""}
                        benefits_table.append(row)
                        logger.debug(f"Extracted benefits table row: {row}")
            elif any(keyword in line.lower() for keyword in ["plan details", "frequency & limitations"]):
                in_benefits_section = False
                if benefits_table:
                    tables.append(benefits_table)
                    logger.debug(f"Benefits table: {benefits_table}")
                benefits_table = []
                continue

        if any(keyword in line.lower() for keyword in ["coinsurance", "frequency", "procedure", "code", "maximum", "deductible"]):
            headers = [h.strip() for h in re.split(r'\s{2,}|\t', line) if h.strip()]
            logger.debug(f"Table headers: {headers}")
            continue
        row = [c.strip() for c in re.split(r'\s{2,}|\t', line) if c.strip()]
        if headers and len(row) >= len(headers):
            row_dict = dict(zip(headers[:len(row)], row))
            current_table.append(row_dict)
        elif current_table:
            tables.append(current_table)
            current_table = []
            headers = None
    if current_table:
        tables.append(current_table)
    if benefits_table:
        tables.append(benefits_table)
        logger.debug(f"Benefits table: {benefits_table}")

    frequency_table = []
    in_frequency_section = False
    for line in lines:
        if "frequency & limitations" in line.lower():
            in_frequency_section = True
            headers = ["Procedure", "Frequency"]
            continue
        if in_frequency_section and re.match(r"^[A-Z][A-Za-z -]+.*(per|once|twice|exclude|no limitations)", line, re.IGNORECASE):
            parts = re.split(r'\s{2,}', line.strip(), 1)
            if len(parts) == 2:
                frequency_table.append({"Procedure": parts[0].strip(), "Frequency": parts[1].strip()})
            elif len(parts) == 1 and frequency_table:
                frequency_table[-1]["Frequency"] += " " + parts[0].strip()
        elif in_frequency_section and any(keyword in line.lower() for keyword in ["total", "plan details"]):
            in_frequency_section = False
    if frequency_table:
        tables.append(frequency_table)
        logger.debug(f"Frequency table: {frequency_table}")
    return tables

def extract_patient_data(data: Dict) -> Dict:
    patient = {}
    sections = ["Patient Detail", "Patient Details", "Patient Information", "Plan And Network"]
    for section in sections:
        if section in data:
            d = data[section]
            patient.update({
                "name": d.get("Name", "") or d.get("Patient Name", ""),
                "patient_id": d.get("Patient ID", ""),
                "date_of_birth": d.get("Date of Birth", "") or d.get("Subscriber Date of Birth", ""),
                "gender": d.get("Gender", ""),
                "subscriber_name": d.get("Subscriber", "") or d.get("Name", ""),
                "subscriber_id": d.get("Patient ID", ""),
                "subscriber_dob": d.get("Date of Birth", "") or d.get("Subscriber Date of Birth", ""),
                "relationship": d.get("Relationship", ""),
                "address": d.get("Address", "")
            })
            break
    logger.debug(f"Patient data: {patient}")
    return patient

def extract_plan_data(data: Dict) -> Dict:
    plan = {}
    sections = ["Plan and Network", "Plan Details", "Plan Information", "Jason'S Deli"]
    for section in sections:
        if section in data:
            d = data[section]
            plan.update({
                "plan_name": d.get("Plan Type", "") or d.get("Plan", ""),
                "group_number": d.get("Account #", "") or d.get("Group Number", ""),
                "insurance_type": d.get("Plan Type", "") or d.get("Plan", "") or d.get("Insurance Type", ""),
                "employer": d.get("Group Name", "") or d.get("Account Name", "") or d.get("Employer Name", ""),
                "plan_reset_date": d.get("Plan Renews", ""),
                "plan_type": d.get("Plan Type", ""),
                "benefits_coordination_method": d.get("Other Insurance?", "No") or d.get("Other Insurance", "No") or d.get("COB", "No"),
                "verified_date": d.get("Verification Date", "") or d.get("Verified Date", ""),
                "participation_type": d.get("Participation Type", "") or d.get("Network Type", "") or d.get("Participation", "")
            })
            break
    logger.debug(f"Plan data: {plan}")
    return plan

def validate_dollar_amount(value: str) -> str:
    if re.match(r'^\$\d+[\d,.]*$', value):
        return value
    logger.debug(f"Invalid dollar amount: {value}")
    return ""

def extract_benefits_data(doc: fitz.Document, data: Dict) -> Dict:
    benefits = {
        "deductible": {
            "individual": "",
            "family": "",
            "individual_remaining": "",
            "individual_total": "",
            "family_remaining": "",
            "family_total": ""
        },
        "maximum": {
            "individual": "",
            "family": "",
            "individual_remaining": "",
            "individual_total": "",
            "family_remaining": "",
            "family_total": ""
        },
        "coinsurance": extract_coinsurance(data),
        "frequencies": extract_frequencies(data),
        "pre_auth": extract_pre_auth(data)
    }

    logger.debug(f"Raw data sections: {json.dumps(dict(data), indent=2)}")

    for section in ["Benefits"]:
        if section in data:
            d = data[section]
            logger.debug(f"Processing section {section}: {d}")
            if "Deductible" in d:
                subsection = d["Deductible"]
                for key, subfields in subsection.items():
                    if isinstance(subfields, dict):
                        remaining = validate_dollar_amount(subfields.get("Remaining", ""))
                        total = validate_dollar_amount(subfields.get("Total", ""))
                        if "Individual Calendar Year Deductible" in key or "Individual Deductible" in key:
                            benefits["deductible"]["individual_remaining"] = remaining
                            benefits["deductible"]["individual_total"] = total
                            logger.debug(f"Extracted Individual Deductible: Remaining={remaining}, Total={total}")
                        elif "Family Calendar Year Deductible" in key or "Family Deductible" in key:
                            benefits["deductible"]["family_remaining"] = remaining
                            benefits["deductible"]["family_total"] = total
                            logger.debug(f"Extracted Family Deductible: Remaining={remaining}, Total={total}")
            if "Benefit Maximums" in d:
                subsection = d["Benefit Maximums"]
                for key, subfields in subsection.items():
                    if key == "Orthodontics":
                        ortho = subfields
                        for ortho_key, ortho_subfields in ortho.items():
                            remaining = validate_dollar_amount(ortho_subfields.get("Remaining", ""))
                            total = validate_dollar_amount(ortho_subfields.get("Total", ""))
                            if "Individual Lifetime Maximum" in ortho_key:
                                benefits["maximum"]["family_remaining"] = remaining
                                benefits["maximum"]["family_total"] = total
                                logger.debug(f"Extracted Family Maximum (Orthodontics): Remaining={remaining}, Total={total}")
                    elif isinstance(subfields, dict):
                        remaining = validate_dollar_amount(subfields.get("Remaining", ""))
                        total = validate_dollar_amount(subfields.get("Total", ""))
                        if "Individual Calendar Year Maximum" in key or "Individual Maximum" in key:
                            benefits["maximum"]["individual_remaining"] = remaining
                            benefits["maximum"]["individual_total"] = total
                            logger.debug(f"Extracted Individual Maximum: Remaining={remaining}, Total={total}")

    logger.debug(f"Final Benefits data: {json.dumps(benefits, indent=2)}")
    return benefits

def extract_coinsurance(data: Dict) -> Dict:
    coinsurance = {}
    sections = ["Plan Details", "Coinsurance - Patient's Coinsurance Percentage", "Total", "Benefits"]
    for section in sections:
        if section in data:
            d = data[section]
            coinsurance.update({
                "diagnostic": d.get("Diagnostic and Preventive", "") or d.get("Diagnostic and Preventive*", ""),
                "basicRestorative": d.get("Basic Restorative", ""),
                "majorRestorative": d.get("Major Restorative", ""),
                "orthodontics": d.get("Orthodontics", "")
            })
            break
    logger.debug(f"Coinsurance: {coinsurance}")
    return coinsurance

def extract_frequencies(data: Dict) -> Dict:
    frequencies = {
        "oralExam": "",
        "fullMouthXRays": "",
        "bitewingXRays": "",
        "adultCleaning": "",
        "topicalFluoride": "",
        "topicalSealant": "",
        "crown": "",
        "bridgeWork": ""
    }
    sections = ["Frequency & Limitations"]
    for section in sections:
        if section in data:
            d = data[section]
            for key, value in d.items():
                key_lower = key.lower()
                if "oral exam" in key_lower:
                    frequencies["oralExam"] = value
                elif "full mouth x" in key_lower or "fmx" in key_lower:
                    frequencies["fullMouthXRays"] = value
                elif "bitewing x" in key_lower:
                    frequencies["bitewingXRays"] = value
                elif "adult cleaning" in key_lower or "prophy" in key_lower:
                    frequencies["adultCleaning"] = value
                elif "topical fluoride" in key_lower:
                    frequencies["topicalFluoride"] = value
                elif "topical sealant" in key_lower or "sealant application" in key_lower:
                    frequencies["topicalSealant"] = value
                elif "crown" in key_lower:
                    frequencies["crown"] = value
                elif "bridge work" in key_lower:
                    frequencies["bridgeWork"] = value
    logger.debug(f"Frequencies: {frequencies}")
    return frequencies

def extract_pre_auth(data: Dict) -> str:
    sections = ["Predetermination of Benefits", "CHCP - Dental", "Frequency & Limitations", "Plan Details"]
    for section in sections:
        if section in data:
            for key, value in data[section].items():
                if "pretreatment review" in key.lower() or "predetermination" in key.lower():
                    return value or key
                if "pretreatment review" in value.lower():
                    return value
    return "Pretreatment review is available on a voluntary basis when dental work in excess of $200 is proposed by the provider."

def extract_procedure_dates(data: Dict) -> Dict:
    procedures = {}
    sections = ["Code Procedure", "Procedure Code Search"]
    for section in sections:
        if section in data:
            for key, value in data[section].items():
                if "History" in key and "No history" not in value:
                    procedures[key] = value
    logger.debug(f"Procedure dates: {procedures}")
    return procedures

def extract_procedure_codes(data: Dict) -> Dict:
    procedure_codes = {}
    if "Procedure Codes" in data:
        procedure_codes = data["Procedure Codes"]
    logger.info(f"Procedure codes returned: {json.dumps(procedure_codes, indent=2)}")
    return procedure_codes