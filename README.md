# Requirement Extraction Agent

A Dash-based application for processing Business Requirements Documents (BRDs) and generating useful project-delivery artifacts.

The application supports:

- Uploading BRD files in PDF, DOCX, DOC, or TXT format
- Building a searchable knowledge base from the uploaded document
- Asking evidence-grounded questions through a QA chatbot
- Generating a Design Requirements Specification (DRS)
- Generating Jira user stories
- Generating an Excel-based effort estimation workbook

## Prerequisites

Install the following before running the application:

- Python 3.10 or later
- [Git](https://git-scm.com/downloads)
- [Node.js LTS](https://nodejs.org/)  
  Node.js is required for Excel estimation workbook generation.
- A Groq API key from [Groq Console](https://console.groq.com/)

## Local Setup and Run

Open PowerShell and run:

```powershell
git clone https://github.com/soukarya18/Requirement-Extraction-Agent-.git
cd Requirement-Extraction-Agent-
code .
```

Create and activate a Python virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

> If PowerShell blocks activation, run the following once for the current terminal, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```

Create an environment file in the project root:

```powershell
New-Item .env -ItemType File
```

Add your Groq API key to `.env`:

```env
GROQ_API_KEY=your_groq_api_key_here
```

Install the required Python packages:

```powershell
pip install -r requirements.txt
```

Launch the application:

```powershell
python dash_app.py
```

Open the application in your browser:

```text
http://127.0.0.1:8050
```

## How to Use

1. Open the **Requirements Generation** section.
2. Upload a BRD document.
3. Wait until the document is processed and the knowledge base is ready.
4. Generate a DRS, Jira user stories, or an estimation workbook.
5. Download generated files from the application dashboard.
6. Use the QA chatbot to ask questions based on the uploaded BRD.

## Generated Files

Generated artifacts are stored locally in the `output/` directory, grouped by BRD name. Typical outputs include:

- `generated_drs.docx`
- `generated_jira_user_stories.docx`
- `generated_estimation.xlsx`

## Configuration

The `.env` file is intentionally excluded from Git to keep API keys private. Never commit or share your Groq API key.
