# Smart Home Energy Simulation

This repository contains a small energy system simulation for a residential smart home. The core model is implemented in `simulation.py`, and an interactive workflow is provided in `simulation.ipynb`.

## Project overview

- `simulation.py` defines a modular, object-oriented simulation engine.
- Components include heat/electricity/cooling demands, PV generation, heat pump, gas boiler, chiller, battery storage, heat storage, and grid interaction.
- The notebook uses the simulation module to run scenarios, compare results, and visualize performance metrics.

## Requirements

This project is built for Python 3. A lightweight virtual environment is recommended.

Required Python packages:

- `numpy`
- `pandas`
- `jupyter`

You can install these packages from `requirements.txt`.

## Setup

1. Open a terminal in this project folder.
2. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Upgrade pip and install dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Running the project

### Using the notebook

Start Jupyter Notebook and open `simulation.ipynb`:

```bash
jupyter notebook simulation.ipynb
```

The notebook imports the module and demonstrates scenario setup, simulation execution, and result comparison.

### Using the Python module

The simulation module can also be imported directly from a Python shell or another script:

```python
from simulation import setup_base, run_scenario, show_comparison

base, scenario = run_scenario(duration_days=1, season='winter')
print(base)
print(scenario)
```

## Environment file

This repository includes a `.env` file to document the project environment and package list. It is not required to run the code, but it can help keep the local environment configuration consistent.

## Notes

- `simulation.py` does not currently define a standalone CLI entrypoint. The notebook is the main interactive interface.
- If you want to use the notebook from VS Code, ensure the `.venv` interpreter is selected and the `python` extension is active.
