import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import io
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
    transition_count = 0
    cycle_count = 0
    in_discharge_cycle = False
    last_bess_charge = min_bess_charge

    for slack in slack_values:
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

        if last_bess_charge >= max_bess_charge:
            if in_discharge_cycle:
                cycle_count += 1
                in_discharge_cycle = False
        elif last_bess_charge <= min_bess_charge:
            in_discharge_cycle = True

    output_df = pd.DataFrame({
        'BESS Charge': bess_values,
        'Energy Flow': energy_flow_values,
        'Slack': slack_values
    })

    st.write(f"The BESS completed {cycle_count} full cycles.")

    # Average Annual Daily Profile Calculation
    hours_per_day = 24
    days_per_year = 365

    bess_charge_daily = output_df['BESS Charge'].values.reshape(days_per_year, hours_per_day)
    energy_flow_daily = output_df['Energy Flow'].values.reshape(days_per_year, hours_per_day)
    slack_daily = output_df['Slack'].values.reshape(days_per_year, hours_per_day)

    average_bess_charge = bess_charge_daily.mean(axis=0)
    average_energy_flow = energy_flow_daily.mean(axis=0)
    average_slack = slack_daily.mean(axis=0)

    # Plotting Average Annual Daily Profile
    fig, axs = plt.subplots(3, 1, figsize=(12, 8))

    axs[0].plot(average_bess_charge, label='BESS Charge (MWh)', color='blue')
    axs[0].set_title('Average Annual Daily Profile: BESS Charge')
    axs[0].set_xlabel('Hour of the Day')
    axs[0].set_ylabel('BESS Charge (MWh)')
    axs[0].grid(True)

    axs[1].plot(average_energy_flow, label='Energy Flow (MW)', color='green')
    axs[1].set_title('Average Annual Daily Profile: Energy Flow')
    axs[1].set_xlabel('Hour of the Day')
    axs[1].set_ylabel('Energy Flow (MW)')
    axs[1].grid(True)

    axs[2].plot(average_slack, label='Slack (MW)', color='red')
    axs[2].set_title('Average Annual Daily Profile: Slack')
    axs[2].set_xlabel('Hour of the Day')
    axs[2].set_ylabel('Slack (MW)')
    axs[2].grid(True)

    plt.tight_layout()
    st.pyplot(fig)

    # Monthly Clustered Column Chart
    output_df['Month'] = (df.index // (hours_per_day * 30)) % 12 + 1
    monthly_stats = output_df.groupby('Month').agg({
        'Slack': [
            lambda x: x[x > 0].sum(),
            lambda x: x[x < 0].sum()
        ],
        'Energy Flow': [
            lambda x: x[x > 0].sum(),
            lambda x: x[x < 0].sum()
        ]
    })
    monthly_stats.columns = ['Lack of Energy', 'Excess of energy', 'Energy From BESS', 'Energy to BESS']

    fig2 = plt.figure(figsize=(10, 6))
    monthly_stats.plot(kind='bar', ax=fig2.gca(), color=['orange', 'red', 'green', 'darkgreen'])
    plt.title('Monthly Energy Flow')
    plt.ylabel('MWh')
    plt.xlabel('Month')
    plt.xticks(rotation=0)
    plt.grid(True)
    plt.tight_layout()
    st.pyplot(fig2)

    # Download Output CSV
    csv_buffer = io.StringIO()
    output_df.to_csv(csv_buffer, index=False)
    st.download_button(
        label="Download BESS.csv",
        data=csv_buffer.getvalue().encode('utf-8'),
        file_name='BESS.csv',
        mime='text/csv'
    )
