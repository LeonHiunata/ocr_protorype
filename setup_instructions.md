# Setup Instructions

Follow these steps to set up the environment and run the Streamlit OCR application.

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

Note: Installing EasyOCR might take some time as it downloads the necessary models and PyTorch dependencies on the first run.

## 4. Run the Streamlit Application

Once installed, you can start the Streamlit web app with:

```powershell
streamlit run run_app.py
```

## 5. Run the Batch Processing Script

To test the algorithm on all images in the `Dataset` folder, run:

```powershell
python process_dataset.py
```
