import os
from flask import Flask, jsonify, request
from supabase import create_client, Client
from google import genai
from dotenv import load_dotenv

# Load environment variables from .env file for local development
load_dotenv()

app = Flask(__name__)

# Initialize Supabase with the Service Role Key to bypass RLS for backend operations
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if supabase_url and supabase_key:
    supabase: Client = create_client(supabase_url, supabase_key)
else:
    print("Warning: Supabase credentials missing.")

# Initialize the new Gemini API client
gemini_api_key = os.environ.get("GEMINI_API_KEY")
if gemini_api_key:
    gemini_client = genai.Client(api_key=gemini_api_key)
else:
    gemini_client = None
    print("Warning: Gemini API key missing.")

@app.route('/', methods=['GET'])
def health_check():
    """Vercel needs a root endpoint to verify the function is alive."""
    return jsonify({
        "status": "success",
        "message": "AfyaArchive & BimaServe API is running on Vercel"
    }), 200

@app.route('/api/test-gemini', methods=['POST'])
def test_gemini():
    """Test endpoint to verify Gemini connectivity."""
    if not gemini_client:
        return jsonify({
            "status": "error", 
            "message": "Gemini client not initialized. Check GEMINI_API_KEY."
        }), 500
        
    try:
        data = request.get_json() or {}
        prompt = data.get('prompt', 'Say hello to the AfyaArchive healthcare AI.')
        
        # Using the new google-genai syntax
        response = gemini_client.models.generate_content(
            model='gemini-3.6-flash',
            contents=prompt
        )
        
        return jsonify({
            "status": "success",
            "ai_response": response.text
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)