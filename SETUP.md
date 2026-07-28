# InternApply Setup Guide

Step-by-step instructions for getting InternApply running on your machine.

---

## 1. Prerequisites

- **Python 3.11 or later** (the project uses `>=3.11`)
- **Chrome or Chromium** browser (required for Playwright-based auto-apply)
- **Git** (for cloning the repository)

Check your Python version:

```bash
python --version
# Should be Python 3.11.x or higher
```

---

## 2. Install InternApply

```bash
git clone https://github.com/your-username/internapply.git
cd internapply
pip install -e .
```

This installs the package in editable mode, so the `internapply` CLI command
is available from anywhere in your terminal.

Install the Playwright browser (needed for auto-apply on Internshala):

```bash
playwright install chromium
```

Verify the CLI works:

```bash
internapply --help
```

You should see the list of available commands.

---

## 3. Get an OpenCode Go API Key

InternApply uses OpenCode Go as its LLM backend for job analysis, resume
tailoring, and cover letter generation. You need an API key.

1. Go to [opencode.ai](https://opencode.ai) and sign in.
2. Navigate to your account settings.
3. Generate an API key (or copy an existing one).
4. Save the key somewhere safe.

---

## 4. Configure Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` with your API key:

```ini
# Required
OPENCODE_GO_API_KEY=sk-...        # Your key from step 3
OPENCODE_GO_MODEL=opencode-go/deepseek-v4-flash
OPENCODE_GO_BASE_URL=https://opencode.ai/zen/go/v1

# Optional: Discovery keywords
SEARCH_KEYWORDS='["python backend intern","java spring boot intern","backend engineer intern"]'
SEARCH_LOCATIONS='["Remote","Bangalore"]'
MIN_STIPEND_INR=5000
```

The remaining variables in `.env` are optional and can be set later.

---

## 5. (Optional) Set Up Gmail API for Email Sending

If you want InternApply to send cold emails through your Gmail account, you
need to set up OAuth2 access.

### Step 5a: Create a Google Cloud project

1. Go to the [Google Cloud Console](https://console.cloud.google.com).
2. Create a new project (or select an existing one).
3. Navigate to **APIs & Services > Library**.
4. Search for "Gmail API" and enable it.

### Step 5b: Create OAuth credentials

1. Go to **APIs & Services > Credentials**.
2. Click **Create Credentials > OAuth 2.0 Client ID**.
3. If prompted, configure the consent screen:
   - User type: **External**
   - App name: "InternApply" (or anything you like)
   - Scopes: add `.../auth/gmail.send` (or skip and add later)
   - Test users: add your Gmail address
4. For application type, choose **Desktop app**.
5. Click **Create**.
6. Download the JSON file. It's your `client_secret.json`.

### Step 5c: Configure InternApply

Add these to your `.env`:

```ini
GMAIL_SENDER_EMAIL=your.email@gmail.com
GMAIL_CLIENT_SECRET_PATH=/absolute/path/to/client_secret.json
```

Then run the OAuth2 setup:

```bash
internapply email setup
```

A browser window opens. Sign in with your Google account and grant the
`gmail.send` permission. After approval, the token is encrypted and saved
to `data/gmail_token.enc`.

The setup command also sends a diagnostic email to your own inbox to confirm
everything works.

### Security notes

- The OAuth scope is restricted to `gmail.send` only. InternApply cannot
  read your inbox or contacts.
- The token is encrypted with a key derived from your machine ID. It cannot
  be used on a different machine.
- You can set `GMAIL_TOKEN_PASSPHRASE` in your environment for an additional
  layer of encryption.

---

## 6. (Optional) Get a Hunter.io API Key

Hunter.io finds hiring manager email addresses for company domains. The free
tier allows about 50 searches per month, which is enough for personal use.

1. Go to [hunter.io](https://hunter.io) and sign up.
2. Navigate to **Dashboard > API**.
3. Copy your API key.
4. Add it to `.env`:

```ini
HUNTER_API_KEY=your-hunter-api-key
```

InternApply caches email lookups in the local SQLite database, so you only
pay the API cost once per domain.

---

## 7. First Run: Import Your Resume

InternApply needs your resume data to tailor for job descriptions. The project
includes a parser for a JavaScript-based resume generator file. If you have a
`generate_resume_ai.js` file, run:

```bash
internapply resume init /path/to/generate_resume_ai.js
```

This extracts your name, contact info, education, skills, projects, and
additional details and saves them to `profile/resume.json`.

If you don't have a JS generator file, you can create `profile/resume.json`
manually. Here's the expected structure:

```json
{
  "name": "Your Name",
  "email": "you@example.com",
  "phone": "+91-...",
  "location": "Bangalore, India",
  "summary": "B.Tech student with experience in Python backend development...",
  "education": [
    {
      "degree": "B.Tech in Computer Science",
      "institution": "Your University",
      "cgpa": "9.39",
      "expected": "May 2027"
    }
  ],
  "skills": {
    "Languages": "Python, Java, SQL",
    "Frameworks": "FastAPI, Spring Boot",
    "Tools": "Docker, Git, PostgreSQL"
  },
  "projects": [
    {
      "name": "Your Project",
      "url": "https://github.com/you/project",
      "tech": "Python, FastAPI, PostgreSQL",
      "description": [
        "Built a RESTful API for...",
        "Implemented authentication with JWT"
      ]
    }
  ],
  "additional": [
    {"label": "Languages", "value": "English, Hindi"}
  ]
}
```

View your resume to confirm it loaded correctly:

```bash
internapply resume show
```

---

## 8. Test Discovery

Run discovery in dry-run mode to confirm everything is wired up:

```bash
internapply discover --dry-run
```

This uses mock data and should print a table of 3 simulated job listings.
No network calls are made.

If that works, try a real discovery:

```bash
internapply discover
```

This scrapes Internshala and Naukri for listings matching your configured
keywords and locations. Results are saved to the SQLite database.

---

## 9. Run the Pipeline

Start with a dry run to see the full pipeline flow without making any
external calls:

```bash
internapply run --dry-run
```

You should see output for all 7 stages, ending with a summary table.

For a real run:

```bash
internapply run --max-jobs 10
```

This processes up to 10 jobs through the entire pipeline. It calls the LLM
to analyze each job description, tailors your resume for each one, runs the
verifier gate, generates cover letters, looks up emails, and saves
everything to disk.

### Resuming from a stage

If the pipeline fails at the email stage (e.g. you configured Hunter.io
incorrectly), fix the issue and resume:

```bash
internapply run --from-stage email
```

---

## 10. Sending Emails

Emails are **never sent automatically**. You must explicitly approve each
batch.

First, check what's pending:

```bash
internapply email list
```

To send a single email:

```bash
internapply email send --job-id 42 --approve
```

To send all pending emails:

```bash
internapply email send --all --approve
```

The `--approve` flag is mandatory. The command also asks for a confirmation
before dispatching.

Check your remaining daily quota:

```bash
internapply email status
```

The limit is 20 emails per day per Gmail account.

---

## 11. Scheduling with GitHub Actions

The repository includes a GitHub Actions workflow that runs discovery and
tailoring every 6 hours. To enable it:

1. Push the repository to GitHub.
2. Go to **Settings > Secrets and variables > Actions**.
3. Add these repository secrets:
   - `OPENCODE_GO_API_KEY`: Your OpenCode Go API key
   - `HUNTER_API_KEY`: Your Hunter.io API key (optional)
4. Go to the **Actions** tab and enable workflows.

The workflow (`.github/workflows/daily-run.yml`) runs:

```bash
internapply discover --max-jobs 20
```

Results are uploaded as workflow artifacts. You can also trigger it manually
from the Actions tab.

If you want to run the full pipeline on a schedule, extend the workflow to
include `internapply run` and set up Gmail credentials as additional secrets.

---

## Quick Reference

```bash
# Setup
pip install -e . && playwright install chromium
cp .env.example .env   # Then edit .env

# Resume
internapply resume init
internapply resume show

# Discovery
internapply discover --dry-run
internapply discover

# Tailor for a specific job
internapply tailor "Backend Intern" "Google" --jd-file description.txt

# Full pipeline
internapply run --dry-run
internapply run --max-jobs 10

# Emails
internapply email setup
internapply email list
internapply email send --all --approve

# Status
internapply status
```

---

## Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| `OPENCODE_GO_API_KEY is not set` | Missing API key | Add it to `.env` |
| `No resume found at profile/resume.json` | Resume not imported | Run `internapply resume init` |
| Discovery returns 0 jobs | Keywords too narrow or scraping blocked | Run `--dry-run` to test; check your keywords |
| `Verifier score < 60` | LLM hallucinated content | The pipeline retries automatically; check your master resume data is complete |
| `Failed to send email` | No Gmail token or quota exhausted | Run `internapply email setup` and check `internapply email status` |
| `No applications found` | Pipeline hasn't been run yet | Run `internapply run` first |
| Playwright browser fails | Chromium not installed | Run `playwright install chromium` |
| `Hunter.io` returns empty | No API key or free tier exhausted | Check `HUNTER_API_KEY` in `.env` and your monthly quota at hunter.io |
