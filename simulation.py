"""
Smart Home Energy Simulation
A simple yet thorough object-oriented model for energy simulation.
Enhanced with detailed component reporting, Comfort Metrics, Inspection, Advanced Metrics (SCR/SSR), GasBoiler, and HeatStorage.
"""

class Component:
    """Base class for all simulation components."""
    def __init__(self, name):
        self.name = name
        self.history = []

    def reset(self):
        """Reset internal state for a new simulation run."""
        self.history = []

    def record(self, value):
        """Record a value for the current timestep."""
        self.history.append(value)


class Demand(Component):
    """Represents an energy demand (electricity or heat)."""
    def __init__(self, name, demand_type, profile):
        super().__init__(name)
        self.demand_type = demand_type
        self.profile = profile

    def get_demand(self, t):
        val = self.profile[t % len(self.profile)] if isinstance(self.profile, list) else self.profile
        self.record(val)
        return val


class Generator(Component):
    """Represents a component that produces energy."""
    def __init__(self, name, output_type, capacity, efficiency=1.0, 
                 input_type=None, emissions_factor=0.0, cost_per_input=0.0):
        super().__init__(name)
        self.output_type = output_type
        self.capacity = capacity
        self.efficiency = efficiency
        self.input_type = input_type
        self.emissions_factor = emissions_factor
        self.cost_per_input = cost_per_input

    def operate(self, required_output, available_input=float('inf')):
        if self.name == "HeatPump":
            # For HeatPump: capacity = max input power (electricity), not output
            # required_input = electricity needed to deliver required_output heat
            required_input = required_output / self.efficiency if self.efficiency > 0 else 0
            # actual_input is limited by HP's max input capacity and available input
            actual_input = min(required_input, self.capacity/self.efficiency, available_input)
            # actual_output depends on actual input available and efficiency
            actual_output = actual_input * self.efficiency
        
        else:
            target_output = min(required_output, self.capacity)
            required_input = target_output / self.efficiency if self.efficiency > 0 else 0
            actual_input = min(required_input, available_input)
            actual_output = actual_input * self.efficiency
        
        cost = actual_input * self.cost_per_input
        emissions = actual_input * self.emissions_factor
        
        self.record(actual_output)
        return actual_output, actual_input, cost, emissions


class Storage(Component):
    """Represents energy storage (e.g., Battery, HeatStorage)."""
    def __init__(self, name, energy_type, capacity, max_charge, max_discharge, charge_efficiency=0.95, discharge_efficiency=0.95):
        super().__init__(name)
        self.energy_type = energy_type
        self.capacity = capacity
        self.max_charge_power = max_charge
        self.max_discharge_power = max_discharge
        self.charge_efficiency = charge_efficiency
        self.discharge_efficiency = discharge_efficiency
        self.soc = self.capacity * 0.6

    def reset(self):
        super().reset()
        self.soc = self.capacity * 0.6

    def charge(self, available_power, dt):
        power_to_charge = min(available_power, self.max_charge_power)
        space_left_energy = self.capacity - self.soc
        max_power_by_space = space_left_energy / self.charge_efficiency / dt
        
        actual_charge_power = min(power_to_charge, max_power_by_space)
        self.soc += actual_charge_power * dt * self.charge_efficiency
        return actual_charge_power

    def discharge(self, required_power, dt):
        power_to_discharge = min(required_power, self.max_discharge_power)
        available_energy = self.soc * self.discharge_efficiency
        max_power_by_energy = available_energy / dt
        
        actual_discharge_power = min(power_to_discharge, max_power_by_energy)
        self.soc -= (actual_discharge_power * dt) / self.discharge_efficiency
        return actual_discharge_power

    def record_state(self):
        self.record(self.soc)


