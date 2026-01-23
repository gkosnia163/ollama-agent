import json, time, os, sys, glob
from datetime import datetime
from enum import Enum
from typing import List, Dict, Union
import config
import ollama
from scenarios import jsonPicker

WORLD_STATE = {}

# ==========================================
# 2. TOOLS
# ==========================================
def detect_failure_nodes() -> List[str]:
    return [n for n, d in WORLD_STATE["nodes"].items() if d["status"] == "Broken"]

def estimate_impact(node_id: str) -> Dict[str, Union[str, int]]:
    if node := WORLD_STATE["nodes"].get(node_id):
        return {"node_id": node_id, "type": node["type"], 
                "population_affected": node["population_affected"], "criticality": node["criticality"]}
    return {"error": "Node not found"}

def assign_repair_crew(node_ids: List[str], crew_ids: List[str]) -> Dict[str, str]:
    results = {}
    for n, c in zip(node_ids, crew_ids):
        crew_status = WORLD_STATE["crews"][c]["status"]
        if crew_status != "Available":
            results[f"{c}->{n}"] = f"Failed (Crew {crew_status})"
        else:
            WORLD_STATE["nodes"][n]["status"] = "Repairing"
            WORLD_STATE["crews"][c]["status"] = "Busy"  # Το crew γίνεται Busy!
            results[f"{c}->{n}"] = "Success"
            print(f"  🛠️  Crew {c} is now BUSY repairing {n}")
    return results

def check_crew_availability() -> Dict[str, str]:
    """Check status of all crews"""
    return {c: d["status"] for c, d in WORLD_STATE["crews"].items()}

# ==========================================
# 3. LLM INTERFACE
# ==========================================
def llm_call(system_prompt: str, user_context: str) -> Dict:
    try:
        response = ollama.chat(model="lfm2.5-thinking:1.2b", messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_context}
        ], format="json", options={"temperature": 0.0})
        return json.loads(response["message"]["content"])
    except:
        return {"thought": "LLM error", "action": "none", "arguments": {}}

# ==========================================
# 4. FSM & AGENT
# ==========================================
class AgentState(Enum):
    DETECT, ANALYZE, PLAN, ACT, FINAL = range(1, 6)

