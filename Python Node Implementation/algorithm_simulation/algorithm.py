import simpy
import random
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.gridspec import GridSpec
import math
import csv 

RUN_ALL_COMPARISON = False 
SELECTED_SCENARIO = "BOTH"

NUM_NODES = 100            
COMM_RANGE = 20# 10

SIM_DURATION = 10000000 # ms
ANIMATION_SPEED_FACTOR = 500 
ANIMATION_FRAME_STEP = 1000 

# ==========================================
# 1. HARDWARE & ENVIRONMENT PROFILE
# ==========================================

UNIT_SCALE = 1e-6 
BATTERY_CAPACITY_MAH = 50.0
VOLTAGE_NOMINAL = 3.7
BATTERY_JOULES = BATTERY_CAPACITY_MAH * VOLTAGE_NOMINAL * 3.6 

SOLAR_GENERATION_SUNNY = 300.0   
SOLAR_GENERATION_SHADY = 50.0    

POWER_IDLE = 434.85
POWER_SENSING = 439.48

INFERENCE_PROFILE = {
    0: {"time_ms": 1305, "energy_uJ": 577770},
    1: {"time_ms": 1603, "energy_uJ": 800620},
    2: {"time_ms": 2400, "energy_uJ": 1197630},
    3: {"time_ms": 3207, "energy_uJ": 1589970},
    4: {"time_ms": 3845, "energy_uJ": 1901280},
}

TX_PROFILE = {
    0: {"time_ms": 30.50, "energy_uJ": 24555},
    1: {"time_ms": 138.00, "energy_uJ": 70284},
    2: {"time_ms": 137.61, "energy_uJ": 69073},
    3: {"time_ms": 26.75, "energy_uJ": 23596},
    4: {"time_ms": 27.80, "energy_uJ": 22226},
}

CYCLE_TIME = 10000 
HANDOVER_WINDOW = 200 
ALPHA = 0.2 
TASK_GENERATION_RATE = 1/100 
VOLTAGE_THRESHOLD = 3.3 

# ==========================================
# 2. CORE CLASSES
# ==========================================

class Packet:
    def __init__(self, sender_id, voltage, timestamp, msg_type="BEACON", task=None):
        self.sender_id = sender_id
        self.voltage = voltage
        self.timestamp = timestamp
        self.msg_type = msg_type
        self.task = task

class Task:
    def __init__(self, task_id, start_layer=0):
        self.task_id = task_id
        self.current_layer = start_layer
        self.completed = False
        self.path = [] 

