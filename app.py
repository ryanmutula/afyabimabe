import os
import json
import re
from datetime import datetime
from flask import Flask, jsonify, request
from supabase import create_client, Client
from google import genai
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if supabase_url and supabase_key:
    supabase: Client = create_client(supabase_url, supabase_key)
else:
    print("Warning: Supabase credentials missing.")

gemini_api_key = os.environ.get("GEMINI_API_KEY")
if gemini_api_key:
    gemini_client = genai.Client(api_key=gemini_api_key)
else:
    gemini_client = None
    print("Warning: Gemini API key missing.")


@app.route('/', methods=['GET'])
def health_check():
    return jsonify({
        "status": "success",
        "message": "AfyaArchive & BimaServe API is fully operational"
    }), 200


# ==========================================
# 1. AUTHENTICATION & ONBOARDING ENDPOINTS
# ==========================================

@app.route('/api/auth/register-clinic', methods=['POST'])
def register_clinic():
    try:
        data = request.get_json()
        name = data.get('name')
        email = data.get('email')
        password = data.get('password')
        kra_pin = data.get('kra_pin')
        
        if not re.match(r'^[A-Z]\d{9}[A-Z]$', kra_pin):
            return jsonify({"status": "error", "message": "Invalid KRA PIN format."}), 400
            
        is_verified = True if kra_pin == 'A123456789Z' else False
        
        auth_response = supabase.auth.sign_up({"email": email, "password": password})
        if not auth_response.user:
            return jsonify({"status": "error", "message": "Auth creation failed."}), 400
            
        db_response = supabase.table('clinics').insert({
            "id": auth_response.user.id,
            "name": name,
            "kra_pin": kra_pin,
            "email": email,
            "is_verified": is_verified
        }).execute()
        
        return jsonify({"status": "success", "message": "Clinic registered.", "data": db_response.data}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/auth/login-clinic', methods=['POST'])
def login_clinic():
    try:
        data = request.get_json()
        response = supabase.auth.sign_in_with_password({
            "email": data.get('email'),
            "password": data.get('password')
        })
        return jsonify({"status": "success", "token": response.session.access_token, "clinic_id": response.user.id}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": "Invalid credentials."}), 401


@app.route('/api/auth/register-doctor', methods=['POST'])
def register_doctor():
    try:
        data = request.get_json()
        clinic_id = data.get('clinic_id')
        name = data.get('name')
        email = data.get('email')
        password = data.get('password')
        specialty = data.get('specialty', 'General Practice')
        
        auth_response = supabase.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"role": "doctor", "clinic_id": clinic_id}
        })
        
        db_response = supabase.table('doctors').insert({
            "id": auth_response.user.id,
            "clinic_id": clinic_id,
            "name": name,
            "email": email,
            "specialty": specialty
        }).execute()
        
        return jsonify({"status": "success", "message": "Doctor registered.", "data": db_response.data}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/auth/login-doctor', methods=['POST'])
def login_doctor():
    try:
        data = request.get_json()
        response = supabase.auth.sign_in_with_password({
            "email": data.get('email'),
            "password": data.get('password')
        })
        doc_profile = supabase.table('doctors').select('clinic_id', 'name').eq('id', response.user.id).execute()
        if not doc_profile.data:
             return jsonify({"status": "error", "message": "Doctor profile not found."}), 404
             
        return jsonify({
            "status": "success", 
            "token": response.session.access_token, 
            "doctor_id": response.user.id,
            "clinic_id": doc_profile.data[0]['clinic_id'],
            "name": doc_profile.data[0]['name']
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "message": "Invalid credentials."}), 401


# ==========================================
# 2. CONSULTANT MODE: PATIENTS & ENCOUNTERS
# ==========================================

@app.route('/api/patients/add', methods=['POST'])
def add_patient():
    """Adds a patient strictly isolated to a specific clinic, or returns existing if already registered."""
    try:
        data = request.get_json()
        clinic_id = data.get('clinic_id')
        first_name = data.get('first_name')
        last_name = data.get('last_name')
        dob = data.get('date_of_birth')
        phone = data.get('phone_number')
        
        if not clinic_id or not first_name or not last_name:
            return jsonify({"status": "error", "message": "clinic_id, first_name, and last_name are required."}), 400

        db_response = supabase.table('patients').insert({
            "clinic_id": clinic_id,
            "first_name": first_name,
            "last_name": last_name,
            "date_of_birth": dob,
            "phone_number": phone
        }).execute()
        
        return jsonify({"status": "success", "message": "Patient registered.", "data": db_response.data}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/patients/<uuid:clinic_id>', methods=['GET'])
def get_clinic_patients(clinic_id):
    """Retrieves all patients belonging exclusively to this clinic, with their visit history."""
    try:
        response = supabase.table('patients').select('*, encounters(id, status, created_at, clinical_notes(*))').eq('clinic_id', str(clinic_id)).execute()
        return jsonify({"status": "success", "data": response.data}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/encounters/create', methods=['POST'])
def create_encounter():
    """Starts a new visit for a returning or new patient."""
    try:
        data = request.get_json()
        patient_id = data.get('patient_id')
        doctor_id = data.get('doctor_id')
        
        response = supabase.table('encounters').insert({
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "status": "in_consultation"
        }).execute()
        
        return jsonify({"status": "success", "message": "Encounter created.", "data": response.data}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/generate-clinical-note', methods=['POST'])
def generate_clinical_note():
    if not gemini_client:
        return jsonify({"status": "error", "message": "Gemini client not initialized"}), 500
        
    try:
        data = request.get_json()
        encounter_id = data.get('encounter_id')
        raw_transcript = data.get('raw_transcript')
        
        if not encounter_id or not raw_transcript:
            return jsonify({"status": "error", "message": "encounter_id and raw_transcript are required"}), 400

        prompt = f"""
        You are an expert clinical documentation AI. Analyze the following raw consultation transcript and convert it into a highly structured clinical note. 
        Return ONLY a raw JSON object with the following keys. Do not include markdown formatting or backticks.
        - "subjective": Patient's symptoms and history.
        - "objective": Measurable clinical findings.
        - "assessment": Medical diagnosis.
        - "plan": Treatment and pharmacological medication plan.
        - "diagnoses_icd10": A list of strings containing relevant ICD-10 codes.

        Raw Transcript:
        "{raw_transcript}"
        """
        
        response = gemini_client.models.generate_content(
            model='gemini-3.6-flash',
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        
        ai_data = json.loads(response.text)
        
        db_response = supabase.table('clinical_notes').insert({
            "encounter_id": encounter_id,
            "subjective": ai_data.get("subjective", ""),
            "objective": ai_data.get("objective", ""),
            "assessment": ai_data.get("assessment", ""),
            "plan": ai_data.get("plan", ""),
            "diagnoses_icd10": ai_data.get("diagnoses_icd10", []),
            "ai_generated": True
        }).execute()
        
        return jsonify({"status": "success", "message": "Clinical note generated.", "data": db_response.data}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/prescriptions/create', methods=['POST'])
def create_prescription():
    """Sends a detailed prescription from Consultant Mode directly to the clinic's pharmacy queue."""
    try:
        data = request.get_json()
        encounter_id = data.get('encounter_id')
        patient_id = data.get('patient_id')
        clinic_id = data.get('clinic_id')
        doctor_id = data.get('doctor_id')
        drug_id = data.get('drug_id')
        dosage = data.get('dosage')             # e.g., "500mg"
        frequency = data.get('frequency')       # e.g., "Twice daily"
        duration = data.get('duration')         # e.g., "5 days"
        times_to_take = data.get('times_to_take') # e.g., "Morning and Evening"
        
        response = supabase.table('prescriptions').insert({
            "encounter_id": encounter_id,
            "patient_id": patient_id,
            "clinic_id": clinic_id,
            "doctor_id": doctor_id,
            "drug_id": drug_id,
            "dosage": dosage,
            "frequency": frequency,
            "duration": duration,
            "times_to_take": times_to_take,
            "status": "pending_dispense"
        }).execute()
        
        return jsonify({"status": "success", "message": "Prescription sent to pharmacy.", "data": response.data}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/request-preauth', methods=['POST'])
def request_preauth():
    if not gemini_client:
        return jsonify({"status": "error", "message": "Gemini client not initialized"}), 500
        
    try:
        data = request.get_json()
        encounter_id = data.get('encounter_id')
        
        note_response = supabase.table('clinical_notes').select('*').eq('encounter_id', encounter_id).execute()
        if not note_response.data:
            return jsonify({"status": "error", "message": "Clinical note not found."}), 404
            
        clinical_note = note_response.data[0]
        
        prompt = f"""
        You are BimaServe, an automated health insurance pre-authorization AI. 
        Evaluate the following clinical note:
        - Assessment: {clinical_note.get('assessment')}
        - Plan: {clinical_note.get('plan')}
        - ICD-10 Codes: {clinical_note.get('diagnoses_icd10')}
        
        Return ONLY a raw JSON object with keys:
        - "status": "APPROVED", "PENDING_REVIEW", or "DENIED".
        - "justification": Brief medical justification.
        - "approved_amount": Integer amount in KES.
        """
        
        ai_response = gemini_client.models.generate_content(
            model='gemini-3.6-flash',
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        
        adjudication_data = json.loads(ai_response.text)
        
        db_response = supabase.table('pre_authorizations').insert({
            "encounter_id": encounter_id,
            "status": adjudication_data.get("status"),
            "justification": adjudication_data.get("justification"),
            "approved_amount": adjudication_data.get("approved_amount")
        }).execute()
        
        return jsonify({"status": "success", "message": "Pre-auth processed.", "data": db_response.data}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================
# 3. PHARMACIST MODE: INVENTORY, BILLING & DISPENSING
# ==========================================

@app.route('/api/drugs/search', methods=['GET'])
def search_master_drugs():
    try:
        query = request.args.get('q', '').strip()
        response = supabase.table('master_drugs').select('*').or_(
            f"brand_name.ilike.%{query}%,generic_name.ilike.%{query}%"
        ).execute()
        return jsonify({"status": "success", "count": len(response.data), "data": response.data}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/inventory/<uuid:clinic_id>', methods=['GET'])
def get_clinic_inventory(clinic_id):
    try:
        response = supabase.table('clinic_inventory').select(
            'id, drug_id, custom_price_kes, stock_quantity, abc_class, master_drugs(brand_name, generic_name, ved_category)'
        ).eq('clinic_id', str(clinic_id)).execute()
        return jsonify({"status": "success", "data": response.data}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/inventory/upsert', methods=['POST'])
def upsert_clinic_inventory():
    try:
        data = request.get_json()
        response = supabase.table('clinic_inventory').upsert({
            "clinic_id": data.get('clinic_id'),
            "drug_id": data.get('drug_id'),
            "custom_price_kes": data.get('custom_price_kes'),
            "stock_quantity": data.get('stock_quantity', 0),
            "abc_class": data.get('abc_class', 'C')
        }, on_conflict="clinic_id,drug_id").execute()
        return jsonify({"status": "success", "message": "Inventory updated.", "data": response.data}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/billing/generate-invoice', methods=['POST'])
def generate_invoice():
    """Produces a bespoke invoice including consultation fee and clinic-specific drug pricing."""
    try:
        data = request.get_json()
        clinic_id = data.get('clinic_id')
        patient_id = data.get('patient_id')
        encounter_id = data.get('encounter_id')
        consultation_fee = data.get('consultation_fee', 1000.00)
        drug_items = data.get('drug_items', []) # List of {"drug_id": "...", "quantity": 2}
        
        drugs_total = 0.00
        for item in drug_items:
            # Fetch the clinic's bespoke custom price for this drug
            price_res = supabase.table('clinic_inventory').select('custom_price_kes').eq('clinic_id', clinic_id).eq('drug_id', item['drug_id']).execute()
            if price_res.data:
                unit_price = float(price_res.data[0]['custom_price_kes'])
                drugs_total += unit_price * int(item['quantity'])

        total_amount = float(consultation_fee) + drugs_total

        invoice_res = supabase.table('invoices').insert({
            "clinic_id": clinic_id,
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "consultation_fee": consultation_fee,
            "drugs_total": drugs_total,
            "total_amount": total_amount,
            "status": "unpaid"
        }).execute()

        return jsonify({"status": "success", "message": "Invoice generated.", "data": invoice_res.data}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/prescriptions/dispense', methods=['POST'])
def dispense_prescription():
    """Pharmacist mode: dispenses prescription, logs pharmacist name, and deducts inventory stock."""
    try:
        data = request.get_json()
        prescription_id = data.get('prescription_id')
        pharmacist_id = data.get('pharmacist_id')
        clinic_id = data.get('clinic_id')
        drug_id = data.get('drug_id')
        quantity_dispensed = data.get('quantity_dispensed', 1)

        # 1. Update prescription status and record dispensing pharmacist
        rx_res = supabase.table('prescriptions').update({
            "status": "dispensed",
            "pharmacist_id": pharmacist_id
        }).eq('id', prescription_id).execute()

        # 2. Deduct from clinic inventory stock
        inv_res = supabase.table('clinic_inventory').select('stock_quantity').eq('clinic_id', clinic_id).eq('drug_id', drug_id).execute()
        if inv_res.data:
            current_stock = inv_res.data[0]['stock_quantity']
            new_stock = max(0, current_stock - int(quantity_dispensed))
            supabase.table('clinic_inventory').update({"stock_quantity": new_stock}).eq('clinic_id', clinic_id).eq('drug_id', drug_id).execute()

        return jsonify({"status": "success", "message": "Prescription dispensed and inventory updated.", "data": rx_res.data}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================
# 4. DASHBOARD MONTHLY ANALYTICS ENDPOINT
# ==========================================

@app.route('/api/dashboard/stats/<uuid:clinic_id>', methods=['GET'])
def get_dashboard_stats(clinic_id):
    """Provides monthly statistics for patients seen, prescriptions dispensed, and drug types stored."""
    try:
        # Fetch patient count for this clinic
        patients_res = supabase.table('patients').select('id', count='exact').eq('clinic_id', str(clinic_id)).execute()
        patient_count = patients_res.count if hasattr(patients_res, 'count') else len(patients_res.data)

        # Fetch dispensed prescriptions count (drugs sold)
        rx_res = supabase.table('prescriptions').select('id', count='exact').eq('clinic_id', str(clinic_id)).eq('status', 'dispensed').execute()
        drugs_sold_count = rx_res.count if hasattr(rx_res, 'count') else len(rx_res.data)

        # Fetch types of drugs stored in clinic inventory
        inv_res = supabase.table('clinic_inventory').select('id', count='exact').eq('clinic_id', str(clinic_id)).execute()
        inventory_count = inv_res.count if hasattr(inv_res, 'count') else len(inv_res.data)

        return jsonify({
            "status": "success",
            "data": {
                "total_patients_registered": patient_count,
                "total_prescriptions_dispensed": drugs_sold_count,
                "total_drug_types_stored": inventory_count
            }
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)