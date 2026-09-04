# Setup Instructions

Follow these steps to set up the environment and run the Flask OCR GPS application.

## 1. Create a Virtual Environment

Open your terminal (PowerShell or Command Prompt) and navigate to this directory (`OCR Prototype`). Then run:

```powershell
python -m venv venv
```

## 2. Activate the Virtual Environment

Activate the environment using the following command:

```powershell
.\venv\Scripts\activate
```

## 3. Install Requirements

Install all necessary dependencies by running:

```powershell
pip install -r requirements.txt
```

## 4. Setup Environment Variables

Copy `.env.example` to `.env` and fill in your Gemini API key:

```powershell
cp .env.example .env
```
Make sure to set `GEMINI_API_KEY` in your `.env` file before running the application.

## 5. Run the Application

Once installed, you can start the Flask server with:

```powershell
python run_app.py
```
*(atau jalankan `python backend/app.py`)*

The application will start at `http://127.0.0.1:5000`.