class Node:
    def __init__(self, env, node_id, pos, neighbors, is_sunny, use_smart_sched, use_smart_offload):
        self.env = env
        self.node_id = node_id
        self.pos = pos 
        self.neighbors = neighbors
        self.is_sunny = is_sunny
        self.use_smart_sched = use_smart_sched
        self.use_smart_offload = use_smart_offload
        
        # [수정] 초기 배터리 레벨을 랜덤하게 설정 (10% ~ 90%)
        initial_level = random.uniform(0.1, 0.9)
        self.current_energy_joules = BATTERY_JOULES * initial_level
        self.is_deep_sleep = False 
        
        self.sleep_time = random.uniform(0, CYCLE_TIME)
        self.neighbor_table = {
            nid: {"predicted_v": 3.7, "last_seen_my_v": 3.7, "offset": 0.0} 
            for nid in neighbors
        }
        
        # Metrics
        self.history_active = [] 
        self.history_voltage = [] 
        self.history_predictions = {nid: [] for nid in neighbors} 
        
        # Processes
        self.env.process(self.run_cycle())
        self.env.process(self.solar_charging())
        self.env.process(self.task_generator())
        self.inbox = simpy.Store(env)

    def get_voltage(self):
        ratio = self.current_energy_joules / BATTERY_JOULES
        return 3.0 + (1.2 * ratio)

    def consume_energy_fixed(self, uJ):
        joules = uJ * UNIT_SCALE
        self.current_energy_joules -= joules
        if self.current_energy_joules < 0: self.current_energy_joules = 0

    def consume_energy(self, mw, duration_ms):
        joules = (mw / 1000.0) * (duration_ms / 1000.0)
        self.current_energy_joules -= joules
        if self.current_energy_joules < 0: self.current_energy_joules = 0

    def predict_neighbor_voltage(self, target_id):
        entry = self.neighbor_table[target_id]
        my_v_now = self.get_voltage()
        my_v_last = entry["last_seen_my_v"]
        
        delta_me = my_v_now - my_v_last
        return entry["predicted_v"] + delta_me + entry["offset"]

    def update_offset(self, sender_id, sender_real_voltage):
        entry = self.neighbor_table[sender_id]
        predicted_v = self.predict_neighbor_voltage(sender_id)
        error = sender_real_voltage - predicted_v
        entry["offset"] += ALPHA * error
        entry["last_seen_my_v"] = self.get_voltage()
        entry["predicted_v"] = sender_real_voltage 
        self.history_predictions[sender_id].append((self.env.now, predicted_v))

    def broadcast(self, packet):
        for nid in self.neighbors:
            nodes[nid].inbox.put(packet)
            
    def run_cycle(self):
        yield self.env.timeout(self.sleep_time)
        while True:
            # 0. RECOVERY & HYSTERESIS
            battery_ratio = self.current_energy_joules / BATTERY_JOULES
            
            if self.is_deep_sleep:
                if battery_ratio >= 0.2: # Recovery at 20%
                    self.is_deep_sleep = False
                else:
                    yield self.env.timeout(1000)
                    continue
            else:
                if battery_ratio <= 0.01: # Die at 1%
                    self.is_deep_sleep = True
                    yield self.env.timeout(1000)
                    continue
            
            cycle_start = self.env.now
            
            # 1. DYNAMIC SENSING
            reserved_uJ = INFERENCE_PROFILE[4]["energy_uJ"] + TX_PROFILE[0]["energy_uJ"] + (POWER_IDLE * HANDOVER_WINDOW)
            reserved_joules = (reserved_uJ * UNIT_SCALE) * 1.1 

            available_joules = self.current_energy_joules - reserved_joules
            
            dynamic_sensing_ms = 0
            if available_joules > 0:
                dynamic_sensing_ms = (available_joules * 1e6) / POWER_SENSING
            
            if dynamic_sensing_ms > 0:
                self.consume_energy(POWER_SENSING, dynamic_sensing_ms)
                self.history_active.append((cycle_start, self.env.now + dynamic_sensing_ms))
                self.history_voltage.append((self.env.now, self.get_voltage()))
                yield self.env.timeout(dynamic_sensing_ms)
            
            # 2. SCHEDULING & HANDOVER
            next_sleep = CYCLE_TIME 
            
            if self.use_smart_sched:
                self.consume_energy(POWER_IDLE, HANDOVER_WINDOW)
                yield self.env.timeout(HANDOVER_WINDOW)
                
                received = []
                while self.inbox.items:
                    pkt = yield self.inbox.get()
                    if pkt.timestamp >= cycle_start: received.append(pkt)
                
                collision_detected = False
                cooperation_needed = False
                
                for pkt in received:
                    if self.use_smart_offload: self.update_offset(pkt.sender_id, pkt.voltage)
                    
                    arrival_time = pkt.timestamp
                    rel_time = arrival_time - cycle_start
                    
                    if rel_time < dynamic_sensing_ms:
                        collision_detected = True 
                    else:
                        cooperation_needed = True 
                        if pkt.msg_type == "TASK": 
                            self.env.process(self.process_task_chain(pkt.task))

                if collision_detected:
                    shift = random.uniform(500, 2000)
                    next_sleep += shift
                elif cooperation_needed:
                    next_sleep += random.uniform(-10, 10)
                else:
                    next_sleep += random.uniform(-5, 5) 

            else:
                while self.inbox.items:
                    pkt = yield self.inbox.get()
                    if pkt.msg_type == "TASK": self.env.process(self.process_task_chain(pkt.task))
                next_sleep = random.uniform(CYCLE_TIME * 0.5, CYCLE_TIME * 1.5)

            # 3. BROADCAST
            if self.current_energy_joules > (TX_PROFILE[0]["energy_uJ"] * UNIT_SCALE):
                my_pkt = Packet(self.node_id, self.get_voltage(), self.env.now)
                self.consume_energy_fixed(TX_PROFILE[0]["energy_uJ"])
                yield self.env.timeout(TX_PROFILE[0]["time_ms"])
                self.broadcast(my_pkt)
            
            # 4. SLEEP
            elapsed = self.env.now - cycle_start
            sleep_duration = max(0, next_sleep - elapsed)
            yield self.env.timeout(sleep_duration)

    def task_generator(self):
        while True:
            inter = random.expovariate(TASK_GENERATION_RATE)
            yield self.env.timeout(inter)
            if not self.is_deep_sleep:
                task = Task(f"{self.node_id}_{int(self.env.now)}")
                self.env.process(self.process_task_chain(task))

    def process_task_chain(self, task):
        while task.current_layer < 5:
            if self.is_deep_sleep or self.current_energy_joules <= 0: break 

            layer = task.current_layer
            task.path.append(self.node_id)
            prof = INFERENCE_PROFILE[layer]
            self.consume_energy_fixed(prof["energy_uJ"])
            yield self.env.timeout(prof["time_ms"])
            
            task.current_layer += 1
            if task.current_layer >= 5:
                task.completed = True
                break
                
            target = self.node_id
            
            if self.use_smart_offload:
                best_v = self.get_voltage()
                for nid in self.neighbor_table:
                    pred_v = self.predict_neighbor_voltage(nid)
                    if pred_v > best_v:
                        best_v = pred_v
                        target = nid
                if target == self.node_id or self.get_voltage() >= VOLTAGE_THRESHOLD:
                    target = self.node_id
            else:
                if random.random() < 0.5 and self.neighbors:
                    target = random.choice(self.neighbors)
                else:
                    target = self.node_id

            if target != self.node_id:
                pkt = Packet(self.node_id, self.get_voltage(), self.env.now, "TASK", task)
                self.consume_energy_fixed(TX_PROFILE[layer]["energy_uJ"])
                yield self.env.timeout(TX_PROFILE[layer]["time_ms"])
                nodes[target].inbox.put(pkt)
                return 

    def solar_charging(self):
        while True:
            yield self.env.timeout(1000)
            gen = SOLAR_GENERATION_SUNNY if self.is_sunny else SOLAR_GENERATION_SHADY
            self.current_energy_joules = min(self.current_energy_joules + (gen/1000.0), BATTERY_JOULES)