class Grid(Component):
    """Represents the external utility grid."""
    def __init__(self, name, import_price, export_price, emissions_factor, blackout=False):
        super().__init__(name)
        self.import_price = import_price
        self.export_price = export_price
        self.emissions_factor = emissions_factor
        self.blackout = blackout

    def interact(self, net_electricity):
        """Calculate grid interaction cost.
        net_electricity < 0 means we need to import from grid (demand > supply).
        net_electricity > 0 means we export surplus to grid (supply > demand).
        Cost = price_grid * energy_imported - export_price * energy_exported
        """
        self.record(net_electricity)
        if net_electricity < 0:
            if self.blackout:
                return 0.0, 0.0, 0.0, 0.0
            imported = abs(net_electricity)
            cost = imported * self.import_price
            return cost, imported * self.emissions_factor, imported, 0.0
    
        elif net_electricity > 0:
            exported = net_electricity
            # Earning from export is negative cost
            cost = -exported * self.export_price
            return cost, 0.0, 0.0, exported
        return 0.0, 0.0, 0.0, 0.0


class Simulation:
    def __init__(self):
        self.components = {}

    def add_component(self, component):
        self.components[component.name] = component

    def run(self, steps=24, solar_profile=None, dt=1.0):
        if solar_profile is None:
            solar_profile = [1.0] * steps

        for comp in self.components.values():
            comp.reset()

        total_emissions = 0.0
        summary = {
            "Total Cost (CHF)": 0.0,
            "PV Generation (kWh)": 0.0,
            "Heat Demand (kWh)": 0.0,
            "Heat Supplied (kWh)": 0.0,
            "Cooling Demand (kWh)": 0.0,
            "Cooling Supplied (kWh)": 0.0,
            "Elec Demand (kWh)": 0.0,
            "Elec Supplied (kWh)": 0.0,
            "Grid Import (kWh)": 0.0,
            "Grid Export (kWh)": 0.0
        }
        
        for t in range(steps):
            step_heat_demand    = sum(d.get_demand(t) for d in self.components.values() if isinstance(d, Demand) and d.demand_type == 'heat')
            step_cooling_demand = sum(d.get_demand(t) for d in self.components.values() if isinstance(d, Demand) and d.demand_type == 'cooling')
            base_elec_demand    = sum(d.get_demand(t) for d in self.components.values() if isinstance(d, Demand) and d.demand_type == 'electricity')

            summary["Heat Demand (kWh)"]    += step_heat_demand * dt
            summary["Cooling Demand (kWh)"] += step_cooling_demand * dt
            summary["Elec Demand (kWh)"]    += base_elec_demand * dt

            # --- 1. PV Generation ---
            # solar_profile values are fractions (0.0–1.0) of peak capacity.
            # pv_gen = capacity × solar_fraction  →  pv_factor scales capacity proportionally.
            pv = self.components.get('PV')
            pv_gen = 0.0
            if pv:
                solar_fraction = solar_profile[t % len(solar_profile)]  # 0.0–1.0
                pv_gen, _, cost, em = pv.operate(pv.capacity * solar_fraction)
                summary["PV Generation (kWh)"] += pv_gen * dt
                summary["Total Cost (CHF)"]     += cost * dt
                total_emissions += em * dt

            # --- 2. Heat System Logic ---
            # Priority: 1) HeatPump (primary, up to capacity)
            #           2) GasBoiler (backup, up to capacity, for what HP can't cover)
            #           3) HeatStorage discharge (last resort, for anything still unmet)
            # HeatStorage also charges from PV surplus via HeatPump.
            heat_unmet = step_heat_demand
            hs = self.components.get('HeatStorage')
            hp = self.components.get('HeatPump')
            gb = self.components.get('GasBoiler')

            # a. HeatPump runs first — capped at its capacity
            hp_heat_for_demand = min(hp.capacity, heat_unmet) if hp else 0.0

            # b. Check if excess PV allows charging HeatStorage via HeatPump
            hp_heat_for_storage = 0.0
            if hp and hs:
                hp_elec_so_far = hp_heat_for_demand / hp.efficiency if hp.efficiency > 0 else 0.0
                net_e = base_elec_demand + hp_elec_so_far - pv_gen
                if net_e < 0:  # Excess PV available
                    excess_pv = abs(net_e)
                    hp_rem_cap = hp.capacity - hp_heat_for_demand
                    hs_space = hs.capacity - hs.soc
                    max_heat_we_can_push = hs_space / hs.charge_efficiency
                    possible_heat = excess_pv * hp.efficiency
                    charge_heat = min(hp_rem_cap, max_heat_we_can_push, possible_heat)
                    if charge_heat > 0:
                        hp_heat_for_storage = charge_heat

            # Operate HeatPump
            hp_elec_needed = 0.0
            if hp:
                total_hp_req = hp_heat_for_demand + hp_heat_for_storage
                out, inp, cost, em = hp.operate(total_hp_req)
                out_for_demand = min(out, hp_heat_for_demand)
                out_for_storage = out - out_for_demand
                heat_unmet -= out_for_demand
                hp_elec_needed = inp
                summary["Total Cost (CHF)"] += cost * dt
                total_emissions += em * dt
                if hs and out_for_storage > 0:
                    hs.charge(out_for_storage, dt)

            # c. GasBoiler covers what HeatPump could not — capped at boiler capacity
            if gb and heat_unmet > 0:
                out, inp, cost, em = gb.operate(heat_unmet)
                heat_unmet -= out
                summary["Total Cost (CHF)"] += cost * dt
                total_emissions += em * dt

            # Legacy GasHeater support
            if not gb:
                gh = self.components.get('GasHeater')
                if gh and heat_unmet > 0:
                    out, inp, cost, em = gh.operate(heat_unmet)
                    heat_unmet -= out
                    summary["Total Cost (CHF)"] += cost * dt
                    total_emissions += em * dt

            # d. HeatStorage discharges as last resort for anything still unmet
            if hs and heat_unmet > 0:
                dis = hs.discharge(heat_unmet, dt)
                heat_unmet -= dis

            if hs:
                hs.record_state()

            summary["Heat Supplied (kWh)"] += (step_heat_demand - heat_unmet) * dt

            # --- 3. Cooling System Logic ---
            # Chiller consumes electricity to provide cooling (COP-based, like HeatPump for heat).
            chiller = self.components.get('Chiller')
            chiller_elec_needed = 0.0
            cooling_unmet = step_cooling_demand
            if chiller and cooling_unmet > 0:
                out, inp, cost, em = chiller.operate(cooling_unmet)
                cooling_unmet -= out
                chiller_elec_needed = inp
                summary["Total Cost (CHF)"] += cost * dt
                total_emissions += em * dt
            summary["Cooling Supplied (kWh)"] += (step_cooling_demand - cooling_unmet) * dt

            # --- 4. Electrical System Logic ---
            # net_elec > 0: more demand than supply (need grid import or battery)
            # net_elec < 0: more supply than demand (can charge battery or export to grid)
            total_elec_req = base_elec_demand + hp_elec_needed + chiller_elec_needed
            summary["Elec Demand (kWh)"] += (hp_elec_needed + chiller_elec_needed) * dt

            # pv_available - total_demand (positive = surplus, negative = deficit)
            net_elec = total_elec_req - pv_gen
            deficit_elec = max(0, net_elec)

            battery = self.components.get('Battery')
            if battery:
                if net_elec < 0:
                    # PV surplus: charge battery first
                    # net_elec becomes less negative (or zero) after charging
                    charged = battery.charge(abs(net_elec), dt)
                    net_elec += charged   # surplus is reduced
                else:
                    # Deficit: discharge battery to cover as much as possible
                    dis = battery.discharge(net_elec, dt)
                    net_elec -= dis
                    deficit_elec -= dis
                battery.record_state()

            # After battery, remaining net_elec:
            #   net_elec > 0  -> deficit -> grid import
            #   net_elec < 0  -> surplus -> export to grid (pv_feed)
            # Grid.interact convention: negative=import, positive=export, so pass -net_elec
            # Cost = import_price * grid_import - export_price * pv_feed
            grid = self.components.get('Grid')
            if grid:
                cost, em, imp, exp = grid.interact(-net_elec)
                summary["Total Cost (CHF)"] += cost * dt
                total_emissions += em * dt
                summary["Grid Import (kWh)"] += imp * dt
                summary["Grid Export (kWh)"] += exp * dt
                deficit_elec = max(0, deficit_elec - imp)

            summary["Elec Supplied (kWh)"] += (total_elec_req - max(0, deficit_elec)) * dt

        # Final Analytics
        summary["Heat Comfort (%)"]    = (summary["Heat Supplied (kWh)"]    / summary["Heat Demand (kWh)"]    * 100) if summary["Heat Demand (kWh)"]    > 0 else 100.0
        summary["Cooling Comfort (%)"] = (summary["Cooling Supplied (kWh)"] / summary["Cooling Demand (kWh)"] * 100) if summary["Cooling Demand (kWh)"] > 0 else 100.0
        summary["Elec Comfort (%)"]    = (summary["Elec Supplied (kWh)"]    / summary["Elec Demand (kWh)"]    * 100) if summary["Elec Demand (kWh)"]    > 0 else 100.0

        summary["Self-Consumption Rate (%)"] = ((summary["PV Generation (kWh)"] - summary["Grid Export (kWh)"]) / summary["PV Generation (kWh)"] * 100) if summary["PV Generation (kWh)"] > 0 else 0.0
        summary["Self-Sufficiency Rate (%)"] = ((summary["Elec Demand (kWh)"] - summary["Grid Import (kWh)"]) / summary["Elec Demand (kWh)"] * 100) if summary["Elec Demand (kWh)"] > 0 else 100.0

        # Emissions per kWh (accounting for mixture of PV and grid)
        total_external_elec = summary["PV Generation (kWh)"] + summary["Grid Import (kWh)"]
        summary["Emissions per kWh (kg CO2/kWh)"] = (total_emissions / total_external_elec) if total_external_elec > 0 else 0.0

        return summary

    def print_parameters(self):
        print("\n" + "-"*50)
        print("CURRENT SYSTEM PARAMETERS")
        print("-"*50)
        for name, comp in self.components.items():
            if isinstance(comp, Generator):
                print(f"{name:12}: Capacity={comp.capacity:<6} Efficiency={comp.efficiency:<6}")
            elif isinstance(comp, Storage):
                print(f"{name:12}: Capacity={comp.capacity:<6} MaxCharge={comp.max_charge_power:<6}")
            elif isinstance(comp, Grid):
                print(f"{name:12}: ImportPrice={comp.import_price:<6} ExportPrice={comp.export_price:<6}")
            elif isinstance(comp, Demand):
                avg_demand = sum(comp.profile)/len(comp.profile) if isinstance(comp.profile, list) else comp.profile
                print(f"{name:12}: Avg Demand={avg_demand:<6}")
        print("-"*50 + "\n")

    def print_results(self):
        print("\n" + "="*50)
        print("SIMULATION RESULTS BY COMPONENT")
        print("="*50)
        for name, comp in self.components.items():
            vals = [round(v, 2) for v in comp.history]
            print(f"{name:12}: {vals}")
        print("="*50 + "\n")


