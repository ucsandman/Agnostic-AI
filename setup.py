from setuptools import setup, find_packages

setup(
    name="agnostic-agent",
    version="1.2.0",
    description="Model-agnostic autonomous coding agent engine with Claude Code capabilities, subagents, and governance",
    packages=find_packages(),
    py_modules=["launch"],
    install_requires=[
        "openai>=1.0.0",
        "rich>=13.0.0",
        "httpx>=0.25.0",
        "prompt_toolkit>=3.0.0",
        "textual>=0.40.0",
    ],
    entry_points={
        "console_scripts": [
            "agnostic=agent.tui:main",
            "agnostic-agent=agent.tui:main",
            "agnostic-legacy=agent.cli:main",
        ],
    },
    python_requires=">=3.9",
)
