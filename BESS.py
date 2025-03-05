import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from scipy.optimize import minimize

# Streamlit UI
st.title("BESS Analysis Tool")

# File Upload
uploaded_file = st.file_uploader("Upload CSV file", type=["csv"])

if uploaded_file is not None:
    try:
        df = pd.read_csv(uploaded_file)
        if 'Slack' not in df.columns:
            st.error("The uploaded CSV must have a 'Slack' column.")
            st.stop()
    except Exception as e:
        st.error(f"Error reading CSV: {e}")
        st.stop()

    # Initial Variables Adjustment
    MW = st.number_input("MW (Constant)", value=df.iloc[0, 1] if 'MW' in df.columns else 10.0)
    MWh = st.number_input("MWh (Constant)", value=df.iloc[0, 2] if 'MWh' in df.columns else 50.0)
    efficiency = st.slider("Efficiency (%)", min_value=0.0, max_value=1.0, value=0.97, step=0.01)
    min_bess_charge_percent = st.slider("Minimum BESS Charge (%)", min_value=0.0, max_value=1.0, value=0.15, step=0.01)
    max_bess_charge_percent = st.slider("Maximum BESS Charge (%)", min_value=0.0, max_value=1.0, value=0.95, step=0.01)

    min_bess_charge = min_bess_charge_percent * MWh
    max_bess_charge = max_bess_charge_percent * MWh

    # Slack values from the uploaded CSV
    slack_values = df['Slack'].values

    # Define the objective function for optimization
    def objective_function(params, slack_values, efficiency, min_bess_charge, max_bess_charge):
        peak_discharge_rate, bess_capacity = params
        bess_charge = min_bess_charge
        lack_of_energy = 0
        excess_of_energy = 0

        for slack in slack_values:
            if slack > 0:
                room_to_min = bess_charge - min_bess_charge
                discharge_amount = min(slack / efficiency, peak_discharge_rate, room_to_min)
                bess_charge -= discharge_amount
                lack_of_energy += slack - (discharge_amount * efficiency)
            elif slack < 0:
                room_to_max = max_bess_charge - bess_charge
                charge_amount = min(abs(slack) * efficiency, peak_discharge_rate, room_to_max)
                bess_charge += charge_amount
                excess_of_energy += abs(slack) - (charge_amount / efficiency)

        return abs(lack_of_energy - excess_of_energy)

    # Initial guesses for peak discharge rate and BESS capacity
    initial_guess = [MW, MWh]  # MW and MWh

    # Bounds for peak discharge rate and BESS capacity
    bounds = [(0, None), (0, None)]

    # Constraints
    constraints = [
        {'type': 'ineq', 'fun': lambda x: max_bess_charge - x[1]},  # BESS capacity <= max_bess_charge
        {'type': 'ineq', 'fun': lambda x: x[1] - min_bess_charge}   # BESS capacity >= min_bess_charge
    ]

    # Run the optimization
    result = minimize(
        objective_function,
        initial_guess,
        args=(slack_values, efficiency, min_bess_charge, max_bess_charge),
        bounds=bounds,
        constraints=constraints
    )

    # Extract the optimized values
    optimal_peak_discharge_rate, optimal_bess_capacity = result.x

    # Display optimized values
    st.write(f"Optimized Peak Discharge Rate for BESS: {optimal_peak_discharge_rate:.2f} MW")
    st.write(f"Optimized BESS Capacity: {optimal_bess_capacity:.2f} MWh")

    # Processing Logic with Optimized Values
    bess_values = []
    energy_flow_values = []
    cycles_per_month = {}  # To store the number of cycles per month
    in_discharge_cycle = False
    last_bess_charge = min_bess_charge

    # Add a 'Month' column to the dataframe
    hours_per_day = 24
    days_per_month = 30
    df['Month'] = (df.index // (hours_per_day * days_per_month)) + 1

    for idx, slack in enumerate(slack_values):
        energy_flow = 0

        if slack > 0:
            room_to_min = last_bess_charge - min_bess_charge
            discharge_amount = min(slack / efficiency, optimal_peak_discharge_rate, room_to_min)
            last_bess_charge -= discharge_amount
            energy_flow = discharge_amount * efficiency

        elif slack < 0:
            room_to_max = max_bess_charge - last_bess_charge
            charge_amount = min(abs(slack) * efficiency, optimal_peak_discharge_rate, room_to_max)
            last_bess_charge += charge_amount
            energy_flow = -charge_amount / efficiency

        bess_values.append(last_bess_charge)
        energy_flow_values.append(energy_flow)

        # Check for cycles
        if last_bess_charge >= max_bess_charge:
            if in_discharge_cycle:
                # Increment cycle count for the current month
                current_month = df.loc[idx, 'Month']
                cycles_per_month[current_month] = cycles_per_month.get(current_month, 0) + 1
                in_discharge_cycle = False
        elif last_bess_charge <= min_bess_charge:
            in_discharge_cycle = True

    # Create a DataFrame for cycles per month
    cycles_df = pd.DataFrame(list(cycles_per_month.items()), columns=['Month', 'Cycles'])

    # Plot the bar chart for cycles per month
    st.write("### Number of Cycles per Month")
    fig_cycles, ax = plt.subplots(figsize=(10, 6))
    cycles_df.plot(kind='bar', x='Month', y='Cycles', ax=ax, legend=False, color='blue')
    ax.set_xlabel('Month')
    ax.set_ylabel('Number of Cycles')
    ax.set_title('Number of Cycles per Month')
    ax.grid(True)
    st.pyplot(fig_cycles)

    # Output DataFrame
    output_df = pd.DataFrame({
        'BESS Charge': bess_values,
        'Energy Flow': energy_flow_values,
        'Slack': slack_values,
        'Month': df['Month']
    })

    # Display the total number of cycles
    total_cycles = cycles_df['Cycles'].sum()
    st.write(f"The BESS completed {total_cycles} full cycles.")

    # Download Output CSV
    csv_buffer = io.StringIO()
    output_df.to_csv(csv_buffer, index=False)
    st.download_button(
        label="Download BESS.csv",
        data=csv_buffer.getvalue().encode('utf-8'),
        file_name='BESS.csv',
        mime='text/csv'
    )
