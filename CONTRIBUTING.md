# Contributing to HAAnim

Thank you for your interest in contributing to HAAnim! This document provides guidelines and
instructions for contributing to the project.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://gitlab.com/YOUR_USERNAME/haanim.git`
3. Create a new branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Test your changes
6. Commit your changes: `git commit -m "Add your feature"`
7. Push to your fork: `git push origin feature/your-feature-name`
8. Create a merge request

## Development Setup

```bash
# Clone the repository
git clone https://gitlab.com/valsr/haanim.git
cd haanim

# Create a virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install Home Assistant for development
pip install homeassistant

# Install development dependencies
pip install black flake8 pylint mypy
```

## Code Style

- Follow PEP 8 guidelines
- Use meaningful variable and function names
- Add docstrings to all functions and classes (Google style)
- Keep lines under 110 characters
- Use type hints where appropriate

## Testing

Before submitting a merge request:

1. Test your changes in a Home Assistant development environment
2. Ensure all existing functionality still works
3. Add tests for new features if applicable

## Commit Messages

- Use clear and descriptive commit messages
- Start with a verb in present tense (e.g., "Add", "Fix", "Update")
- Reference issues when applicable (e.g., "Fix #123")

## Merge Request Process

1. Update the CHANGELOG.md with details of your changes
2. Update the README.md if you've added new features or changed functionality
3. Ensure your code follows the style guidelines
4. Your merge request will be reviewed by maintainers

## Questions?

If you have questions, feel free to:
- Open an issue on GitLab
- Ask in the Home Assistant community forums

## Code of Conduct

Be respectful and constructive in all interactions.
