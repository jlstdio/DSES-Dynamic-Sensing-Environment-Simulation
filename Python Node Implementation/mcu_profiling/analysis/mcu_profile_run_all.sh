#!/bin/bash
# ESP32-C3 Energy Profiling

cd "$(dirname "$0")"

# Check if data folder exists and has CSV files
if [ ! -d "data" ] || [ -z "$(ls data/*.csv 2>/dev/null)" ]; then
    echo -e "\ndata/ no csv in folder"
    exit 1
fi

# Create results directory
mkdir -p results

# Run scripts
scripts=(
    "analyze_detailed_energy.py"
    "create_sensor_independent_summary.py"
    "create_summary_reports.py"
)

for item in "${scripts[@]}"; do
    IFS='|' read -r step desc script <<< "$item"
    echo -n -e "\n[$step] $desc... "
    
    if python3 "$script" > /dev/null 2>&1; then
        echo "ok"
    else
        echo "failed"
        python3 "$script" 2>&1
        exit 1
    fi
done

echo -e "\nDone"
exit 0
