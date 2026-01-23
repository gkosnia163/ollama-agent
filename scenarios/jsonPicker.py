# ΔΙΟΡΘΩΣΗ: Προσθέτει τις εισαγωγές που λείπουν
import sys
import json
import os
import glob

def load_world_state(filename):
    if not os.path.exists(filename):
        print(f"[JSONPICKER] Σφάλμα: Το αρχείο {filename} δεν υπάρχει.")
        sys.exit(1)
    with open(filename, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_world_state(state, filename):
    # Αποθηκεύει τα αποτελέσματα σε νέο αρχείο 'results_...'
    result_file = "result_" + filename
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=4, ensure_ascii=False)
    print(f"[JSONPICKER] Τα αποτελέσματα αποθηκεύτηκαν στο: {result_file}")

def get_available_scenarios():
    """Επιστρέφει λίστα με τα paths των διαθέσιμων σεναρίων (scenario_*.json)"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return sorted(glob.glob(os.path.join(current_dir, "scenario_*.json")))

if __name__ == "__main__":
    SCENARIO_FILE = sys.argv[1] if len(sys.argv) > 1 else "mainscenario.json"
    # Φόρτωση του επιλεγμένου σεναρίου
    WORLD_STATE = load_world_state(SCENARIO_FILE)