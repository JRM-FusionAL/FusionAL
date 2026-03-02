# Contributing to FusionAL

Thanks for your interest in improving FusionAL.

## Development Setup

1. Clone and enter the repo:
   - `git clone https://github.com/TangMan69/FusionAL.git`
   - `cd FusionAL`
2. Create a virtual environment:
   - Windows: `python -m venv venv && .\venv\Scripts\activate`
   - Linux/macOS: `python -m venv venv && source venv/bin/activate`
3. Install dependencies:
   - `pip install -r core/requirements.txt`
4. Run the API locally:
   - `cd core`
   - `python -m uvicorn main:app --reload --port 8089`

## Branch and PR Workflow

- Create feature branches from `main`.
- Keep PRs focused and small.
- Use clear commit messages (for example: `fix:`, `feat:`, `docs:`).
- Open a Pull Request with:
  - What changed
  - Why it changed
  - How it was tested

## Coding Guidelines

- Follow existing project structure and naming.
- Prefer minimal, targeted changes over broad refactors.
- Do not commit secrets (`.env`, tokens, credentials).

## Testing

- Run relevant tests before opening a PR.
- If a change has no test coverage, include manual verification steps in the PR.

## Security and Secrets

- Never include API keys or credentials in code, commits, or screenshots.
- Use `.env.example` patterns for documented configuration.

## Reporting Issues

Use the provided issue templates for bug reports and feature requests.