# ---------------------------------------------------------------------------
# Convenience functions used by the notebook
# ---------------------------------------------------------------------------

try:
    import pandas as pd
    import numpy as np

    def calculate_comp(base, scen):
        """Build a DataFrame comparing base and scenario summary dicts."""
        res = []
        for m in base:
            b, s = base[m], scen[m]
            diff = s - b
            dev = ((diff) / abs(b) * 100) if b != 0 else (0.0 if s == 0 else float('nan'))
            res.append({"Metric": m, "Base": b, "Scenario": s, "Abs. Diff": diff, "Rel. Dev. (%)": dev})
        return pd.DataFrame(res)

    def color_dev(v):
        """Color cell: blue=neutral, green=positive, red=negative deviation."""
        if pd.isna(v) or v == 0:
            return "background-color:#3b82f6;color:white"
        return "background-color:#22c55e;color:white" if v > 0 else "background-color:#ef4444;color:white"

    def show_comparison(base, scen, title="Comparison"):
        """Print a styled comparison table of two scenario summaries."""
        print(f"--- {title} ---")
        df = calculate_comp(base, scen)
        return df.style.map(color_dev, subset=["Rel. Dev. (%)"]).format(
            {"Base": "{:.2f}", "Scenario": "{:.2f}", "Abs. Diff": "{:+.2f}", "Rel. Dev. (%)": "{:+.2f}%"})