class InfrastructureAgent:
    def __init__(self, max_steps=20):
        self.state = AgentState.DETECT
        self.step_count = 0
        self.max_steps = max_steps
        self.memory = {"context": {}, "history": []}

    def get_system_prompt(self, remaining_nodes=None):
        base = """
            You are an Infrastructure Failure Management Agent.
            GOAL: Your primary objective is to EXECUTE REPAIRS. You must prioritize fixing nodes based on criticality (Critical > High > Medium > Low).

            AVAILABLE TOOLS:
            1. detect_failure_nodes() -> list: Returns broken node IDs.
            2. estimate_impact(node_id: str) -> dict: Returns impact metrics.
            3. assign_repair_crew(node_ids: list, crew_ids: list) -> dict: Assigns crews.
            4. finalize() -> None: Ends the mission.

            RESPONSE FORMAT:
            You must respond with a JSON object containing:
            - "thought": A brief reasoning for your action.
            - "action": The name of the tool to call.
            - "arguments": A dictionary of arguments for the tool.

            PHASE INSTRUCTIONS:
            - If phase is 'DETECT': Call detect_failure_nodes.
            - If phase is 'ANALYZE': Call estimate_impact for a node.
            - If phase is 'PLAN': Call assign_repair_crew.
            - PRIORITY RULE: You MUST repair 'Critical' nodes before 'High', and 'High' before 'Low'.
            - MATCHING RULE: 
                - 'General' crews can fix ANY node.
                - Specialized crews (e.g. 'Electrical') can only fix their specific type.
                - NEVER assign a mismatched crew (e.g. 'Water' crew to 'Power' node).

            User Input: { "phase": "ANALYZE", "context": { "failures": ["Node_99"] } }
            Model Response:
            {
            "thought": "I found a failure at Node_99. I need to check its impact.",
            "action": "estimate_impact",
            "arguments": { "node_id": "Node_99" }
            }

            User Input: { "phase": "PLAN", "context": { "impact_reports": [{"node_id": "Node_99", "criticality": "High"}] }, "available_crews": ["Crew_Alpha"] }
            Model Response:
            {
            "thought": "Node_99 is High criticality. I will assign Crew_Alpha.",
            "action": "assign_repair_crew",
            "arguments": { "node_ids": ["Node_99"], "crew_ids": ["Crew_Alpha"] }
            }
            """
        
        
        prompts = {
            AgentState.DETECT: "CURRENT STATE: DETECT\nACTION: detect_failure_nodes",
            AgentState.ANALYZE: f"CURRENT STATE: ANALYZE\nREMAINING: {remaining_nodes or 'Analyze one node'}\nACTION: estimate_impact",
            AgentState.PLAN: "CURRENT STATE: PLAN\nACTION: none",
            AgentState.ACT: "CURRENT STATE: ACT\nACTION: assign_repair_crew"
        }
        
        return base + "\n" + prompts.get(self.state, "")

    def step(self):
        self.step_count += 1
        print(f"\n{'='*50}\nSTEP {self.step_count} | STATE: {self.state.name}\n{'='*50}")

        # Get current status
        available_crews = [c for c, d in WORLD_STATE["crews"].items() if d["status"] == "Available"]
        busy_crews = [c for c, d in WORLD_STATE["crews"].items() if d["status"] == "Busy"]
        failures = self.memory["context"].get("failures", [])
        analyzed = [r["node_id"] for r in self.memory["context"].get("impact_reports", [])]
        remaining = [n for n in failures if n not in analyzed] if self.state == AgentState.ANALYZE else []
        
        context = {
            "state": self.state.name,
            "failed_nodes": failures,
            "analyzed_nodes": analyzed,
            "remaining_to_analyze": remaining,
            "available_crews": available_crews,
            "busy_crews": busy_crews,
            "all_crews_status": check_crew_availability()
        }
        
        print(f"[CONTEXT]: {json.dumps(context, indent=2)}")
        
        # Get LLM decision
        decision = llm_call(self.get_system_prompt(remaining), json.dumps(context))
        print(f"[DECISION]: {json.dumps(decision, indent=2)}")
        
        action = decision.get("action", "none")
        args = decision.get("arguments", {})
        thought = decision.get("thought", "No reasoning")
        
        print(f"[THOUGHT]: {thought}")
        print(f"[ACTION]: {action}")
        
        # Execute based on state
        observation = self.execute_state_action(action, args, failures, analyzed, remaining, available_crews)
        
        print(f"[OBSERVATION]: {observation}")
        
        # Save history
        self.memory["history"].append({
            "step": self.step_count, "state": self.state.name,
            "thought": thought, "action": action, "observation": observation,
            "crews_status": check_crew_availability()
        })

    def execute_state_action(self, action, args, failures, analyzed, remaining, available_crews):
        # DETECT state
        if self.state == AgentState.DETECT:
            if action != "detect_failure_nodes":
                action = "detect_failure_nodes"
            
            obs = detect_failure_nodes()
            self.memory["context"]["failures"] = obs
            self.state = AgentState.ANALYZE if obs else AgentState.FINAL
            return obs
        
        # ANALYZE state
        elif self.state == AgentState.ANALYZE:
            # Optimization: Analyze ALL remaining nodes in one go to save steps
            reports = []
            for node_id in remaining:
                if node_id in failures:
                    obs = estimate_impact(node_id)
                    reports.append(obs)
            
            if reports:
                self.memory["context"].setdefault("impact_reports", []).extend(reports)
                self.state = AgentState.PLAN
                return {"analyzed_nodes": [r["node_id"] for r in reports]}
            return {"error": "No nodes to analyze"}
        
        # PLAN state
        elif self.state == AgentState.PLAN:
            impacts = self.memory["context"].get("impact_reports", [])
            
            if not impacts:
                self.state = AgentState.FINAL
                return {"error": "No impacts to plan"}
            
            # Sort by priority
            priority = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
            impacts.sort(key=lambda x: (priority[x["criticality"]], x["population_affected"]), reverse=True)
            
            # Smart Matching Logic
            plan = []
            used_crews = set()
            crew_details = {c: WORLD_STATE["crews"][c] for c in available_crews}

            for imp in impacts:
                node_type = imp["type"]
                candidates = []
                
                # Find compatible crews
                for c_id, c_data in crew_details.items():
                    if c_id not in used_crews:
                        if c_data["specialty"] == node_type or c_data["specialty"] == "General":
                            # Priority: Specific (0) > General (1)
                            score = 0 if c_data["specialty"] == node_type else 1
                            candidates.append((score, c_id))
                
                if candidates:
                    candidates.sort() # Sort by score (Specific first)
                    best_crew = candidates[0][1]
                    plan.append({"node": imp["node_id"], "crew": best_crew})
                    used_crews.add(best_crew)
            
            self.memory["context"]["repair_plan"] = plan
            
            if plan:
                self.state = AgentState.ACT
                return {"plan": plan}
            else:
                self.state = AgentState.FINAL
                return {"error": "No available crews for repair"}
        
        # ACT state
        elif self.state == AgentState.ACT:
            plan = self.memory["context"].get("repair_plan", [])
            
            # Force execution of the calculated plan (ignore LLM args to avoid hallucinations)
            node_ids = [p["node"] for p in plan]
            crew_ids = [p["crew"] for p in plan]
            
            obs = assign_repair_crew(node_ids, crew_ids)
            self.state = AgentState.FINAL
            
            return obs
        
        return {"error": "Invalid state"}

    def run(self):
        print("--- INFRASTRUCTURE AGENT STARTED ---")
        self.state = AgentState.DETECT # Force Start State
        
        while self.state != AgentState.FINAL and self.step_count < self.max_steps:
            self.step()
            time.sleep(1)

        print("\n--- AGENT FINISHED ---")
        print("Final World State (Check if nodes are Repairing):")
        print(json.dumps(WORLD_STATE["nodes"], indent=2))
        
        # --- ΠΡΟΣΘΗΚΗ ΓΙΑ ΑΠΟΘΗΚΕΥΣΗ LOGS ---
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Αν δεν έχεις το config.runs_path, βάλε απλά "run_" + ts + ".json"
        log_filename = f"run_log_{ts}.json" 
        with open(log_filename, "w", encoding="utf-8") as f:
            # Αποθηκεύει όλη τη μνήμη και το ιστορικό του Agent
            json.dump(self.memory, f, indent=2, ensure_ascii=False)
        print(f"\n Το Log αποθηκεύτηκε στο αρχείο: {log_filename}")

if __name__ == "__main__":
    # Find all scenario files in the scenarios directory
    scenario_files = jsonPicker.get_available_scenarios()

    print(f"Found {len(scenario_files)} scenarios to run.")
    print(f"[CORE] Found {len(scenario_files)} scenarios to run.")

    for scenario_path in scenario_files:
        scenario_name = os.path.basename(scenario_path)
        print(f"\n{'#'*50}\nRUNNING SCENARIO: {scenario_name}\n{'#'*50}")
        print(f"\n{'#'*50}\n[CORE] RUNNING SCENARIO: {scenario_name}\n{'#'*50}")
        
        # Load scenario into WORLD_STATE
        WORLD_STATE.clear()
        WORLD_STATE.update(jsonPicker.load_world_state(scenario_path))
        
        print("Starting Infrastructure Agent...")
        print("[CORE] Starting Infrastructure Agent...")
        agent = InfrastructureAgent(max_steps=15)
        agent.run()        