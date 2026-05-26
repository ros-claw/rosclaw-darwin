from setuptools import setup, find_packages

setup(
    name="rosclaw-darwin",
    version="0.1.0",
    description="ROSClaw-Darwin: Evolutionary Embodied Intelligence Benchmark",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "pydantic>=2.0",
        "pyyaml>=6.0",
        "numpy>=1.24",
        "httpx>=0.27",
    ],
    extras_require={
        "dev": ["pytest>=8.0", "pytest-asyncio>=0.23"],
        "arena": ["isaaclab-arena>=0.2.0"],
        "dashboard": ["fastapi>=0.110", "uvicorn>=0.29"],
    },
)