except ImportError:
    pass   # pandas/numpy not available outside notebook — functions skipped

# Default daily solar profiles (4 timesteps = one representative day)
SOLAR_PROFILE_WINTER = [0.0, 0.4, 0.8, 0.0]
SOLAR_PROFILE_SUMMER = [0.0, 0.6, 1.0, 0.3]
SOLAR_PROFILE = SOLAR_PROFILE_WINTER  # Default fallback


def calculate_base_demand(season):
    """Calculate the total average daily electricity consumption of the house (kWh)."""
    if season == "summer":
        heat_profile = [0.2, 0.4, 0.3, 0.5]
        cooling_profile = [1.0, 2.5, 3.0, 1.5]
    else: # winter
        heat_profile = [2.0, 3.0, 2.5, 4.0]
        cooling_profile = [0.0, 0.0, 0.0, 0.0]

    elec_demand = sum([1.0, 1.2, 1.5, 0.8])
    hp_elec = sum(heat_profile) / 3.5  # HP efficiency is 3.5
    chiller_elec = sum(cooling_profile) / 3.0  # Chiller efficiency is 3.0
    
    # Each profile value represents average kW over the step. 
    # Total daily kWh = sum(kW) * dt
    dt = 24.0 / 4.0  # 4 steps per day
    return (elec_demand + hp_elec + chiller_elec) * dt