# ==========================================
# 3. SETUP & HELPERS
# ==========================================

nodes = {}

def generate_spiral_hex_grid(n, radius=2.0):
    coords = []
    max_ring = int(math.sqrt(n)) + 2
    for q in range(-max_ring, max_ring+1):
        for r in range(-max_ring, max_ring+1):
            coords.append((q, r))
    coords.sort(key=lambda p: max(abs(p[0]), abs(p[1]), abs(-p[0]-p[1])))
    final_coords = coords[:n]
    
    pos = {}
    for i, (q, r) in enumerate(final_coords):
        x = radius * (3/2 * q)
        y = radius * (math.sqrt(3)/2 * q  +  math.sqrt(3) * r)
        pos[i] = (x, y)
    return pos

def get_neighbors(pos, r):
    adj = {i: [] for i in pos}
    ids = list(pos.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            u, v = ids[i], ids[j]
            dist = np.linalg.norm(np.array(pos[u]) - np.array(pos[v]))
            if dist <= r:
                adj[u].append(v)
                adj[v].append(u)
    return adj

def run_single_simulation(scenario, duration, visible_print=True):
    global nodes
    env = simpy.Environment()
    
    pos = generate_spiral_hex_grid(NUM_NODES)
    adj = get_neighbors(pos, COMM_RANGE)
    
    smart_sched = scenario in ["ALGO1_ONLY", "BOTH"]
    smart_offload = scenario in ["ALGO2_ONLY", "BOTH"]
    
    nodes = {}
    for i in range(NUM_NODES):
        # 햇빛 분포를 듬성듬성하게(랜덤하게) 배치 (50% 확률)
        is_sunny = (random.random() < 0.5)
        nodes[i] = Node(env, i, pos[i], adj[i], is_sunny, smart_sched, smart_offload)
        
    if visible_print:
        print(f"Running Scenario: [{scenario}] for {duration/1000}s ...")
    env.run(until=duration)
    
    dead_nodes = sum([1 for n in nodes.values() if n.current_energy_joules <= 1.0]) 
    
    total_sim_time_all_nodes = duration * NUM_NODES
    total_active_time = sum([sum([e-s for s,e in n.history_active]) for n in nodes.values()])
    avg_coverage = (total_active_time / total_sim_time_all_nodes) * 100 
    
    return nodes, avg_coverage, dead_nodes

# ==========================================
# 4. EXECUTION FLOW & STATIC PLOTTING
# ==========================================

def save_to_csv(times, cov_data, eff_data, error_mae):
    filename = "simulation_results.csv"
    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([
            "Time_ms", 
            "Cov_Total_Pct", "Cov_Sunny_Pct", "Cov_Shady_Pct", 
            "Eff_Total_AvgNodes", "Eff_Sunny_AvgNodes", "Eff_Shady_AvgNodes",
            "Avg_Prediction_Error_V"
        ])
        
        for i in range(len(times)):
            writer.writerow([
                times[i], 
                f"{cov_data['total'][i]:.2f}", 
                f"{cov_data['sunny'][i]:.2f}", 
                f"{cov_data['shady'][i]:.2f}", 
                f"{eff_data['total'][i]:.4f}", 
                f"{eff_data['sunny'][i]:.4f}", 
                f"{eff_data['shady'][i]:.4f}", 
                f"{error_mae[i]:.4f}"
            ])
    print(f"Simulation data saved to '{filename}'")

def print_statistics(name, data):
    # data can contain NaN, so use nanmean etc.
    avg_val = np.nanmean(data)
    std_val = np.nanstd(data)
    min_val = np.nanmin(data)
    max_val = np.nanmax(data)
    print(f"[{name}] Avg: {avg_val:.4f}, Std: {std_val:.4f}, Min: {min_val:.4f}, Max: {max_val:.4f}")

def run_comparison_experiment():
    print("========================================")
    print("   ECO-COOP 4-WAY COMPARISON EXPERIMENT   ")
    print("========================================")
    
    scenarios = ["RANDOM", "ALGO1_ONLY", "ALGO2_ONLY", "BOTH"]
    results_cov = []
    results_dead = []
    
    COMPARE_DURATION = 50000 
    
    for sc in scenarios:
        _, cov, dead = run_single_simulation(sc, COMPARE_DURATION, True)
        results_cov.append(cov)
        results_dead.append(dead)
        print(f" -> {sc}: Cov={cov:.2f}%, Dead Nodes={dead}")
        
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    ax1.bar(scenarios, results_cov, color=['gray', 'blue', 'orange', 'green'])
    ax1.set_title("Avg Active Duty Cycle (%)")
    ax2.bar(scenarios, results_dead, color=['red', 'orange', 'red', 'green'])
    ax2.set_title(f"Dead Nodes Count (after {COMPARE_DURATION/1000}s)")
    plt.tight_layout()
    plt.savefig('comparison_analysis.png')

def run_main_visualization():
    global nodes
    print(f"\nStarting Full Visualization for: {SELECTED_SCENARIO}")
    nodes, _, _ = run_single_simulation(SELECTED_SCENARIO, SIM_DURATION, True)
    
    plot_static_summary(nodes)
    animate_simulation(nodes)

def find_triangles(nodes):
    triangles = []
    seen = set()
    for n_id, node in nodes.items():
        neighbors = node.neighbors
        for i in range(len(neighbors)):
            for j in range(i + 1, len(neighbors)):
                n1 = neighbors[i]
                n2 = neighbors[j]
                if n2 in nodes[n1].neighbors:
                    tri = tuple(sorted((n_id, n1, n2)))
                    if tri not in seen:
                        seen.add(tri)
                        sunny_count = sum([1 for n in tri if nodes[n].is_sunny])
                        is_sunny_area = (sunny_count >= 2)
                        triangles.append((tri, is_sunny_area))
    return triangles

def plot_static_summary(nodes):
    # [수정] 그래프 레이아웃 확장 (3행 2열)
    fig = plt.figure(figsize=(20, 24))
    
    # ----------------------------------------------------
    # Plot 1: Active Nodes (Top-Left)
    # ----------------------------------------------------
    ax1 = fig.add_subplot(3, 2, 1)
    for nid, node in nodes.items():
        ranges = [(s, e-s) for s, e in node.history_active]
        if ranges:
            color = 'gold' if node.is_sunny else 'dimgray'
            ax1.broken_barh(ranges, (nid-0.4, 0.8), facecolors=color, alpha=0.6)
    ax1.set_xlim(0, SIM_DURATION)
    ax1.set_ylim(-1, NUM_NODES)
    ax1.set_title(f"1. Node Activation (Yellow=Sunny, Gray=Shady)")
    ax1.set_xlabel("Time (ms)")
    ax1.set_ylabel("Node ID")
    ax1.grid(True, alpha=0.2)

    # ----------------------------------------------------
    # Plot 2: Area Coverage Heatmap (Top-Right)
    # ----------------------------------------------------
    ax2 = fig.add_subplot(3, 2, 2)
    
    tri_info = find_triangles(nodes)
    triangles = [t[0] for t in tri_info]
    
    if not triangles:
        ax2.text(0.5, 0.5, "No Triangular Areas Found", ha='center')
        return # Cannot process further without triangles
    
    triangles.sort()
    num_tris = len(triangles)
    sunny_tri_indices = [i for i, t in enumerate(tri_info) if t[1]]
    shady_tri_indices = [i for i, t in enumerate(tri_info) if not t[1]]
    
    heatmap_res = 1000 # Resolution slightly lowered for speed
    times = np.arange(0, SIM_DURATION, heatmap_res)
    heatmap_data = np.zeros((num_tris, len(times)))
    
    node_active = {n: nodes[n].history_active for n in nodes}
    
    # Data storage for plots and stats
    cov_data = {'total': [], 'sunny': [], 'shady': []}
    eff_data = {'total': [], 'sunny': [], 'shady': []}
    
    # Voltage prediction error setup
    resampled_voltages = {}
    for nid in nodes:
        hist = np.array(nodes[nid].history_voltage)
        if len(hist) > 0:
            interp_v = np.interp(times, hist[:,0], hist[:,1])
            resampled_voltages[nid] = interp_v
        else:
            resampled_voltages[nid] = np.zeros_like(times)
    
    prediction_mae_over_time = []

    # --- MAIN LOOP FOR STATISTICS ---
    for t_idx, t in enumerate(times):
        active_nodes_at_t = set()
        for nid in range(NUM_NODES):
            for s, e in node_active[nid]:
                if s <= t <= e:
                    active_nodes_at_t.add(nid)
                    break
        
        # Coverage & Efficiency Calculation
        # Efficiency = Sum(Active Nodes in Covered Area) / Count(Covered Areas)
        # Ideal Efficiency = 1.0 (Exact Cover)
        
        # Helper for calculating stats per group
        def calc_stats(indices):
            if not indices: return 0.0, np.nan
            
            covered_count = 0
            total_active_nodes_in_covered = 0
            
            for idx in indices:
                tri = triangles[idx]
                # Count how many nodes in this triangle are active
                nodes_in_tri_active = sum(1 for n in tri if n in active_nodes_at_t)
                
                if nodes_in_tri_active > 0:
                    covered_count += 1
                    total_active_nodes_in_covered += nodes_in_tri_active
                    heatmap_data[idx, t_idx] = 1 # Mark heatmap
            
            coverage_pct = (covered_count / len(indices)) * 100
            
            if covered_count > 0:
                efficiency = total_active_nodes_in_covered / covered_count
            else:
                efficiency = np.nan # No coverage, undefined efficiency
                
            return coverage_pct, efficiency

        # 1. Total
        c_tot, e_tot = calc_stats(range(num_tris))
        cov_data['total'].append(c_tot)
        eff_data['total'].append(e_tot)
        
        # 2. Sunny
        c_sun, e_sun = calc_stats(sunny_tri_indices)
        cov_data['sunny'].append(c_sun)
        eff_data['sunny'].append(e_sun)
        
        # 3. Shady
        c_sha, e_sha = calc_stats(shady_tri_indices)
        cov_data['shady'].append(c_sha)
        eff_data['shady'].append(e_sha)

        # Prediction Error
        errors_at_t = []
        if SELECTED_SCENARIO in ["ALGO2_ONLY", "BOTH"]:
            for nid, node in nodes.items():
                for target_id, pred_list in node.history_predictions.items():
                    if not pred_list: continue
                    p_arr = np.array(pred_list)
                    if len(p_arr) == 0 or p_arr[0,0] > t: continue
                    idx = np.searchsorted(p_arr[:,0], t)
                    if idx > 0:
                        pred_val = p_arr[idx-1, 1]
                        real_val = resampled_voltages[target_id][t_idx]
                        errors_at_t.append(abs(pred_val - real_val))
        prediction_mae_over_time.append(np.mean(errors_at_t) if errors_at_t else 0)

    # --- HEATMAP PLOT ---
    im = ax2.imshow(heatmap_data, aspect='auto', cmap='Greens', interpolation='nearest',
                    extent=[0, SIM_DURATION, num_tris, 0], vmin=0, vmax=1)
    ax2.set_title(f"2. Area Coverage Heatmap\nTotal: {num_tris} (Sunny: {len(sunny_tri_indices)}, Shady: {len(shady_tri_indices)})")
    ax2.set_xlabel("Time (ms)")
    ax2.set_ylabel("Area ID")

    # --- PRINT & SAVE STATISTICS ---
    print("\n" + "="*40)
    print("   SIMULATION STATISTICS REPORT   ")
    print("="*40)
    
    print("\n[1. Coverage %]")
    print_statistics("Total Coverage", cov_data['total'])
    print_statistics("Sunny Coverage", cov_data['sunny'])
    print_statistics("Shady Coverage", cov_data['shady'])
    
    print("\n[2. Efficiency (Avg Active Nodes per Covered Area)]")
    print("(Note: Lower is better. Ideal = 1.0. Shows redundancy.)")
    print_statistics("Total Efficiency", eff_data['total'])
    print_statistics("Sunny Efficiency", eff_data['sunny'])
    print_statistics("Shady Efficiency", eff_data['shady'])
    print("="*40 + "\n")
    
    save_to_csv(times, cov_data, eff_data, prediction_mae_over_time)

    # ----------------------------------------------------
    # Plot 3: Coverage Analysis (Middle-Left)
    # ----------------------------------------------------
    ax3 = fig.add_subplot(3, 2, 3)
    ax3.set_title("3. Coverage Ratio (%)")
    ax3.plot(times, cov_data['total'], 'g-', label='Total', linewidth=2, alpha=0.5)
    ax3.plot(times, cov_data['sunny'], color='orange', linestyle='-', label='Sunny', linewidth=1.5)
    ax3.plot(times, cov_data['shady'], color='navy', linestyle='-', label='Shady', linewidth=1.5)
    ax3.set_xlabel("Time (ms)")
    ax3.set_ylabel("Coverage (%)")
    ax3.set_ylim(0, 105)
    ax3.grid(True, alpha=0.3)
    ax3.legend()

    # ----------------------------------------------------
    # Plot 4: Efficiency Analysis (Middle-Right) [NEW]
    # ----------------------------------------------------
    ax4 = fig.add_subplot(3, 2, 4)
    ax4.set_title("4. Efficiency (Redundancy: Avg Nodes/Area)\n(Ideal=1.0, Lower is Better)")
    ax4.plot(times, eff_data['total'], 'g-', label='Total', linewidth=2, alpha=0.5)
    ax4.plot(times, eff_data['sunny'], color='orange', linestyle='-', label='Sunny', linewidth=1.5)
    ax4.plot(times, eff_data['shady'], color='navy', linestyle='-', label='Shady', linewidth=1.5)
    ax4.axhline(y=1.0, color='r', linestyle='--', label='Ideal (1.0)')
    ax4.set_xlabel("Time (ms)")
    ax4.set_ylabel("Avg Nodes per Area")
    ax4.set_ylim(0.8, 3.5) # Scale adjustment
    ax4.grid(True, alpha=0.3)
    ax4.legend()

    # ----------------------------------------------------
    # Plot 5: Prediction Error (Bottom-Left)
    # ----------------------------------------------------
    ax5 = fig.add_subplot(3, 2, 5)
    ax5.set_title("5. Voltage Prediction Error (MAE)")
    ax5.plot(times, prediction_mae_over_time, 'r-', label='Error')
    ax5.set_xlabel("Time (ms)")
    ax5.set_ylabel("Error (V)")
    ax5.set_ylim(0, 0.5)
    ax5.grid(True)

    # ----------------------------------------------------
    # Plot 6: Best Predictions Samples (Bottom-Right)
    # ----------------------------------------------------
    ax6 = fig.add_subplot(3, 2, 6)
    ax6.set_title("6. Top 10 Prediction Samples")
    ax6.set_xlabel("Time (ms)")
    ax6.set_ylabel("Voltage (V)")
    
    prediction_errors = [] 
    if SELECTED_SCENARIO in ["ALGO2_ONLY", "BOTH"]:
        for obs_id, obs_node in nodes.items():
            for tgt_id, pred_list in obs_node.history_predictions.items():
                if not pred_list: continue
                tgt_hist = np.array(nodes[tgt_id].history_voltage)
                pred_arr = np.array(pred_list)
                if len(tgt_hist) < 2 or len(pred_arr) < 2: continue
                start_t = max(tgt_hist[0,0], pred_arr[0,0])
                end_t = min(tgt_hist[-1,0], pred_arr[-1,0])
                if end_t <= start_t: continue
                eval_times = np.linspace(start_t, end_t, 100)
                act_vals = np.interp(eval_times, tgt_hist[:,0], tgt_hist[:,1])
                est_vals = np.interp(eval_times, pred_arr[:,0], pred_arr[:,1])
                mae = np.mean(np.abs(act_vals - est_vals))
                prediction_errors.append((mae, obs_id, tgt_id))
        
        prediction_errors.sort(key=lambda x: x[0])
        top_10 = prediction_errors[:10]
        colors = plt.cm.tab10(np.linspace(0,1,10))
        for i, (mae, oid, tid) in enumerate(top_10):
            pred_list = nodes[oid].history_predictions[tid]
            pred_arr = np.array(pred_list)
            ax6.plot(pred_arr[:,0], pred_arr[:,1], linestyle='-', color=colors[i], label=f"{oid}->{tid}")
            tgt_hist = np.array(nodes[tid].history_voltage)
            ax6.plot(tgt_hist[:,0], tgt_hist[:,1], linestyle=':', color=colors[i], alpha=0.5)
        if top_10: ax6.legend(fontsize='x-small', ncol=2)
    else:
        ax6.text(0.5, 0.5, "Prediction Algo Not Active", ha='center')
    ax6.grid(True)

    plt.tight_layout()
    plt.savefig('eco_coop_results.png')
    print("Static summary plot saved as 'eco_coop_results.png'")

# ==========================================
# 5. ANIMATION
# ==========================================

def animate_simulation(nodes):
    time_steps = np.arange(0, SIM_DURATION, ANIMATION_FRAME_STEP)
    fig = plt.figure(figsize=(16, 10))
    gs = GridSpec(2, 2, height_ratios=[1.5, 1])
    
    # Topo
    ax_topo = fig.add_subplot(gs[0, 0])
    all_x = [n.pos[0] for n in nodes.values()]
    all_y = [n.pos[1] for n in nodes.values()]
    pad=2
    ax_topo.set_xlim(min(all_x)-pad, max(all_x)+pad)
    ax_topo.set_ylim(min(all_y)-pad, max(all_y)+pad)
    ax_topo.axvspan(0, max(all_x)+pad, color='orange', alpha=0.1) # Sunny Zone
    ax_topo.axvspan(min(all_x)-pad, 0, color='grey', alpha=0.1)   # Shady Zone
    scat = ax_topo.scatter(all_x, all_y, s=80, c='grey', edgecolors='k')
    
    # Voltage
    ax_volt = fig.add_subplot(gs[1, :])
    sorted_nodes = sorted(nodes.values(), key=lambda n: n.pos[0])
    observer = sorted_nodes[0]
    targets = observer.neighbors[:3]
    
    ax_volt.set_title(f"Node {observer.node_id} (Shadow) View")
    ax_volt.set_xlim(0, SIM_DURATION)
    ax_volt.set_ylim(2.8, 4.3)
    
    lines_a = {t: ax_volt.plot([],[],'-', alpha=0.5)[0] for t in targets}
    lines_p = {t: ax_volt.plot([],[],'--')[0] for t in targets}
    line_me, = ax_volt.plot([],[],'k-')
    
    # Coverage
    ax_cov = fig.add_subplot(gs[0, 1])
    ax_cov.set_xlim(0, SIM_DURATION)
    ax_cov.set_ylim(0, 105)
    line_cov_total, = ax_cov.plot([],[],'g-', label='Total', alpha=0.3)
    line_cov_sunny, = ax_cov.plot([],[],'orange', label='Sunny', linewidth=1.5)
    line_cov_shady, = ax_cov.plot([],[],'navy', label='Shady', linewidth=1.5)
    ax_cov.set_title("Realtime Area Coverage (%)")
    ax_cov.legend(loc='lower right')
    ax_cov.grid(True)
    
    # Precompute Animation Data
    print("Pre-computing animation...")
    active_intervals = {n: nodes[n].history_active for n in nodes}
    volt_hist = {n: np.array(nodes[n].history_voltage) for n in nodes}
    pred_hist = {}
    if targets:
        for t in targets:
             pred_hist[t] = np.array(observer.history_predictions[t])
    
    tri_info = find_triangles(nodes)
    sunny_tris = [t[0] for t in tri_info if t[1]]
    shady_tris = [t[0] for t in tri_info if not t[1]]
    all_tris = [t[0] for t in tri_info]
    
    data_cov_total, data_cov_sunny, data_cov_shady = [], [], []
    
    for t in time_steps:
        # Here we use 'active_nodes' for the animation loop
        active_nodes = set()
        for nid in range(NUM_NODES):
            for s, e in active_intervals[nid]:
                if s <= t <= e:
                    active_nodes.add(nid)
                    break
        
        # Capture 'active_nodes' via closure/argument
        def count_covered(triangle_list, current_active_set):
            c = 0
            for tri in triangle_list:
                if any(n in current_active_set for n in tri): c += 1
            return c
            
        t_c = count_covered(all_tris, active_nodes)
        s_c = count_covered(sunny_tris, active_nodes)
        h_c = count_covered(shady_tris, active_nodes)
        
        data_cov_total.append((t_c / len(all_tris) * 100) if all_tris else 0)
        data_cov_sunny.append((s_c / len(sunny_tris) * 100) if sunny_tris else 0)
        data_cov_shady.append((h_c / len(shady_tris) * 100) if shady_tris else 0)
        
    data_cov_total = np.array(data_cov_total)
    data_cov_sunny = np.array(data_cov_sunny)
    data_cov_shady = np.array(data_cov_shady)
    
    def update(frame_idx):
        frame_time = time_steps[frame_idx]
        
        # 1. Colors
        cols = []
        for i in range(NUM_NODES):
            act = False
            for s,e in active_intervals[i]:
                if s <= frame_time <= e: 
                    act=True; break
            cols.append('lime' if act else 'white')
        scat.set_facecolors(cols)
        
        # 2. Voltage
        win_s = max(0, frame_time - 30000)
        ax_volt.set_xlim(win_s, frame_time+5000)
        
        me_d = volt_hist[observer.node_id]
        if len(me_d) > 0: # 데이터 존재 여부 확인
            m = (me_d[:,0]<=frame_time) & (me_d[:,0]>=win_s)
            if np.any(m): line_me.set_data(me_d[m,0], me_d[m,1])
        
        for t in targets:
            act_d = volt_hist[t]
            if len(act_d) > 0: # 데이터 존재 여부 확인
                ma = (act_d[:,0]<=frame_time) & (act_d[:,0]>=win_s)
                if np.any(ma): lines_a[t].set_data(act_d[ma,0], act_d[ma,1])
            
            if observer.use_smart_offload and t in pred_hist:
                pre_d = pred_hist[t]
                if len(pre_d)>0:
                    mp = (pre_d[:,0]<=frame_time) & (pre_d[:,0]>=win_s)
                    if np.any(mp): lines_p[t].set_data(pre_d[mp,0], pre_d[mp,1])
        
        # 3. Coverage
        line_cov_total.set_data(time_steps[:frame_idx], data_cov_total[:frame_idx])
        line_cov_sunny.set_data(time_steps[:frame_idx], data_cov_sunny[:frame_idx])
        line_cov_shady.set_data(time_steps[:frame_idx], data_cov_shady[:frame_idx])
        
        ax_topo.set_title(f"Time: {frame_time/1000:.1f}s")
        return scat,

    ani = animation.FuncAnimation(fig, update, frames=len(time_steps), 
                                  interval=ANIMATION_FRAME_STEP/ANIMATION_SPEED_FACTOR, blit=False, repeat=False)
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    if RUN_ALL_COMPARISON:
        run_comparison_experiment()
    run_main_visualization()