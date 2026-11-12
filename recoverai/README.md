# RecoverAI

RecoverAI is the AI-powered payment recovery module for PayGuard AI. It helps identify overdue payments, review failed transactions, prepare personalized customer recovery actions, and keep the PayPal flow safely sandboxed.

## Project purpose

This backend demonstrates a synthetic overdue payment recovery workflow. A customer can be offered a separate demo payment through PayPal Sandbox to resolve a simulated overdue balance without touching real PayPal data or real payment collections.

## Project structure

```text
recoverai/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── paypal_service.py
│   ├── recovery_agent.py
│   └── models.py
├── .env
├── .env.example
├── .gitignore
├── requirements.txt
├── tests/
│   └── test_paypal_service.py
└── README.md
```

## Python environment setup

This project requires Python 3.11 or later.

1. Open a terminal in the project folder.
2. Create a virtual environment:

```powershell
python -m venv venv
```

3. Activate it:

PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
```

Command Prompt:

```bat
venv\Scripts\activate.bat
```

If PowerShell blocks script execution, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then activate the environment again.

## Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install fastapi uvicorn requests python-dotenv pydantic pytest google-genai
```

If you want to recreate the environment later, use:

```powershell
python -m pip freeze > requirements.txt
```

## Sandbox credential and Gemini setup

Add your PayPal Sandbox credentials and Gemini settings to the local `.env` file and keep it out of version control.

```env
PAYPAL_CLIENT_ID=your_client_id
PAYPAL_CLIENT_SECRET=your_client_secret
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.0-flash
```

Do not expose the secret in frontend code or logs. The backend must keep it on the server side only.

## Run the backend

From the project root:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The app will be available at:

```text
http://127.0.0.1:8000
```

## Available endpoints

Core app endpoints:

- GET /
- GET /health
- GET /api/recovery/status
- GET /api/recovery/agent
- GET /api/recovery/example-case
- GET /api/recovery/example-plan
- GET /api/recovery/example-payment-status

PayPal flow endpoints:

- GET /api/paypal/health
- POST /api/payments/create-order
- POST /api/payments/capture-order
- GET /api/payments/return
- GET /api/payments/cancel

Recovery AI endpoints:

- POST /api/recovery/{case_id}/classify
- POST /api/recovery/{case_id}/plan
- POST /api/recovery/{case_id}/chat
- POST /api/recovery/{case_id}/action
- GET /api/recovery/{case_id}/history

Example URLs:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/health
http://127.0.0.1:8000/api/paypal/health
http://127.0.0.1:8000/docs
```

## Recovery classifications

The AI can classify cases into:

- PAYMENT_METHOD_FAILURE
- FORGOT_PAYMENT
- FINANCIAL_HARDSHIP
- PAYMENT_DISPUTE
- SUSPICIOUS_ACTIVITY
- UNKNOWN

## Gemini behavior

The project uses the official Google GenAI SDK. If a valid API key is present, the app uses Gemini to improve classification and chat responses. If the credential is missing or the request fails, the app falls back to a deterministic rule-based classification so the backend remains safe and usable.

## How to create a Sandbox order

Send a POST request to:

```text
POST /api/payments/create-order
```

Example JSON:

```json
{
  "recovery_case_id": "RC-1001"
}
```

The response includes an approval URL. Open that URL in a browser using a PayPal Sandbox buyer account.

## How to approve the order

1. Use a PayPal Sandbox buyer account.
2. Log in to PayPal Sandbox.
3. Approve the order.
4. You will be redirected back to the backend return URL.
5. After the buyer returns, call the capture endpoint using the order ID and recovery case ID.

## How to capture the payment

Send a POST request to:

```text
POST /api/payments/capture-order
```

Example JSON:

```json
{
  "order_id": "PAYPAL_ORDER_ID",
  "recovery_case_id": "RC-1001"
}
```

The backend validates the order, checks the recovery case association, and captures only after approval.

## Testing with Swagger

1. Start the backend.
2. Open the Swagger UI:

```text
http://127.0.0.1:8000/docs
```

3. Test the endpoints there.
4. Use a valid PayPal Sandbox buyer account for the approval flow.

## Automated tests

Run:

```powershell
pytest
```

This project includes mocked PayPal calls for OAuth, order creation, capture, and error-handling tests, plus RecoveryAI classification and chat checks.

## Important notes

- This is a hackathon demo, not a real loan or real repayment system.
- No actual PayPal loan repayment data is used.
- The overdue invoice is demo data only.
- The order is a separate PayPal Sandbox transaction for demonstration purposes.
- Recovery actions must be explicitly approved before they can create a real payment order.