def setup_base(season="winter", pv_sizing_factor=None):
    """Create a fresh base-case simulation with default component values based on season."""
    sim = Simulation()
    
    if season == "summer":
        heat_profile = [0.2, 0.4, 0.3, 0.5]
        cooling_profile = [1.0, 2.5, 3.0, 1.5]
    else: # winter
        heat_profile = [2.0, 3.0, 2.5, 4.0]
        cooling_profile = [0.0, 0.0, 0.0, 0.0]

    sim.add_component(Demand("Heat",    "heat",        profile=heat_profile))
    sim.add_component(Demand("Elec",    "electricity", profile=[1.0, 1.2, 1.5, 0.8]))
    sim.add_component(Demand("Cooling", "cooling",     profile=cooling_profile))

    if pv_sizing_factor is not None:
        daily_demand = calculate_base_demand(season)
        solar_profile = SOLAR_PROFILE_SUMMER if season == "summer" else SOLAR_PROFILE_WINTER
        dt = 24.0 / len(solar_profile)
        # We need: pv_capacity * dt * sum(solar_profile) = pv_sizing_factor * daily_demand
        pv_capacity = (pv_sizing_factor * daily_demand) / (dt * sum(solar_profile))
    else:
        pv_capacity = 5.0

    sim.add_component(Generator("PV",        "electricity", capacity=pv_capacity))
    sim.add_component(Generator("HeatPump",  "heat",        capacity=4.0, efficiency=3.5,
                                input_type="electricity"))
    sim.add_component(Generator("GasBoiler", "heat",        capacity=4.0, efficiency=0.9,
                                input_type="gas", cost_per_input=0.15, emissions_factor=0.2))
    sim.add_component(Generator("Chiller",   "cooling",     capacity=3.0, efficiency=3.5,
                                input_type="electricity"))
    sim.add_component(Storage("Battery",     "electricity", capacity=10.0,
                              max_charge=5.0, max_discharge=5.0))
    sim.add_component(Storage("HeatStorage", "heat",        capacity=5.0,
                              max_charge=3.0, max_discharge=3.0,
                              charge_efficiency=0.98, discharge_efficiency=0.98))
    sim.add_component(Grid("Grid", import_price=0.27, export_price=0.08,
                           emissions_factor=0.09))
    return sim


