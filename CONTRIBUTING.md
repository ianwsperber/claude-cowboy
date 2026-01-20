# Contributing to Claude Cowboy

Thank you for your interest in contributing to Claude Cowboy! This document provides guidelines and information for contributors.

## Getting Started

### Prerequisites

- Python 3.12 or later
- tmux
- fzf (for session browser)
- git

### Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/claude-cowboy.git
   cd claude-cowboy
   ```

2. Install development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

3. Run the development installation script:
   ```bash
   ./scripts/install-dev.sh
   ```

4. Verify installation:
   ```bash
   cowboy --help
   ```

## Development Workflow

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=lib --cov-report=term-missing

# Run a specific test file
pytest tests/test_config.py
```

### Code Quality

We use the following tools for code quality:

```bash
# Linting
ruff check lib/

# Type checking
mypy lib/

# Format check
ruff format --check lib/
```

### Code Style

- Use Python 3.12+ type hints (e.g., `str | None` instead of `Optional[str]`)
- Follow PEP 8 conventions
- Use descriptive variable and function names
- Add docstrings to public functions and classes
- Keep functions focused and reasonably sized

## Making Changes

### Branching

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes with clear, focused commits

3. Push your branch and create a pull request

### Commit Messages

Write clear, concise commit messages:
- Use the imperative mood ("Add feature" not "Added feature")
- First line should be 50 characters or less
- Add detail in the body if needed

### Pull Requests

- Provide a clear description of the changes
- Reference any related issues
- Ensure all tests pass
- Update documentation if needed

## Project Structure

```
claude-cowboy/
├── lib/                    # Main Python package
│   ├── config.py          # Configuration loading
│   ├── session_discovery.py   # Session detection
│   ├── status_analyzer.py     # Status detection
│   ├── cowboy_cli.py          # CLI entry point
│   └── ...
├── tests/                  # Test suite
├── hooks/                  # Claude Code hooks
├── commands/               # Plugin commands
└── scripts/                # Development scripts
```

## Reporting Issues

When reporting issues, please include:

- Your operating system and version
- Python version (`python --version`)
- tmux version (`tmux -V`)
- Steps to reproduce the issue
- Expected vs actual behavior
- Any relevant error messages

## Questions?

Feel free to open an issue for questions or discussion about potential contributions.