def run_scenario(
    duration_days           = 1,
    season                  = "winter",
    solar_profile           = None,
    pv_sizing_factor        = None,
    pv_factor               = 1.0,
    battery_factor          = 1.0,
    heat_demand_factor      = 1.0,
    cooling_demand_factor   = 1.0,
    elec_demand_factor      = 1.0,
    hp_capacity_factor      = 1.0,
    chiller_capacity_factor = 1.0,
    boiler_capacity_factor  = 1.0,
    heat_storage_factor     = 1.0,
    black_out_factor        = False,  # If True, Grid import is blocked (infinite price) to simulate blackout
    grid_import_price_factor = 1.0,
    grid_export_price_factor = 1.0,
):
    """
    Run base case and scenario for the given duration and factors.
    Returns (base_summary, scenario_summary).

    All *_factor parameters are multipliers applied on top of the base values.
    E.g. heat_demand_factor=2.0 doubles the heat demand (coldspell).
    """
    if solar_profile is None:
        solar_profile = SOLAR_PROFILE_SUMMER if season == "summer" else SOLAR_PROFILE_WINTER

    steps_per_day = len(solar_profile)
    dt            = 24.0 / steps_per_day          # hours per timestep
    total_steps   = steps_per_day * duration_days  # total timesteps

    # --- Base case (no factors applied) ---
    base_sim     = setup_base(season=season, pv_sizing_factor=pv_sizing_factor)
    base_summary = base_sim.run(steps=total_steps, solar_profile=solar_profile, dt=dt)

    # --- Scenario (factors applied to a fresh simulation) ---
    sim = setup_base(season=season, pv_sizing_factor=pv_sizing_factor)
    sim.components["PV"].capacity              *= pv_factor
    sim.components["Battery"].capacity         *= battery_factor
    sim.components["HeatPump"].capacity        *= hp_capacity_factor
    sim.components["HeatPump"].efficiency       *= hp_capacity_factor  # Assume efficiency scales with capacity for HP
    sim.components["Chiller"].capacity         *= chiller_capacity_factor
    sim.components["GasBoiler"].capacity       *= boiler_capacity_factor
    sim.components["HeatStorage"].capacity     *= heat_storage_factor
    sim.components["Heat"].profile    = [v * heat_demand_factor    for v in sim.components["Heat"].profile]
    sim.components["Cooling"].profile = [v * cooling_demand_factor for v in sim.components["Cooling"].profile]
    sim.components["Elec"].profile    = [v * elec_demand_factor    for v in sim.components["Elec"].profile]
    sim.components["Grid"].import_price *= grid_import_price_factor
    sim.components["Grid"].export_price *= grid_export_price_factor
    sim.components["Grid"].blackout = black_out_factor
    sim.print_parameters()
    scenario_summary = sim.run(steps=total_steps, solar_profile=solar_profile, dt=dt)
    return base_summary, scenario_summary


def run_pv_sweep_scenario(**kwargs):
    """
    Runs `run_scenario` for 4 different PV sizing factors: 1.2, 1.0, 0.8, 0.6.
    Returns a dictionary mapping the sizing factor to (base_summary, scenario_summary).
    """
    results = {}
    for sizing in [1.2, 1.0, 0.8, 0.6]:
        print(f"\n{'='*50}\nRUNNING SWEEP: PV Sizing Factor = {sizing}x Base Demand\n{'='*50}")
        # Overwrite pv_sizing_factor in kwargs
        sweep_kwargs = kwargs.copy()
        sweep_kwargs['pv_sizing_factor'] = sizing
        base, scen = run_scenario(**sweep_kwargs)
        results[sizing] = (base, scen)
    return results


try:
    from IPython.display import display, HTML
    import matplotlib.pyplot as plt
    import seaborn as sns
    
    def show_sweep_comparison(sweep_results, title="PV Sweep Comparison"):
        """
        Displays 4 side-by-side or consecutive styled comparison tables for the sweep results,
        and plots a grouped bar chart of the relative deviations for all metrics.
        """
        print(f"\n--- {title} ---")
        all_dfs = []
        for sizing, (base, scen) in sweep_results.items():
            print(f"\nPV Sizing: {sizing}x Demand")
            df = calculate_comp(base, scen)
            styled_df = df.style.map(color_dev, subset=["Rel. Dev. (%)"]).format(
                {"Base": "{:.2f}", "Scenario": "{:.2f}", "Abs. Diff": "{:+.2f}", "Rel. Dev. (%)": "{:+.2f}%"}
            )
            display(HTML(styled_df.to_html()))
            
            # Prepare data for plot
            df_plot = df.copy()
            df_plot['PV Sizing'] = f"{sizing}x"
            all_dfs.append(df_plot)
            
        if all_dfs:
            master_df = pd.concat(all_dfs, ignore_index=True)
            
            # 1) Absolute Comparison Table
            print(f"\n--- Absolute Comparison (Scenario Values) ---")
            abs_df = master_df.pivot(index='Metric', columns='PV Sizing', values='Scenario').reset_index()
            # Keep original metric order
            metrics_order = all_dfs[0]['Metric'].tolist()
            abs_df['Metric'] = pd.Categorical(abs_df['Metric'], categories=metrics_order, ordered=True)
            abs_df = abs_df.sort_values('Metric')
            # Keep original sizing columns order
            sizing_cols = [f"{s}x" for s in sweep_results.keys()]
            abs_df = abs_df[['Metric'] + sizing_cols]
            
            format_dict = {col: "{:.2f}" for col in sizing_cols}
            styled_abs_df = abs_df.style.format(format_dict)
            display(HTML(styled_abs_df.to_html()))

            # 2) Relative Deviations Plot
            master_df_rel = master_df.dropna(subset=['Rel. Dev. (%)'])
            plt.figure(figsize=(16, 7))
            sns.barplot(data=master_df_rel, x='Metric', y='Rel. Dev. (%)', hue='PV Sizing')
            plt.title(f"{title} - Relative Deviations by PV Size", fontsize=14, pad=15)
            plt.xticks(rotation=45, ha='right')
            plt.ylabel("Relative Deviation (%)")
            plt.yscale('symlog', linthresh=10.0)
            plt.axhline(0, color='black', linewidth=0.8)
            plt.tight_layout()
            plt.show()

           
            # 4) Absolute Values Plot - Base Case
            plt.figure(figsize=(16, 7))
            sns.barplot(data=master_df, x='Metric', y='Base', hue='PV Sizing')
            plt.title(f"{title} - Absolute Base Case Values by PV Size", fontsize=14, pad=15)
            plt.xticks(rotation=45, ha='right')
            plt.ylabel("Absolute Value")
            plt.axhline(0, color='black', linewidth=0.8)
            plt.tight_layout()
            plt.show()

            # 5) Base vs Scenario Comparison
            # Melt data to prepare for side-by-side comparison
            comparison_cols = ['Metric', 'PV Sizing']
            melted_df = master_df[comparison_cols + ['Base', 'Scenario']].melt(
                id_vars=comparison_cols, 
                var_name='Case', 
                value_name='Value'
            )
            melted_df['Metric_Case'] = melted_df['Metric'] + '\n(' + melted_df['Case'] + ')'
            
            # Display as table
            print(f"\n--- Base Case vs Scenario Comparison Table ---")
            comparison_table = melted_df.pivot_table(
                index='Metric',
                columns=['PV Sizing', 'Case'],
                values='Value',
                aggfunc='first'
            )
            # Keep original metric order
            comparison_table['Metric'] = pd.Categorical(comparison_table.index, categories=metrics_order, ordered=True)
            comparison_table = comparison_table.sort_index(key=lambda x: pd.Categorical(x, categories=metrics_order, ordered=True))
            def _safe_fmt(v):
                try:
                    return f"{v:.2f}"
                except Exception:
                    return v

            styled_comparison = comparison_table.style.format(_safe_fmt)
            display(HTML(styled_comparison.to_html()))
            
            plt.figure(figsize=(18, 8))
            sns.barplot(data=melted_df, x='Metric', y='Value', hue='Case')
            plt.title(f"{title} - Base Case vs Scenario Comparison by PV Size", fontsize=14, pad=15)
            plt.xticks(rotation=45, ha='right')
            plt.ylabel("Absolute Value")
            plt.axhline(0, color='black', linewidth=0.8)
            plt.tight_layout()
            plt.show()

except ImportError:
    def show_sweep_comparison(sweep_results, title="PV Sweep Comparison"):
        pass

if __name__ == "__main__":
    base, scen = run_scenario(duration_days=4, heat_demand_factor=2.0)
    print("Base:"); [print(f"  {k:28}: {v:8.2f}") for k, v in base.items()]
    print("Scenario:"); [print(f"  {k:28}: {v:8.2f}") for k, v in scen.items()]